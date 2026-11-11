"""Independently replay continuous forecast timing, predictions, and metrics.

Use trusted local run artifacts. This verifier does not import the experiment's
example builder, split masks, or score functions, and does not refit a model.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TZ = 'America/Los_Angeles'
WATER = dict(zip([f'SDI-12-LS-US915-{i}' for i in (1, 2, 4, 5)], [2, 1, 3, 4]))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def close(a, b):
    np.testing.assert_allclose(a, b, rtol=1e-10, atol=1e-10, equal_nan=True)


def max_gap(values):
    text = ''.join('1' if v else '0' for v in values)
    return max(map(len, text.split('1')))


def scores(part):
    error = part.prediction.to_numpy() - part.actual.to_numpy()
    reference = np.abs(part.actual).mean()
    mae = np.abs(error).mean()
    return {'n': len(part), 'mae': mae, 'rmse': np.sqrt(np.square(error).mean()),
            'bias': error.mean(), 'persistence_mae': reference,
            'mae_skill_vs_persistence': 1 - mae / reference if reference else np.nan,
            'days': part.day.nunique()}


def verify(source, audit):
    receipt = audit / 'independent_verification.json'
    if receipt.exists(): raise FileExistsError('Verification receipt already exists')
    summary = json.loads((audit / 'summary.json').read_text())
    for name, expected in summary['input_hashes'].items(): assert digest(source / name) == expected, name
    for name, expected in summary['artifact_hashes'].items(): assert digest(audit / name) == expected, name
    assert digest(ROOT / 'iron_horse/continuous.py') == summary['analysis_code_sha256']
    assert digest(ROOT / 'iron_horse/sensor_compare.py') == summary['aggregation_code_sha256']
    assert digest(ROOT / 'docs/continuous-forecast-plan.md') == summary['plan_sha256']
    hourly = pd.read_parquet(audit / 'hourly.parquet')
    examples = pd.read_parquet(audit / 'examples.parquet')
    predictions = pd.read_parquet(audit / 'predictions.parquet')
    info = json.loads((audit / 'channel_metadata.json').read_text())
    checks = feature_checks = 0
    for (outcome, site), part in examples.groupby(['outcome', 'site']):
        part = part.sort_values('time')
        assert pd.DatetimeIndex(part.time).equals(hourly.index)
        target_key = site + ':potential' if outcome == 'potential' else f'SE01-LS-{WATER[site]}:device_frmpayload_data_water_SOIL'
        values = hourly[target_key].to_numpy()
        endpoint = np.r_[values[24:], np.full(24, np.nan)]
        close(part.current, values);close(part.future, endpoint);close(part.target_change, endpoint - values)
        close(part.trend_change, 4 * (values - np.r_[np.full(6, np.nan), values[:-6]]))
        present = np.isfinite(values)
        for i, row in enumerate(part.itertuples()):
            past, future = present[max(0, i - 24):i + 1], present[i + 1:i + 25]
            covered = i >= 24 and present[i] and present[i - 6] and present[i - 24] and present[i - 5:i + 1].sum() >= 4 and present[i - 23:i + 1].sum() >= 18 and max_gap(past) <= 2
            complete = len(past) == 25 and past.all()
            label = len(future) == 24 and future[-1] and future.sum() >= 20 and max_gap(future) <= 2
            assert row.past_covered == covered and row.past_complete == complete
            assert row.eligible_covered == (covered and label)
            assert row.eligible_complete == (complete and len(future) == 24 and future.all())
            near = outcome == 'potential' and np.isfinite(values[i]) and abs(values[i]) <= 1
            recent = outcome == 'potential' and any(
                np.isfinite(values[j - 1:j + 1]).all() and abs(values[j] - values[j - 1]) >= 100
                for j in range(max(1, i - 23), i + 1))
            assert row.near_zero == near and row.recent_jump == recent
            checks += 1
        # Independently sample all predictor columns at three eligible times.
        eligible = part[part.eligible_covered]
        for position in sorted({0, len(eligible) // 2, len(eligible) - 1}):
            row = eligible.iloc[position];i = hourly.index.get_loc(row.time)
            local = row.time.tz_convert(TZ)
            for key in [c for c in part if c.startswith(('history__', 'extra__'))]:
                if key.startswith('history__'):
                    stat = key[len('history__'):]
                    if stat.startswith(('hour_', 'day_')):
                        angle = 2 * np.pi * (local.hour / 24 if stat.startswith('hour') else local.dayofyear / 365)
                        expected = np.sin(angle) if stat.endswith('sin') else np.cos(angle)
                    elif stat == 'current': expected = values[i]
                    elif stat.startswith('lag'): expected = values[i - int(stat[3:])]
                    else:
                        width = 6 if stat.endswith('6') else 24
                        window = values[i + 1 - width:i + 1]
                        finite = np.isfinite(window)
                        if stat.startswith('slope'):
                            expected = np.polyfit(np.arange(width)[finite], window[finite], 1)[0] if finite.sum() >= (4 if width == 6 else 18) else np.nan
                        elif stat.startswith('std'): expected = np.std(window[finite], ddof=1) if finite.sum() >= 2 else np.nan
                        else: expected = np.mean(window[finite]) if finite.any() else np.nan
                else:
                    channel, stat = key[len('extra__'):].rsplit('__', 1)
                    meta = info[channel]
                    relevant = channel != target_key and (meta['block'] == info[target_key]['block'] or
                                meta['device'] == 'SDI-12-LS-US915-3' or meta['kind'] == 'air_temperature_c')
                    a = hourly[channel].to_numpy()
                    if not relevant: expected = np.nan
                    elif stat == 'current': expected = a[i]
                    elif stat.startswith('change'): expected = a[i] - a[i - int(stat[6:])]
                    else:
                        width = 6 if stat.endswith('6') else 24
                        window = a[i + 1 - width:i + 1];good = window[np.isfinite(window)]
                        if stat.startswith('count'): expected = len(good)
                        elif not len(good): expected = np.nan
                        elif stat.startswith('sum'): expected = good.sum()
                        else: expected = good.mean()
                close(row[key], expected);feature_checks += 1
    # Every saved fitted preprocessor must match only the permitted training rows.
    model_checks = 0
    for fit in summary['fits']:
        panel = examples[(examples.outcome == fit['outcome']) & (examples.site == fit['site'])]
        start, end = pd.Timestamp(fit['evaluation_start']), pd.Timestamp(fit['evaluation_end'])
        eligible = panel['eligible_' + fit['policy']]
        finish = panel.time + pd.Timedelta(hours=24)
        train = panel[(panel.time < start) & (finish < start) & eligible]
        test = panel[(panel.time >= start) & (finish < end) & eligible]
        assert len(train) == fit['train_rows'] and len(test) == fit['eval_rows']
        assert (train.time.max() + pd.Timedelta(hours=24)).isoformat() == fit['latest_training_outcome']
        assert pd.Timestamp(fit['latest_training_outcome']) < start
        artifact = joblib.load(audit / fit['path']);model, columns = artifact['model'], artifact['columns']
        assert all(c.startswith(('history__', 'extra__')) for c in columns)
        if fit['method'].endswith('_history'): assert all(c.startswith('history__') for c in columns)
        a = train[columns].to_numpy();keep = [j for j in range(a.shape[1]) if np.isfinite(a[:, j]).any() and np.ptp(a[np.isfinite(a[:, j]), j]) > 0]
        pre = model.named_steps['preprocess'];np.testing.assert_array_equal(pre.keep_, keep)
        medians = np.array([np.median(a[np.isfinite(a[:, j]), j]) for j in keep]);close(pre.medians_, medians)
        fitted = np.where(np.isfinite(a[:, keep]), a[:, keep], medians)
        close(pre.means_, fitted.mean(axis=0));std = fitted.std(axis=0);std[std == 0] = 1;close(pre.scales_, std)
        scored = predictions[(predictions.outcome == fit['outcome']) & (predictions.site == fit['site']) &
            (predictions.fold == fit['fold']) & (predictions.policy == fit['policy']) & (predictions.method == fit['method'])].sort_values('time')
        assert list(scored.time) == list(test.time)
        close(scored.actual, test.target_change);close(scored.prediction, model.predict(test[columns]));model_checks += 1
    for method in ['persistence', 'trend6']:
        for (outcome, site, fold, policy), part in predictions[predictions.method == method].groupby(['outcome', 'site', 'fold', 'policy']):
            frame = examples[(examples.outcome == outcome) & (examples.site == site)].set_index('time').loc[part.time]
            close(part.actual, frame.target_change)
            close(part.prediction, np.zeros(len(part)) if method == 'persistence' else frame.trend_change)
    metrics = pd.read_csv(audit / 'metrics.csv')
    for row in metrics.itertuples():
        part = predictions[(predictions.outcome == row.outcome) & (predictions.site == row.site) &
            (predictions.fold == row.fold) & (predictions.policy == row.policy) & (predictions.method == row.method)]
        if row.stratum != 'all': part = part[part[row.stratum]]
        for key, expected in scores(part).items(): close(getattr(row, key), expected)
    pooled = pd.read_csv(audit / 'pooled_metrics.csv')
    for row in pooled.itertuples():
        part = predictions[(predictions.outcome == row.outcome) & (predictions.policy == row.policy) & (predictions.method == row.method)]
        for key, expected in scores(part).items(): close(getattr(row, key), expected)
        groups = metrics[(metrics.outcome == row.outcome) & (metrics.policy == row.policy) & (metrics.method == row.method) & (metrics.stratum == 'all')]
        assert row.site_month_groups == len(groups);close(row.equal_group_mae, groups.mae.mean())
    coverage = pd.read_csv(audit / 'coverage.csv')
    for row in coverage.itertuples():
        panel = examples[(examples.outcome == row.outcome) & (examples.site == row.site)]
        start = pd.Timestamp(row.fold + '-01', tz=TZ).tz_convert('UTC')
        end = (pd.Timestamp(row.fold + '-01', tz=TZ) + pd.offsets.MonthBegin()).tz_convert('UTC')
        finish = panel.time + pd.Timedelta(hours=24)
        train_mask, eval_mask = (panel.time < start) & (finish < start), (panel.time >= start) & (finish < end)
        train, test = panel[train_mask & panel['eligible_' + row.policy]], panel[eval_mask & panel['eligible_' + row.policy]]
        assert row.training_rows == len(train) and row.scored_rows == len(test)
        assert row.scheduled_eval_rows == eval_mask.sum()
        assert row.past_eligible_rows == (eval_mask & panel['past_' + row.policy]).sum()
        assert row.training_days == train.time.dt.tz_convert(TZ).dt.date.nunique()
        assert row.scored_days == test.time.dt.tz_convert(TZ).dt.date.nunique()
    daily = pd.read_csv(audit / 'daily_errors.csv')
    daily_keys = ['outcome', 'policy', 'fold', 'site', 'method', 'day']
    groups = {key: part for key, part in predictions.groupby(daily_keys)}
    assert len(groups) == len(daily)
    for row in daily.itertuples():
        part = groups[tuple(getattr(row, key) for key in daily_keys)]
        assert row.n == len(part);close(row.mae, (part.prediction - part.actual).abs().mean())
    common = pd.read_csv(audit / 'common_policy_comparison.csv')
    groups = {key: part for key, part in predictions.groupby(['outcome', 'fold', 'site', 'method'])}
    assert len(common) == len(groups)
    for row in common.itertuples():
        part = groups[(row.outcome, row.fold, row.site, row.method)]
        a = part[part.policy == 'covered'].set_index('time')
        b = part[part.policy == 'complete'].set_index('time')
        times = a.index.intersection(b.index)
        assert row.n_common == len(times);close(a.loc[times].actual, b.loc[times].actual)
        close(row.covered_fit_mae, (a.loc[times].prediction - a.loc[times].actual).abs().mean())
        close(row.complete_fit_mae, (b.loc[times].prediction - b.loc[times].actual).abs().mean())
    result = {'verified_at_utc': pd.Timestamp.now(tz='UTC').isoformat(), 'example_rows_checked': checks,
              'sampled_predictor_values_checked': feature_checks, 'models_and_training_preprocessors_checked': model_checks,
              'prediction_rows_replayed': len(predictions), 'metric_rows_checked': len(metrics),
              'pooled_metric_rows_checked': len(pooled), 'coverage_rows_checked': len(coverage),
              'daily_error_rows_checked': len(daily), 'common_policy_rows_checked': len(common),
              'verifier_sha256': digest(Path(__file__))}
    receipt.write_text(json.dumps(result, indent=2) + '\n');print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    verify(args.run, args.audit)
