"""Independently recount the target grid from trusted decoded observations.

This checker uses rolling counts, raw dry-count prefixes, and the intervals
intersecting long observation gaps. It does not import the audit's kernels.
Run it in the pinned project environment. It writes only a new receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

H = 3_600_000_000_000
TZ = 'America/Los_Angeles'
BOUNDARIES = [pd.Timestamp(s, tz=TZ).value for s in
              ('2026-01-01', '2026-06-01', '2026-07-01', '2026-09-01')]
PERIODS = ('train', 'validation', 'test')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def observed_spells(site, times, values, threshold):
    """Find spell starts through gap segments and cumulative wet-reset markers."""
    raw = pd.DataFrame({'hour': pd.to_datetime(times, utc=True).ceil('h'),
                        'value': values, 'time': times,
                        'segment': np.r_[0, np.cumsum(np.diff(times) > 2 * H)]})
    hourly = raw.groupby('hour').agg(minimum=('value', 'min'), segment=('segment', 'first'))
    hourly = hourly.reindex(pd.date_range(hourly.index.min(), hourly.index.max(), freq='h'))
    recovered = (hourly.minimum > threshold).rolling(6).sum() == 6
    hourly['reset'] = (recovered & ~recovered.shift(1, fill_value=False)).cumsum()
    dry = raw[raw.value <= threshold].copy()
    dry['reset'] = dry.hour.map(hourly.reset)
    starts = dry.groupby(['segment', 'reset']).time.min()
    rows = []
    for onset in starts:
        hour = pd.Timestamp(onset, tz='UTC').ceil('h')
        prior = hour - pd.Timedelta(hours=1)
        confirmed = prior in recovered.index and bool(recovered.loc[prior])
        if confirmed:
            confirmed = hourly.loc[hour, 'segment'] == hourly.loc[prior, 'segment']
        period = next((name for left, right, name in zip(BOUNDARIES[:-1], BOUNDARIES[1:], PERIODS)
                       if left <= onset < right), 'outside')
        rows.append((site, int(onset), bool(confirmed), period))
    return rows


def verify(folder, audit_folder, receipt):
    """Check every aggregate class count and baseline metric in the fixed grid."""
    if receipt.exists():
        raise FileExistsError('Verification receipt exists. Choose a new --receipt path')
    summary = json.loads((audit_folder / 'summary.json').read_text())
    for name, expected in summary['provenance']['input_hashes'].items():
        if digest(folder / name) != expected:
            raise ValueError(f'Input hash mismatch: {name}')
    potential = joblib.load(folder / 'cache/potential.joblib')
    source = pd.read_parquet(folder / 'cache/hourly_inputs.parquet').sort_values(['site', 'time']).reset_index(drop=True)
    counts = pd.read_csv(audit_folder / 'coverage.csv')
    baselines = pd.read_csv(audit_folder / 'baselines.csv')
    inventory = pd.read_csv(audit_folder / 'threshold_spells.csv')
    assert summary['candidate_count'] == 60 and len(counts) == 180 and len(baselines) == 720
    expected_spells = []
    checked_counts = checked_metrics = 0
    for threshold in (-100., -200., -300., -400., -500.):
        spells = [row for site, pair in potential.items() for row in observed_spells(site, *pair, threshold)]
        expected_spells.extend((threshold, *row[:3]) for row in spells)
        confirmed = {site: {onset for s, onset, known, _ in spells if s == site and known} for site in potential}
        for horizon in (6, 12, 24, 48):
            parts = []
            for site, original in source.groupby('site', sort=True):
                frame = original.copy()
                times, values = potential[site]
                anchors = pd.DatetimeIndex(frame.time).as_unit('ns').asi8
                raw_hourly = pd.Series(values, index=pd.to_datetime(times, utc=True).ceil('h')).groupby(level=0).median()
                current = raw_hourly.reindex(pd.DatetimeIndex(frame.time))
                np.testing.assert_allclose(current, frame.current_potential_kpa, equal_nan=True)
                finite = current.notna()
                history = finite & (finite.rolling(6, min_periods=1).sum() >= 4) & (finite.rolling(24, min_periods=1).sum() >= 18)
                assert np.array_equal(history, frame.forecast_eligible)
                occupied = finite.rolling(horizon, min_periods=0).sum().shift(-horizon).fillna(0).to_numpy()
                dry_hours = (current <= threshold).rolling(horizon, min_periods=0).sum().shift(-horizon).fillna(0).to_numpy()
                left = np.searchsorted(times, anchors, side='right')
                right = np.searchsorted(times, anchors + horizon * H, side='right')
                has_future = right > left
                bad_gap = ~has_future
                positions = np.flatnonzero(has_future)
                bad_gap[positions] |= times[left[positions]] - anchors[positions] > 2 * H
                bad_gap[positions] |= anchors[positions] + horizon * H - times[right[positions] - 1] > 2 * H
                for index in np.flatnonzero(np.diff(times) > 2 * H):
                    # A window is invalid when its overlap with this raw gap exceeds two hours.
                    bad_gap |= (anchors > times[index] + 2 * H - horizon * H) & (anchors < times[index + 1] - 2 * H)
                covered = (occupied >= (5 * horizon + 5) // 6) & ~bad_gap
                prefix = np.r_[0, np.cumsum(values <= threshold)]
                occurrence = prefix[right] > prefix[left]
                dry_times = times[values <= threshold]
                next_index = np.searchsorted(dry_times, anchors, side='right')
                next_onset = np.full(len(anchors), -1, dtype=np.int64)
                available = next_index < len(dry_times)
                next_onset[available] = dry_times[next_index[available]]
                opportunity = np.isin(next_onset, list(confirmed[site])) & (next_onset > anchors) & (next_onset <= anchors + horizon * H)
                period = np.full(len(frame), 'purged', dtype=object)
                for a, b, name in zip(BOUNDARIES[:-1], BOUNDARIES[1:], PERIODS):
                    period[(anchors >= a) & (anchors + horizon * H < b)] = name
                frame['period'] = period
                frame['covered'] = covered
                frame['occurrence'] = occurrence
                frame['majority'] = np.where(dry_hours >= horizon / 2, 1.,
                                              np.where(dry_hours + horizon - occupied < horizon / 2, 0., np.nan))
                frame['current_dry'] = current.to_numpy() <= threshold
                frame['opportunity'] = opportunity
                frame['next_onset'] = next_onset
                parts.append(frame)
            data = pd.concat(parts, ignore_index=True)
            for family in ('new_dry_event', 'future_dry_occurrence', 'future_dry_majority'):
                name = f'{family}__kpa{abs(int(threshold))}__h{horizon}'
                label = data.majority if family == 'future_dry_majority' else data.occurrence.astype(float)
                input_ok = data.forecast_eligible & (~data.current_dry if family == 'new_dry_event' else True)
                scored = input_ok & data.covered & label.notna()
                for period in PERIODS:
                    schedule = data.period == period
                    mask = scored & schedule
                    positive = mask & (label == 1)
                    negative = mask & (label == 0)
                    def days(which):
                        rows = data[which].copy()
                        rows['day'] = pd.DatetimeIndex(rows.time).tz_convert(TZ).strftime('%Y-%m-%d')
                        return len(rows[['site', 'day']].drop_duplicates())
                    opportunities = data[positive & data.opportunity]
                    reference = {'scheduled_hours': int(schedule.sum()),
                                 'history_missing_hours': int((schedule & ~data.forecast_eligible).sum()),
                                 'currently_dry_history_hours': int((schedule & data.forecast_eligible & data.current_dry).sum()),
                                 'excluded_currently_dry_hours': int((schedule & data.forecast_eligible & ~input_ok).sum()),
                                 'input_eligible_hours': int((schedule & input_ok).sum()),
                                 'future_coverage_missing_hours': int((schedule & input_ok & ~data.covered).sum()),
                                 'definition_ambiguous_hours': int((schedule & input_ok & data.covered & label.isna()).sum()),
                                 'eligible_hours': int(mask.sum()), 'positive_hours': int(positive.sum()),
                                 'negative_hours': int(negative.sum()), 'positive_sensor_days': days(positive),
                                 'negative_sensor_days': days(negative),
                                 'positive_locations': data[positive].site.nunique(),
                                 'negative_locations': data[negative].site.nunique(),
                                 'confirmed_episodes': sum(known and p == period for _, _, known, p in spells),
                                 'uncertain_onsets': sum(not known and p == period for _, _, known, p in spells),
                                 'episodes_with_positive_pre_onset_opportunity': len(opportunities[['site', 'next_onset']].drop_duplicates()),
                                 'positive_pre_onset_hours': len(opportunities)}
                    saved = counts[(counts.candidate == name) & (counts.partition == period)].iloc[0]
                    for key, expected in reference.items():
                        assert saved[key] == expected, (name, period, key, saved[key], expected)
                    checked_counts += 1
                    y = label[mask].to_numpy(int)
                    current = data.loc[mask, 'current_potential_kpa'].to_numpy()
                    trend = data.loc[mask, 'trend_6h_kpa_per_h'].to_numpy()
                    projected = ((trend < 0) & (current + horizon * trend <= threshold))
                    if family == 'future_dry_occurrence': projected |= current <= threshold
                    if family == 'future_dry_majority': projected = current + horizon / 2 * trend <= threshold
                    for method, prediction in (('always_defer', np.zeros(len(y))), ('always_positive', np.ones(len(y))),
                                               ('persistence', current <= threshold), ('trend_reference', projected)):
                        saved = baselines[(baselines.candidate == name) & (baselines.partition == period) & (baselines.method == method)].iloc[0]
                        tp, fp = int(((y == 1) & (prediction == 1)).sum()), int(((y == 0) & (prediction == 1)).sum())
                        fn, tn = int(((y == 1) & (prediction == 0)).sum()), int(((y == 0) & (prediction == 0)).sum())
                        for key, expected in {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.,
                            'precision': tp / (tp + fp) if tp + fp else 0.,
                            'recall': tp / (tp + fn) if tp + fn else 0.}.items():
                            assert abs(saved[key] - expected) < 1e-12, (name, period, method, key)
                        checked_metrics += 1
    actual_spells = [(r.threshold_kpa, r.site, int(r.onset_ns), bool(r.confirmed)) for r in inventory.itertuples()]
    assert sorted(expected_spells) == sorted(actual_spells)
    value = {'verified_at_utc': pd.Timestamp.now(tz='UTC').isoformat(), 'candidate_count': 60,
             'partition_count_rows_checked': checked_counts, 'baseline_metric_rows_checked': checked_metrics,
             'all_threshold_spell_identities_match': True, 'models_fitted': 0,
             'verifier_sha256': digest(Path(__file__))}
    receipt.write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    verify(args.run, args.audit, args.receipt or args.audit / 'independent_verification.json')
