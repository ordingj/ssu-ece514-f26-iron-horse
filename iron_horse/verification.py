"""Independently recount saved predictions and replay future-window labels."""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import joblib
import pandas as pd

HOUR_NS = 3_600_000_000_000


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify(folder, verify_source=False):
    result = json.loads((folder / 'results.json').read_text())
    prep = json.loads((folder / 'preparation.json').read_text())
    if prep.get('source_kind') == 'public_influx_api':
        from .checkpoint import verify_preparation
        verify_preparation(folder)
    frozen = json.loads((folder / 'model_freeze.json').read_text())
    unlocked = json.loads((folder / 'test_unlock.json').read_text())
    assert pd.Timestamp(frozen['frozen_at_utc']) < pd.Timestamp(unlocked['unlocked_at_utc'])
    assert pd.Timestamp(unlocked['unlocked_at_utc']) < pd.Timestamp(result['completed_at_utc'])
    assert file_hash(folder / 'model_freeze.json') == unlocked['model_freeze_sha256']
    assert file_hash(folder / 'feature_schema.json') == frozen['feature_schema_sha256']
    for name, digest in json.loads((folder / 'artifact_manifest.json').read_text()).items():
        assert file_hash(folder / name) == digest, name
    for name, digest in frozen['model_hashes'].items():
        assert file_hash(folder / 'models' / name) == digest, name
    if verify_source:
        assert file_hash(Path(prep['source'])) == prep['source_sha256']
    potential = joblib.load(folder / 'cache/potential.joblib')
    counts = {kind: Counter() for kind in result['metrics']}
    positive = 0
    with (folder / 'test_predictions.csv').open(newline='') as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        anchor = pd.Timestamp(row['time'])
        assert pd.Timestamp('2026-07-01', tz='America/Los_Angeles') <= anchor
        assert anchor + pd.Timedelta(hours=24) < pd.Timestamp('2026-09-01', tz='America/Los_Angeles')
        current, trend = float(row['current_potential_kpa']), float(row['trend_6h_kpa_per_h'])
        assert current > -500
        assert int(row['history_hours_6h']) >= 4
        assert int(row['history_hours_24h']) >= 18
        expected_baseline = int(trend < 0 and current + 24 * trend <= -500)
        assert expected_baseline == int(row['baseline_prediction'])
        times, values = potential[row['site']]
        start, end = anchor.value, anchor.value + 24 * HOUR_NS
        left = bisect.bisect_right(times, start)
        right = bisect.bisect_right(times, end)
        occupied = set()
        previous = start
        maximum_gap = 0
        event = 0
        for index in range(left, right):
            timestamp = int(times[index])
            occupied.add((timestamp - start - 1) // HOUR_NS)
            maximum_gap = max(maximum_gap, timestamp - previous)
            previous = timestamp
            if values[index] <= -500:
                event = 1
        maximum_gap = max(maximum_gap, end - previous)
        assert len(occupied) >= 20 and maximum_gap <= 2 * HOUR_NS
        assert event == int(float(row['target']))
        positive += event
        predictions = {'drying_trend': expected_baseline, 'always_defer': 0,
                       'random_forest': int(row['rf_prediction']),
                       'logistic_regression': int(row['lr_prediction'])}
        assert predictions['random_forest'] == int(float(row['rf_score']) >= .70)
        assert predictions['logistic_regression'] == int(float(row['lr_score']) >= .70)
        for kind, prediction in predictions.items():
            key = ('tp' if prediction else 'fn') if event else ('fp' if prediction else 'tn')
            counts[kind][key] += 1
    assert len(rows) == result['test_examples']
    assert positive == result['positive_examples']
    for kind, counter in counts.items():
        metrics = result['metrics'][kind]
        for key in ('tp', 'fp', 'fn', 'tn'):
            assert counter[key] == metrics[key], (kind, key)
        denominator = 2 * counter['tp'] + counter['fp'] + counter['fn']
        expected_f1 = 2 * counter['tp'] / denominator if denominator else 0.
        assert abs(expected_f1 - metrics['f1']) < 1e-14
    coverage = pd.read_csv(folder / 'coverage.csv')
    for partition, frame in coverage.groupby('partition'):
        excluded = frame.current_or_history_missing_hours + frame.currently_dry_forecast_eligible_hours
        excluded += frame.primary_hours_missing_future_label + frame.evaluation_hours
        assert (excluded == frame.scheduled_nonpurged_hours).all(), partition
    receipt = {'verified_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
               'test_rows_replayed': len(rows), 'confusion_counts_and_f1_match': True,
               'baseline_rule_matches': True, 'future_labels_and_coverage_replayed': True,
               'freeze_order_and_hashes_match': True, 'coverage_exclusions_reconcile': True,
               'source_rehashed': verify_source}
    (folder / 'independent_verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--verify-source', action='store_true')
    args = parser.parse_args()
    verify(args.folder, args.verify_source)
