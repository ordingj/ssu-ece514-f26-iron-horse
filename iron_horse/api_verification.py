"""Independently replay API source potentials, eligibility, and checkpoint scores."""
import argparse
import bisect
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
from .verification import verify as verify_scores
from .api_checkpoint import verify_api_source

HOUR = 3600000000000
TZ = 'America/Los_Angeles'
SITES = tuple(f'SDI-12-LS-US915-{i}' for i in (1, 2, 4, 5))


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''): result.update(chunk)
    return result.hexdigest()


def read_public_potentials(source):
    """Reconstruct value and quality sets directly from frozen response bytes."""
    snapshot = json.loads(source.read_text())
    values, provenance = defaultdict(set), defaultdict(set)
    returned = 0; page_rows = defaultdict(int)
    for record in snapshot['pages']:
        path = source.parent / record['file']
        if path.is_symlink() or not path.resolve().is_relative_to(source.parent.resolve()):
            raise ValueError('Source page leaves its snapshot directory')
        assert digest(path) == record['sha256']
        page = json.loads(gzip.decompress(path.read_bytes()))
        page_rows[record['request']['measurement']] += len(page['readings'])
        if record['request']['measurement'] != 'matric_potential_kpa': continue
        for row in page['readings']:
            if row.get('device_name') not in SITES: continue
            flag = row.get('potential_quality')
            if flag not in {'reported_kpa_calibration_not_validated', 'unknown_first_field_units'}:
                raise ValueError('Source lacks supported matric quality provenance')
            returned += 1
            key = row['device_name'], pd.Timestamp(row['time']).value
            values[key].add(float(row['value']))
            provenance[key].add(tuple(row[field] for field in
                ('response_format', 'checksum_status', 'potential_quality', 'temperature_quality')))
    return snapshot, values, provenance, returned, page_rows


