"""Compare saved CSV and API checkpoint inputs without fitting or changing rules."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from iron_horse.matric import decode_response


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def compare(original, current):
    if original.resolve() == current.resolve():
        raise ValueError('Choose separate historical and API output directories')
    for name in ('source_comparison.json', 'source_feature_comparison.csv'):
        if (current / name).exists(): raise FileExistsError('Source comparison already exists')
    old_prep = json.loads((original / 'preparation.json').read_text())
    new_prep = json.loads((current / 'preparation.json').read_text())
    assert old_prep.get('source_kind') != 'public_influx_api'
    assert new_prep.get('source_kind') == 'public_influx_api'
    assert digest(original / 'cache/clean_measurements.parquet') == old_prep['derived_hashes']['clean_measurements.parquet']
    for folder in (original, current):
        prep = json.loads((folder / 'preparation.json').read_text())
        for name in ('potential.joblib', 'hourly_inputs.parquet'):
            assert digest(folder / 'cache' / name) == prep['derived_hashes'][name]
    old = joblib.load(original / 'cache/potential.joblib')
    new = joblib.load(current / 'cache/potential.joblib')
    raw = pl.scan_parquet(original / 'cache/clean_measurements.parquet').filter(
        pl.col('measurement') == 'device_frmpayload_data_data_sum').select(
            'device_name', 'time', 'value').collect().to_pandas()
    rows = []
    for site, (a_time, a_value) in old.items():
        b_time, b_value = new[site]
        common, a, b = np.intersect1d(a_time, b_time, return_indices=True)
        old_only = np.setdiff1d(a_time, b_time)
        old_rows = raw[(raw.device_name == site) & raw.time.isin(pd.to_datetime(old_only, unit='ns', utc=True))]
        formats = Counter()
        for response in old_rows.value:
            reading = decode_response(response)
            formats[reading.response_format if reading else 'parse_rejected'] += 1
        rows.append({'site': site, 'csv_accepted_observations': len(a_time), 'api_accepted_observations': len(b_time),
            'common_timestamps': len(common), 'same_values_on_common_timestamps': int((a_value[a] == b_value[b]).sum()),
            'different_values_on_common_timestamps': int((a_value[a] != b_value[b]).sum()),
            'csv_only_timestamps': len(old_only), 'api_only_timestamps': len(b_time) - len(common),
            'csv_only_response_formats': dict(formats)})
    old = pd.read_parquet(original / 'cache/hourly_inputs.parquet').set_index(['site', 'time']).sort_index()
    new = pd.read_parquet(current / 'cache/hourly_inputs.parquet').set_index(['site', 'time']).sort_index()
    pd.testing.assert_index_equal(old.index, new.index)
    columns = json.loads((current / 'feature_schema.json').read_text())['columns']
    feature_rows = []
    for name in columns:
        a, b = old[name].to_numpy(float), new[name].to_numpy(float)
        both = np.isfinite(a) & np.isfinite(b)
        feature_rows.append({'feature': name, 'scheduled_rows': len(a),
            'both_present': int(both.sum()), 'both_missing': int((~np.isfinite(a) & ~np.isfinite(b)).sum()),
            'csv_only_present': int((np.isfinite(a) & ~np.isfinite(b)).sum()),
            'api_only_present': int((~np.isfinite(a) & np.isfinite(b)).sum()),
            'different_when_both_present_atol_1e_10': int((both & ~np.isclose(a, b, rtol=0, atol=1e-10)).sum())})
    pd.DataFrame(feature_rows).to_csv(current / 'source_feature_comparison.csv', index=False)
    result = {'compared_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
        'comparison_script_sha256': digest(Path(__file__)),
        'csv_preparation_sha256': digest(original / 'preparation.json'),
        'public_preparation_sha256': digest(current / 'preparation.json'),
        'potential_comparisons': rows, 'scheduled_input_rows': len(old),
        'causal_attribution': False}
    (current / 'source_comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('current', type=Path)
    args = parser.parse_args()
    compare(args.original.resolve(), args.current.resolve())
