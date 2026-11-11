"""Rerun the fixed checkpoint using a frozen public InfluxDB response snapshot."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import math
import platform
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib
import numpy as np
import pandas as pd
import polars as pl
import sklearn
from threadpoolctl import threadpool_limits

from . import checkpoint
from .core import ROOT, START, END, MATRIC, WEATHER, WEATHER_FIELDS, ns, now, save_json, sha256, window_stat

CONTRACT_FILE = ROOT / 'metadata/public_api_contract.json'
CONTRACT = json.loads(CONTRACT_FILE.read_text())
API = CONTRACT['endpoint']
QUALITY_FIELDS = ('response_format', 'checksum_status', 'potential_quality', 'temperature_quality')
DEFAULT_SNAPSHOT = ROOT / 'runs/influx-source'
DEFAULT_OUTPUT = ROOT / 'runs/influx-checkpoint'
SOIL = {f'soil_{kind}{suffix}': f'device_frmpayload_data_{raw}_SOIL{suffix.replace("_", "")}'
        for kind, raw in [('water', 'water'), ('temperature', 'temp')]
        for suffix in ('', '_1', '_2', '_3', '_4')}
MEASUREMENTS = ('matric_potential_kpa',) + tuple('atmos_' + f for f in WEATHER_FIELDS) + tuple(SOIL)
INVENTORY = json.loads((ROOT / 'metadata/devices.json').read_text())['by_device_name']
ADAPTER_FILES = (Path(__file__), CONTRACT_FILE)
LIMIT = 10000


def adapter_hashes():
    return {str(p.relative_to(ROOT)): sha256(p) for p in ADAPTER_FILES}


def save_snapshot_json(path, value):
    """Publish a complete receipt atomically so interrupted writes can resume."""
    temporary = path.with_suffix(path.suffix + '.partial')
    save_json(temporary, value)
    temporary.replace(path)


def request_page(params):
    """Read a bounded public response, retrying transient failures without credentials."""
    request = Request(API + '?' + urlencode(params), headers={'Accept': 'application/json'})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=60) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError('API response exceeds 16 MiB')
            return raw
        except (HTTPError, URLError, TimeoutError) as error:
            if isinstance(error, HTTPError):
                error.close()
            if isinstance(error, HTTPError) and error.code not in {429, 500, 502, 503, 504}:
                raise
            if attempt == 3: raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('API request did not complete')


def selected(row):
    device, measurement = row.get('device_name'), row.get('measurement')
    if measurement == 'matric_potential_kpa': return device in MATRIC
    if measurement and measurement.startswith('atmos_'): return device == WEATHER
    return measurement in SOIL and device in INVENTORY and device.startswith(('SE01-', 'SE0X-'))


def validate_page(page, params):
    """Reject mismatched windows, malformed readings, and non-advancing cursors."""
    left, right = pd.Timestamp(params['start']), pd.Timestamp(params['stop'])
    for key, expected in (('start', left), ('stop', right)):
        if pd.Timestamp(page[key]) != expected:
            raise ValueError('API response window differs from the request')
    if any(page[k] != params[k] for k in ('measurement', 'limit', 'offset')):
        raise ValueError('API response selection differs from the request')
    if page.get('source') != 'influxdb-standby' or not isinstance(page['readings'], list):
        raise ValueError('API source or readings are invalid')
    cursor = page['next_offset']
    if cursor is not None and (type(cursor) is not int or cursor != params['offset'] + LIMIT or cursor > 1000000):
        raise ValueError('API cursor does not advance by the page limit')
    if len(page['readings']) > LIMIT: raise ValueError('API page exceeds its row limit')
    for row in page['readings']:
        if not {'device_name', 'dev_eui', 'sensor', 'block', 'slope'} <= row.keys():
            raise ValueError('API metadata fields are missing')
        stamp = pd.Timestamp(row['time'])
        if stamp.tzinfo is None or not left <= stamp < right:
            raise ValueError('API reading lies outside its requested window')
        value = row['value']
        if row['measurement'] != params['measurement'] or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('API reading has an invalid measurement or value')
        if selected(row):
            if row['measurement'] == CONTRACT['potential_measurement']:
                if params.get('include_quality') != 'true':
                    raise ValueError('Matric requests must include quality provenance')
                validate_quality(row)
            if not row.get('dev_eui') or not row.get('sensor'):
                raise ValueError('Selected API reading has no stable identity')
            if any(row.get(k) != INVENTORY[row['device_name']][k] for k in ('block', 'slope')):
                raise ValueError('API metadata differs from the captured device inventory')


def validate_quality(row):
    """Require explicit, consistent matric provenance before accepting numeric units."""
    if not set(QUALITY_FIELDS) <= row.keys():
        raise ValueError('Matric quality provenance is missing; request include_quality=true')
    if row['value'] in CONTRACT['matric_fault_values']:
        raise ValueError('Matric quality provenance includes a documented fault code')
    pairs = CONTRACT['response_checksum_pairs']
    if row['response_format'] not in pairs or row['checksum_status'] != pairs[row['response_format']]:
        raise ValueError('Matric response format and checksum quality are inconsistent')
    if row['potential_quality'] not in CONTRACT['potential_quality_values'] or row['temperature_quality'] not in CONTRACT['temperature_quality_values']:
        raise ValueError('Matric quality flags are outside the supported contract')


def require_quality_requests(manifest):
    """Reject old snapshots before reading their pages or inferring quality from numbers."""
    for record in manifest['pages']:
        request = record['request']
        if request['measurement'] == CONTRACT['potential_measurement'] and request.get('include_quality') != 'true':
            raise ValueError('Snapshot lacks matric quality provenance; capture a fresh snapshot with include_quality=true')
    if 'measurements' in manifest and (manifest.get('schema_version') != CONTRACT['schema_version'] or manifest.get('quality_policy') != CONTRACT['quality_policy']):
        raise ValueError('Snapshot lacks the current quality contract; choose a fresh snapshot directory')


def check_api(*, get=None):
    """Probe the required public contract without saving readings or starting a download."""
    params = dict(measurement=CONTRACT['potential_measurement'],
        start='2026-08-25T07:00:00+00:00', stop='2026-08-25T07:05:00+00:00',
        include_metadata='true', include_quality='true', limit=LIMIT, offset=0)
    try:
        raw = (get or request_page)(params)
    except HTTPError as error:
        error.close()
        if error.code == 400:
            raise ValueError('The live API rejects quality-enabled requests. It must support include_quality=true before a new checkpoint download.') from error
        raise
    page = json.loads(raw); validate_page(page, params)
    selected_rows = [row for row in page['readings'] if selected(row)]
    if not selected_rows:
        raise ValueError('The capability probe returned no matric quality evidence')
    return {'endpoint': API, 'quality_policy': CONTRACT['quality_policy'],
            'quality_contract_supported': True, 'sample_readings': len(selected_rows)}


def checked_page_path(root, record):
    """Return a contained page path only when its frozen digest matches."""
    path = root / record['file']
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or sha256(path) != record['sha256']:
        raise ValueError('API snapshot page changed or leaves its snapshot directory')
    return path


def read_record(root, record):
    """Verify and decode one immutable cached page."""
    path = checked_page_path(root, record)
    page = json.loads(gzip.decompress(path.read_bytes()))
    validate_page(page, record['request'])
    return page


def capture_window(measurement, start, stop, root, *, get=request_page):
    """Capture every page in a fixed window, reusing verified completed pages on restart."""
    left, right = pd.Timestamp(start), pd.Timestamp(stop)
    if left.tzinfo is None or right.tzinfo is None or not pd.Timedelta(0) < right - left <= pd.Timedelta(days=31):
        raise ValueError('Select a timezone-aware window of at most 31 days')
    root = Path(root); (root / 'pages').mkdir(parents=True, exist_ok=True)
    records, offset = [], 0
    while True:
        params = dict(measurement=measurement, start=left.isoformat(), stop=right.isoformat(),
                      include_metadata='true', limit=LIMIT, offset=offset)
        if measurement == CONTRACT['potential_measurement']:
            params['include_quality'] = 'true'
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        path = root / 'pages' / (key + '.json.gz')
        receipt = path.with_suffix('.receipt.json')
        if receipt.exists():
            record = json.loads(receipt.read_text())
            if record['request'] != params: raise ValueError('Cached API query changed')
            page = read_record(root, record)
        else:
            raw = get(params); page = json.loads(raw); validate_page(page, params)
            path.write_bytes(gzip.compress(raw, mtime=0))
            record = {'file': str(path.relative_to(root)), 'sha256': sha256(path),
                      'retrieved_at_utc': now(), 'request': params, 'readings': len(page['readings'])}
            save_snapshot_json(receipt, record)
        records.append(record)
        if page['next_offset'] is None: return records
        offset = page['next_offset']


def download(root):
    """Freeze the complete registered calendar without a CSV or personal token."""
    root = Path(root)
    if (root / 'snapshot.json').exists():
        verify_snapshot(root); return
    check_api()
    records = []
    left = START
    while left < END:
        right = min(left + pd.Timedelta(days=7), END)
        def capture(measurement):
            pages = capture_window(measurement, left.isoformat(), right.isoformat(), root)
            print(f'{left.date()} {measurement}: {sum(p["readings"] for p in pages)} readings', flush=True)
            return pages
        with ThreadPoolExecutor(max_workers=3) as pool:
            for pages in pool.map(capture, MEASUREMENTS):
                records.extend(pages)
        left = right
    save_snapshot_json(root / 'snapshot.json', {'schema_version': CONTRACT['schema_version'],
        'quality_policy': CONTRACT['quality_policy'], 'api': API, 'start': START.isoformat(), 'stop': END.isoformat(),
        'measurements': list(MEASUREMENTS), 'completed_at_utc': now(), 'pages': records,
        'atomic_database_snapshot': False, 'metadata_is_deployment_inventory': True})
    verify_snapshot(root)


def verify_snapshot(root):
    """Check every page hash and each complete cursor chain in a source snapshot."""
    root = Path(root); manifest = json.loads((root / 'snapshot.json').read_text())
    require_quality_requests(manifest)
    chains = {}
    for record in manifest['pages']:
        page = read_record(root, record)
        p = record['request']; key = (p['measurement'], p['start'], p['stop'])
        expected = chains.get(key, 0)
        if expected is None or p['offset'] != expected:
            raise ValueError('API snapshot has a missing, repeated, or reordered page')
        chains[key] = page['next_offset']
    if not chains or any(cursor is not None for cursor in chains.values()):
        raise ValueError('API snapshot has an incomplete cursor chain')
    if 'measurements' in manifest:
        expected = set(); left = START
        while left < END:
            right = min(left + pd.Timedelta(days=7), END)
            expected.update((m, left.isoformat(), right.isoformat()) for m in MEASUREMENTS)
            left = right
        if set(chains) != expected or manifest['measurements'] != list(MEASUREMENTS) or manifest['start'] != START.isoformat() or manifest['stop'] != END.isoformat() or manifest['api'] != API:
            raise ValueError('API snapshot differs from the fixed calendar or measurement contract')
    return manifest


def clean_snapshot(root, destination):
    """Collapse duplicate numeric keys and preserve conflicting-key exclusions."""
    manifest = verify_snapshot(root)
    parts = []
    for record in manifest['pages']:
        rows = [{k: row.get(k) for k in ('time', 'device_name', 'dev_eui', 'sensor', 'measurement', 'value', 'block', 'slope', *QUALITY_FIELDS)}
                for row in read_record(root, record)['readings'] if selected(row)]
        if rows: parts.append(pl.DataFrame(rows, infer_schema_length=None).with_columns(pl.col('value').cast(pl.Float64)))
    if not parts: raise ValueError('API snapshot has no selected observations')
    frame = pl.concat(parts, how='vertical_relaxed').unique().with_columns(
        pl.col('time').str.to_datetime(time_zone='UTC', time_unit='ns'))
    identities = frame.group_by('device_name').agg(pl.col('dev_eui').n_unique().alias('ids'), pl.col('sensor').n_unique().alias('aliases'))
    if identities.filter((pl.col('ids') != 1) | (pl.col('aliases') != 1)).height:
        raise ValueError('Device identity changed within the API snapshot')
    clean = frame.group_by('device_name', 'measurement', 'time').agg(
        pl.col('value').first(), pl.col('value').n_unique().alias('value_versions'),
        pl.col('block').first(), pl.col('slope').first(), pl.len().alias('deduplicated_rows'),
        *[pl.col(field).first() for field in QUALITY_FIELDS],
        pl.struct(QUALITY_FIELDS).n_unique().alias('quality_versions'))
    clean = clean.with_columns(((pl.col('value_versions') == 1) & (pl.col('quality_versions') == 1)).alias('valid_key')).sort('device_name', 'measurement', 'time')
    clean.write_parquet(destination, compression='zstd')
    return clean


def build_inputs(cleaned, output):
    """Use public numeric observations in the original feature and timing rules."""
    df = cleaned.to_pandas(); accepted = df[df.valid_key]
    potential = {}
    for device in MATRIC:
        rows = accepted[(accepted.device_name == device) & (accepted.measurement == 'matric_potential_kpa') &
                        (accepted.potential_quality == CONTRACT['accepted_potential_quality'])].sort_values('time')
        potential[device] = (ns(rows.time), rows.value.to_numpy(float))
    weather = accepted[accepted.device_name == WEATHER]
    features = {}
    for field in WEATHER_FIELDS:
        rows = weather[weather.measurement == 'atmos_' + field].sort_values('time')
        features[f'weather__{field}__24h'] = window_stat(ns(rows.time), rows.value.to_numpy(float), field == 'precipitation_mm')
    soil = accepted[accepted.measurement.isin(SOIL)].copy()
    soil['numeric'] = soil.value
    soil['measurement'] = soil.measurement.map(SOIL)
    soil['slot'] = checkpoint.soil_slot_names(soil)
    inventory = pd.read_csv(ROOT / 'metadata/probe_inventory.csv')
    inventory = inventory[inventory.device_name.str.match(r'^SE0[1X]-LS-\d+$') & inventory.measurement.str.match(r'^device_frmpayload_data_(water|temp)_SOIL[1-4]?$')]
    slots = sorted(checkpoint.soil_slot_names(inventory).unique())
    save_json(output / 'cleaning_audit.json', {'measurement_keys': len(df), 'conflicting_keys': int((~df.valid_key).sum()),
        'metadata_disagreements': [], 'soil_quality_flag_available': False, 'raw_packet_available': False,
        'cc_raw_unit_check_available': False, 'quality_provenance_available': True,
        'quality_policy': CONTRACT['quality_policy'], 'numeric_acceptance': 'public scalar values with explicit reported-kPa provenance'})
    save_json(output / 'decode_audit.json', {d: {'public_potential_observations': len(potential[d][0]),
        'unknown_unit_keys_excluded': int(((accepted.device_name == d) &
            (accepted.measurement == 'matric_potential_kpa') &
            (accepted.potential_quality == 'unknown_first_field_units')).sum())} for d in MATRIC})
    return checkpoint.assemble_inputs(potential, soil, features, slots, output)


def prepared_cache_hashes(cache):
    """Hash the declared scientific cache, excluding incidental operating-system files."""
    names = ('clean_api_measurements.parquet', 'hourly_inputs.parquet', 'potential.joblib')
    return {name: sha256(cache / name) for name in names}


def prepare(snapshot, output):
    if output.exists(): raise FileExistsError('Choose a new API checkpoint output directory')
    manifest = json.loads((snapshot / 'snapshot.json').read_text())
    if 'measurements' not in manifest: raise ValueError('A complete study snapshot is required')
    if sklearn.__version__ != '1.9.1': raise RuntimeError('This protocol requires scikit-learn 1.9.1')
    cache = output / 'cache'; cache.mkdir(parents=True)
    clean = clean_snapshot(snapshot, cache / 'clean_api_measurements.parquet')
    inputs, potential = build_inputs(clean, output)
    inputs.to_parquet(cache / 'hourly_inputs.parquet', index=False)
    joblib.dump(potential, cache / 'potential.joblib')
    source = (snapshot / 'snapshot.json').resolve()
    save_json(output / 'preparation.json', {'prepared_at_utc': now(), 'source': str(source), 'source_kind': 'public_influx_api',
        'quality_policy': CONTRACT['quality_policy'],
        'source_sha256': sha256(source), 'source_bytes': source.stat().st_size,
        'implementation_hashes': checkpoint.implementation_hashes(), 'adapter_hashes': adapter_hashes(),
        'python': platform.python_version(), 'scikit_learn': sklearn.__version__, 'scheduled_hours': len(inputs),
        'test_labels_constructed': False, 'feature_schema_sha256': sha256(output / 'feature_schema.json'),
        'derived_hashes': prepared_cache_hashes(cache)})
    print('API preparation complete. Test labels have not been constructed.', flush=True)


def verify_api_source(prep):
    """Bind the public adapter and every response page to the prepared source."""
    source = Path(prep['source'])
    if prep['adapter_hashes'] != adapter_hashes() or sha256(source) != prep['source_sha256']:
        raise ValueError('API adapter or snapshot manifest changed after preparation')
    manifest = json.loads(source.read_text())
    require_quality_requests(manifest)
    if prep.get('quality_policy') != CONTRACT['quality_policy']:
        raise ValueError('Preparation lacks the current matric quality policy')
    # Preparation already validated these exact bytes and cursor chains.
    for record in manifest['pages']:
        checked_page_path(source.parent, record)



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--stage', choices=['download', 'prepare', 'develop', 'evaluate', 'verify', 'all'], default='all')
    args = parser.parse_args(argv)
    snapshot, output = args.snapshot.resolve(), args.output.resolve()
    if output.is_relative_to(ROOT / 'results'):
        parser.error('Recorded results are read-only. Choose an output directory under runs/')
    if not snapshot.is_relative_to(ROOT / 'runs') or not output.is_relative_to(ROOT / 'runs') or snapshot.is_relative_to(output) or output.is_relative_to(snapshot):
        parser.error('Use separate snapshot and output directories under runs/')
    if args.stage == 'prepare':
        try:
            require_quality_requests(json.loads((snapshot / 'snapshot.json').read_text()))
        except (OSError, ValueError) as error:
            parser.error(f'{error}. Run python -m iron_horse doctor, then run --stage download')
    if args.stage in {'prepare', 'all'} and output.exists():
        parser.error('Choose a new API checkpoint output directory')
    if args.stage in {'develop', 'evaluate', 'verify'}:
        prep = json.loads((output / 'preparation.json').read_text())
        if prep.get('source_kind') != 'public_influx_api':
            parser.error('This output was not prepared from the public API')
    with threadpool_limits(limits=2):
        if args.stage in {'download', 'all'}: download(snapshot)
        if args.stage in {'prepare', 'all'}: prepare(snapshot, output)
        if args.stage in {'develop', 'all'}:
            if not checkpoint.develop(output): return
        if args.stage in {'evaluate', 'all'}:
            checkpoint.evaluate(output)
        if args.stage == 'verify':
            from .api_verification import verify
            verify(output)


if __name__ == '__main__': main()
