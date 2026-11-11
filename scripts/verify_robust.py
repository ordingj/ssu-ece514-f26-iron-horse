"""Independently replay the median/loss/window comparison from trusted artifacts."""
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


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def close(actual, expected):
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10, equal_nan=True)


def percentile90(values):
    ordered = sorted(abs(float(value)) for value in values)
    position = .9 * (len(ordered) - 1)
    left, right = int(np.floor(position)), int(np.ceil(position))
    return ordered[left] + (position - left) * (ordered[right] - ordered[left])


def scores(part):
    if not len(part):
        return dict(n=0, days=0, mae=np.nan, rmse=np.nan, bias=np.nan, persistence_mae=np.nan, mae_skill_vs_persistence=np.nan)
    errors = part.prediction.to_numpy() - part.actual.to_numpy()
    reference = np.abs(part.actual).mean();mae = np.abs(errors).mean()
    return {'n': len(part), 'days': part.day.nunique(), 'mae': mae, 'rmse': np.sqrt(np.square(errors).mean()),
            'bias': errors.mean(), 'persistence_mae': reference,
            'mae_skill_vs_persistence': 1 - mae / reference if reference else np.nan}


def verify(parent, audit):
    receipt_path = audit / 'independent_verification.json'
    if receipt_path.exists(): raise FileExistsError('Receipt already exists')
    summary = json.loads((audit / 'summary.json').read_text())
    for name, expected in summary['parent_input_hashes'].items(): assert digest(parent / name) == expected, name
    for name, expected in summary['artifact_hashes'].items(): assert digest(audit / name) == expected, name
    assert digest(ROOT / 'iron_horse/robust.py') == summary['analysis_code_sha256']
    assert digest(ROOT / 'docs/robust-forecast-plan.md') == summary['plan_sha256']
    previous = json.loads((parent / 'summary.json').read_text())
    examples = pd.read_parquet(parent / 'examples.parquet')
    prior_predictions = pd.read_parquet(parent / 'predictions.parquet')
    predictions = pd.read_parquet(audit / 'predictions.parquet')
    references = pd.read_csv(audit / 'training_references.csv')
    controls = {(fit['site'], fit['fold']): fit for fit in previous['fits'] if fit['outcome'] == 'water'
                and fit['policy'] == 'covered' and fit['method'] == 'forest_history'}
    fits = {(fit['window'], fit['site'], fit['fold']): fit for fit in summary['fits']}
    groups = {key: part for key, part in predictions.groupby(['window', 'site', 'fold'])}
    thresholds, models_checked = {}, 0
    assert len(references) == len(fits) == len(groups)
    # Expanding thresholds must be available before checking the rolling rows.
    for row in references.sort_values(['window', 'site', 'fold']).itertuples():
        key = (row.window, row.site, row.fold)
        panel = examples[(examples.outcome == 'water') & (examples.site == row.site)]
        start = pd.Timestamp(row.fold + '-01', tz=TZ).tz_convert('UTC')
        end = (pd.Timestamp(row.fold + '-01', tz=TZ) + pd.offsets.MonthBegin()).tz_convert('UTC')
        finish = panel.time + pd.Timedelta(hours=24)
        train_mask = (panel.time < start) & (finish < start) & panel.eligible_covered
        if row.window == 'rolling90': train_mask &= panel.time >= start - pd.Timedelta(hours=2160)
        train = panel[train_mask]
        test = panel[(panel.time >= start) & (finish < end) & panel.eligible_covered]
        assert row.train_rows == len(train) and row.eval_rows == len(test)
        assert row.first_training_issue == train.time.min().isoformat()
        assert row.last_training_outcome == (train.time.max() + pd.Timedelta(hours=24)).isoformat()
        assert pd.Timestamp(row.last_training_outcome) < start
        median = float(np.median(train.target_change));q90 = percentile90(train.target_change)
        close(row.median_change, median);close(row.window_training_q90, q90)
        if row.window == 'expanding': thresholds[(row.site, row.fold)] = q90
        cutoff = thresholds[(row.site, row.fold)];close(row.larger_cutoff, cutoff)
        part = groups[key]
        methods = {'persistence', 'median_change', 'forest_absolute'} | ({'forest_squared'} if row.window == 'expanding' else set())
        assert set(part.method) == methods
        for method in methods:
            subset = part[part.method == method].sort_values('time')
            assert list(subset.time) == list(test.time)
            assert list(subset.day) == list(test.time.dt.tz_convert(TZ).dt.strftime('%Y-%m-%d'))
            close(subset.actual, test.future - test.current);close(subset.larger_cutoff, cutoff)
            if method == 'persistence': close(subset.prediction, np.zeros(len(test)))
            if method == 'median_change': close(subset.prediction, np.full(len(test), median))
        fit = fits[key];control_fit = controls[(row.site, row.fold)]
        assert fit['train_rows'] == len(train) and fit['eval_rows'] == len(test)
        assert digest(audit / fit['path']) == fit['sha256']
        assert fit['control_path'] == control_fit['path']
        old = joblib.load(parent / control_fit['path']);artifact = joblib.load(audit / fit['path'])
        columns, model = artifact['columns'], artifact['model']
        assert columns == old['columns'] and all(c.startswith('history__') for c in columns)
        expected_params = old['model'].named_steps['regressor'].get_params() | {'criterion': 'absolute_error'}
        assert model.named_steps['regressor'].get_params() == expected_params == fit['parameters']
        a = train[columns].to_numpy();keep = [j for j in range(a.shape[1]) if np.isfinite(a[:, j]).any() and np.ptp(a[np.isfinite(a[:, j]), j]) > 0]
        pre = model.named_steps['preprocess'];np.testing.assert_array_equal(pre.keep_, keep)
        medians = np.array([np.median(a[np.isfinite(a[:, j]), j]) for j in keep]);close(pre.medians_, medians)
        filled = np.where(np.isfinite(a[:, keep]), a[:, keep], medians)
        close(pre.means_, filled.mean(axis=0));scale = filled.std(axis=0);scale[scale == 0] = 1;close(pre.scales_, scale)
        if row.window == 'expanding':
            old_pre = old['model'].named_steps['preprocess']
            for attribute in ['keep_', 'medians_', 'means_', 'scales_']: close(getattr(pre, attribute), getattr(old_pre, attribute))
            anchor = part[part.method == 'forest_squared'].sort_values('time')
            old_rows = prior_predictions[(prior_predictions.outcome == 'water') & (prior_predictions.policy == 'covered') &
                (prior_predictions.method == 'forest_history') & (prior_predictions.site == row.site) & (prior_predictions.fold == row.fold)].sort_values('time')
            assert list(anchor.time) == list(old_rows.time)
            close(anchor.prediction, old_rows.prediction);close(anchor.prediction, old['model'].predict(test[columns]))
        robust = part[part.method == 'forest_absolute'].sort_values('time')
        close(robust.prediction, model.predict(test[columns]));models_checked += 1
    first = pd.read_parquet(audit / 'expanding_predictions.parquet')
    pd.testing.assert_frame_equal(first.reset_index(drop=True), predictions[predictions.window == 'expanding'].reset_index(drop=True))
    metrics = pd.read_csv(audit / 'metrics.csv')
    per_method = {key: part for key, part in predictions.groupby(['window', 'site', 'fold', 'method'])}
    assert len(metrics) == 2 * len(per_method)
    for row in metrics.itertuples():
        part = per_method[(row.window, row.site, row.fold, row.method)]
        if row.stratum == 'larger': part = part[np.abs(part.actual) > part.larger_cutoff]
        for name, expected in scores(part).items(): close(getattr(row, name), expected)
    pooled = pd.read_csv(audit / 'pooled_metrics.csv')
    for row in pooled.itertuples():
        part = predictions[(predictions.window == row.window) & (predictions.method == row.method)]
        if row.stratum == 'larger': part = part[part.actual.abs() > part.larger_cutoff]
        for name, expected in scores(part).items(): close(getattr(row, name), expected)
        subset = metrics[(metrics.window == row.window) & (metrics.method == row.method) & (metrics.stratum == row.stratum)]
        close(row.nonempty_site_month_groups, (subset.n > 0).sum())
        close(row.equal_group_mae, subset.mae.mean())
    for row in pd.read_csv(audit / 'expanding_pooled.csv').itertuples():
        saved = pooled[(pooled.window == 'expanding') & (pooled.method == row.method) & (pooled.stratum == row.stratum)].iloc[0]
        for name in ['n', 'mae', 'rmse', 'bias', 'days']: close(getattr(row, name), saved[name])
    daily = pd.read_csv(audit / 'daily_errors.csv')
    daily_keys = ['window', 'site', 'fold', 'method', 'day']
    by_day = {key: part for key, part in predictions.groupby(daily_keys)}
    assert len(daily) == len(by_day)
    for row in daily.itertuples():
        part = by_day[tuple(getattr(row, name) for name in daily_keys)]
        assert row.n == len(part);close(row.mae, (part.prediction - part.actual).abs().mean())
    initial = pooled[(pooled.window == 'expanding') & (pooled.stratum == 'all')].set_index('method').mae
    trigger = not (initial['forest_absolute'] < initial['persistence'] and initial['forest_absolute'] < initial['median_change'])
    decision = json.loads((audit / 'decision.json').read_text())
    assert trigger == decision['rolling90_triggered'] == summary['rolling90_triggered']
    for name, value in initial.items(): close(decision['expanding_overall_mae'][name], value)
    assert models_checked == summary['models_fitted'] == (24 if trigger else 12)
    assert set(predictions.window) == ({'expanding', 'rolling90'} if trigger else {'expanding'})
    result = {'verified_at_utc': pd.Timestamp.now(tz='UTC').isoformat(), 'training_reference_rows_checked': len(references),
        'models_and_preprocessors_checked': models_checked, 'prediction_rows_replayed': len(predictions),
        'metric_rows_checked': len(metrics), 'pooled_rows_checked': len(pooled), 'daily_rows_checked': len(daily),
        'conditional_trigger_checked': True, 'verifier_sha256': digest(Path(__file__))}
    receipt_path.write_text(json.dumps(result, indent=2) + '\n');print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    verify(args.parent, args.audit)