def verify(output):
    """Verify source units, observed potentials, and every scored forecast."""
    if output.resolve().is_relative_to((ROOT / 'results').resolve()):
        raise ValueError('Recorded results are read-only. Verify a local output under runs/')
    receipt = output / 'independent_api_verification.json'
    if receipt.exists(): raise FileExistsError('Independent API verification already exists')
    prep = json.loads((output / 'preparation.json').read_text())
    if prep.get('source_kind') != 'public_influx_api':
        raise ValueError('Use --legacy-csv to verify a historical CSV reproduction')
    verify_api_source(prep)
    source = Path(prep['source']); assert digest(source) == prep['source_sha256']
    snapshot, values, provenance, returned, page_rows = read_public_potentials(source)
    potential = joblib.load(output / 'cache/potential.joblib')
    inputs = pd.read_parquet(output / 'cache/hourly_inputs.parquet')
    labeled = pd.concat([pd.read_parquet(output / 'cache/development_examples.parquet'),
                         pd.read_parquet(output / 'cache/test_examples.parquet')], ignore_index=True)
    replayed = 0
    for site in SITES:
        pairs = sorted((stamp, next(iter(items))) for (device, stamp), items in values.items()
                       if device == site and len(items) == 1 and len(provenance[device, stamp]) == 1
                       and next(iter(provenance[device, stamp]))[2] == 'reported_kpa_calibration_not_validated')
        times = [p[0] for p in pairs]; numeric = [p[1] for p in pairs]
        np.testing.assert_array_equal(potential[site][0], times)
        np.testing.assert_array_equal(potential[site][1], numeric)
        observed = pd.Series(numeric, index=pd.to_datetime(times, unit='ns', utc=True))
        bins = observed.groupby(observed.index.ceil('h')).median()
        frame = inputs[inputs.site == site].sort_values('time')
        hourly = bins.reindex(pd.DatetimeIndex(frame.time)).to_numpy(float)
        np.testing.assert_allclose(frame.current_potential_kpa, hourly, equal_nan=True, atol=0, rtol=0)
        for width, name, minimum in [(6, 'trend_6h_kpa_per_h', 4), (24, 'trend_24h_kpa_per_h', 18)]:
            expected = []
            counts = []
            for i in range(len(hourly)):
                y = hourly[max(0, i + 1 - width):i + 1]; good = np.isfinite(y)
                counts.append(int(good.sum()))
                expected.append(float(np.polyfit(np.arange(len(y))[good], y[good], 1)[0]) if good.sum() >= minimum else np.nan)
            np.testing.assert_allclose(frame[name], expected, equal_nan=True, atol=1e-10, rtol=1e-10)
            np.testing.assert_array_equal(frame[f'history_hours_{width}h'], counts)
        good = np.isfinite(hourly) & (frame.history_hours_6h.to_numpy() >= 4) & (frame.history_hours_24h.to_numpy() >= 18)
        np.testing.assert_array_equal(frame.forecast_eligible, good)
        np.testing.assert_array_equal(frame.currently_dry, np.isfinite(hourly) & (hourly <= -500))
        np.testing.assert_array_equal(frame.primary_input_eligible, good & (hourly > -500))
        for row in labeled[labeled.site == site].itertuples():
            anchor = row.time.value
            left, right = bisect.bisect_right(times, anchor), bisect.bisect_right(times, anchor + 24 * HOUR)
            selected_times = times[left:right]
            occupied = {(t - anchor - 1) // HOUR for t in selected_times}
            gap = max(b - a for a, b in zip([anchor] + selected_times, selected_times + [anchor + 24 * HOUR]))
            label_ok = len(occupied) >= 20 and gap <= 2 * HOUR
            assert row.future_occupied_hours == len(occupied)
            assert abs(row.future_max_gap_hours - gap / HOUR) < 1e-12
            assert bool(row.evaluation_eligible) == bool(row.primary_input_eligible and label_ok)
            if label_ok: assert row.target == int(any(v <= -500 for v in numeric[left:right]))
            else: assert np.isnan(row.target)
            end = {'train': '2026-06-01', 'validation': '2026-07-01', 'test': '2026-09-01'}[row.partition]
            assert row.time + pd.Timedelta(hours=24) < pd.Timestamp(end, tz=TZ)
            replayed += 1
    verify_scores(output, verify_source=True)
    test = pd.read_csv(output / 'test_predictions.csv')
    columns = json.loads((output / 'feature_schema.json').read_text())['columns']
    for kind, prefix in [('random_forest', 'rf'), ('logistic_regression', 'lr')]:
        model = joblib.load(output / 'models' / f'{kind}.joblib')
        probability = model.predict_proba(test[columns])[:, list(model.classes_).index(1)]
        np.testing.assert_allclose(probability, test[prefix + '_score'], atol=1e-14, rtol=1e-14)
        np.testing.assert_array_equal(probability >= .70, test[prefix + '_prediction'])
    result = {'verified_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
        'verifier_sha256': digest(Path(__file__)), 'source_manifest_sha256': digest(source),
        'source_page_hashes_checked': len(snapshot['pages']), 'public_rows_by_measurement': dict(sorted(page_rows.items())),
        'returned_selected_matric_rows': returned, 'distinct_matric_keys': len(values),
        'conflicting_matric_keys': sum(len(v) > 1 or len(provenance[k]) > 1 for k, v in values.items()),
        'unknown_unit_matric_keys_excluded': sum(any(p[2] == 'unknown_first_field_units' for p in q) for q in provenance.values()),
        'quality_policy': prep['quality_policy'],
        'hourly_input_rows_replayed': len(inputs), 'nonpurged_labels_replayed': replayed,
        'all_potential_arrays_match_public_pages': True, 'all_hourly_medians_and_slopes_match': True,
        'all_labels_and_eligibility_match': True, 'both_frozen_models_replay': True,
        'test_predictions': len(test), 'original_score_verifier_sha256': digest(ROOT / 'iron_horse/verification.py')}
    receipt.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    verify(parser.parse_args(argv).output.resolve())


if __name__ == '__main__': main()
