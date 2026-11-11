"""Independently replay alternative-model splits, fits, and unchanged controls."""
import argparse
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import QuantileRegressor
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_transfer import digest, close, scores

TZ = 'America/Los_Angeles'
METHODS = {'median_regression', 'hist_boosting'}


def verify(parent, transfer, audit):
    receipt = audit / 'independent_verification.json'
    if receipt.exists(): raise FileExistsError('Receipt already exists')
    summary = json.loads((audit / 'summary.json').read_text())
    for name, expected in summary['continuous_input_hashes'].items(): assert digest(parent / name) == expected, name
    for name, expected in summary['transfer_input_hashes'].items(): assert digest(transfer / name) == expected, name
    for name, expected in summary['artifact_hashes'].items(): assert digest(audit / name) == expected, name
    assert digest(ROOT / 'iron_horse/alternatives.py') == summary['analysis_code_sha256']
    assert digest(ROOT / 'docs/alternative-models-plan.md') == summary['plan_sha256']
    old_summary = json.loads((transfer / 'summary.json').read_text())
    specifications = {fit['fit_id']: fit for fit in old_summary['fits']}
    assert len(specifications) == 19
    old = pd.read_parquet(transfer / 'predictions.parquet')
    predictions = pd.read_parquet(audit / 'predictions.parquet')
    old_methods = {'persistence', 'median_change', 'forest_absolute'}
    reused = predictions[predictions.method.isin(old_methods)].reset_index(drop=True)
    pd.testing.assert_frame_equal(reused, old.reset_index(drop=True))
    examples = pd.read_parquet(parent / 'examples.parquet')
    data = examples[examples.outcome == 'water']
    start_season = pd.Timestamp('2026-01-01', tz=TZ).tz_convert('UTC')
    end_season = pd.Timestamp('2026-09-01', tz=TZ).tz_convert('UTC')
    finish = data.time + pd.Timedelta(hours=24)
    eligible = data.eligible_covered & (data.time >= start_season) & (finish < end_season)
    assert len(summary['fits']) == summary['models_fitted'] == 38
    assert {(fit['fit_id'], fit['method']) for fit in summary['fits']} == {(key, method) for key in specifications for method in METHODS}
    model_checks = objective_checks = 0
    for fit in summary['fits']:
        spec = specifications[fit['fit_id']]
        design, held, fold = spec['design'], spec['held_site'], spec['fold']
        if design == 'block_only':
            train_mask, test_mask = eligible & (data.site != held), eligible & (data.site == held)
        else:
            start = pd.Timestamp(fold + '-01', tz=TZ).tz_convert('UTC')
            end = (pd.Timestamp(fold + '-01', tz=TZ) + pd.offsets.MonthBegin()).tz_convert('UTC')
            train_mask = eligible & (data.time < start) & (finish < start)
            test_mask = eligible & (data.time >= start) & (finish < end)
            if design == 'block_time': train_mask &= data.site != held;test_mask &= data.site == held
        train, test = data[train_mask], data[test_mask].sort_values(['site', 'time'])
        if design != 'pooled_time': assert held not in set(train.site)
        if design != 'block_only': assert (train.time + pd.Timedelta(hours=24) < start).all()
        assert fit['design'] == design and fit['held_site'] == held and fit['fold'] == fold
        assert fit['train_rows'] == len(train) == spec['train_rows']
        assert fit['eval_rows'] == len(test) == spec['eval_rows']
        assert fit['parent_forest_path'] == spec['path']
        rows = predictions[(predictions.fit_id == fit['fit_id']) & (predictions.method == fit['method'])].sort_values(['site', 'time'])
        assert len(rows) == len(test)
        assert list(zip(rows.site, rows.time)) == list(zip(test.site, test.time))
        close(rows.actual, test.future - test.current)
        anchor = old[(old.fit_id == fit['fit_id']) & (old.method == 'persistence')].sort_values(['site', 'time'])
        pd.testing.assert_frame_equal(rows.drop(columns=['method', 'prediction']).reset_index(drop=True),
                                      anchor.drop(columns=['method', 'prediction']).reset_index(drop=True))
        artifact = joblib.load(audit / fit['path']);model, columns = artifact['model'], artifact['columns']
        forest = joblib.load(transfer / spec['path'])
        assert digest(audit / fit['path']) == fit['sha256']
        assert columns == forest['columns'] and all(name.startswith('history__') for name in columns)
        a = train[columns].to_numpy();keep = [j for j in range(a.shape[1]) if np.isfinite(a[:, j]).any() and np.ptp(a[np.isfinite(a[:, j]), j]) > 0]
        pre = model.named_steps['preprocess'];np.testing.assert_array_equal(pre.keep_, keep)
        medians = np.array([np.median(a[np.isfinite(a[:, j]), j]) for j in keep]);close(pre.medians_, medians)
        filled = np.where(np.isfinite(a[:, keep]), a[:, keep], medians)
        close(pre.means_, filled.mean(axis=0));std = filled.std(axis=0);std[std == 0] = 1;close(pre.scales_, std)
        original_pre = forest['model'].named_steps['preprocess']
        for name in ['keep_', 'medians_', 'means_', 'scales_']:close(getattr(pre, name), getattr(original_pre, name))
        estimator = model.named_steps['regressor']
        assert estimator.get_params(deep=False) == fit['parameters']
        if fit['method'] == 'median_regression':
            expected = QuantileRegressor(quantile=.5, alpha=.001, fit_intercept=True, solver='highs')
            assert isinstance(estimator, QuantileRegressor)
            assert estimator.get_params() == expected.get_params()
            assert fit['nonzero_coefficients'] == (np.abs(estimator.coef_) > 1e-8).sum()
        else:
            expected = HistGradientBoostingRegressor(loss='absolute_error', learning_rate=.05, max_iter=100,
                max_depth=3, max_leaf_nodes=7, min_samples_leaf=24, l2_regularization=1.,
                early_stopping=False, random_state=514)
            assert isinstance(estimator, HistGradientBoostingRegressor)
            assert estimator.get_params() == expected.get_params()
            assert estimator.n_iter_ == 100 and not estimator.do_early_stopping_
        assert fit['n_iter'] == estimator.n_iter_
        with threadpool_limits(limits=2):
            close(rows.prediction, model.predict(test[columns]))
            if fit['method'] == 'median_regression':
                residual = np.abs(model.predict(train[columns]) - train.target_change).mean()
                objective = .5 * residual + .001 * np.abs(estimator.coef_).sum()
                constant_objective = .5 * np.abs(train.target_change - np.median(train.target_change)).mean()
                assert objective <= constant_objective + 1e-7
                objective_checks += 1
        model_checks += 1
    assert len(predictions) == len(old) + 2 * sum(spec['eval_rows'] for spec in specifications.values())
    for design in ['block_only', 'block_time', 'pooled_time']:
        common = predictions[(predictions.design == design) & predictions.common_eval]
        anchor = None
        for _, part in common.groupby('method'):
            frame = part.sort_values(['site', 'time'])[['site', 'time', 'actual']].reset_index(drop=True)
            if anchor is None:anchor = frame
            else:pd.testing.assert_frame_equal(anchor, frame)
        assert len(anchor) == 6883
    scoped = pd.concat([predictions[predictions.design == 'block_only'].assign(scope='full_season'),
                        predictions[predictions.common_eval].assign(scope='common_summer')], ignore_index=True)
    metrics = pd.read_csv(audit / 'metrics.csv')
    keys = ['scope', 'design', 'site', 'fold', 'method']
    groups = {key: part for key, part in scoped.groupby(keys)}
    assert len(metrics) == len(groups)
    for row in metrics.itertuples():
        part = groups[tuple(getattr(row, key) for key in keys)]
        for name, expected in scores(part).items():close(getattr(row, name), expected)
    pooled = pd.read_csv(audit / 'pooled_metrics.csv')
    for row in pooled.itertuples():
        part = scoped[(scoped.scope == row.scope) & (scoped.design == row.design) & (scoped.method == row.method)]
        for name, expected in scores(part).items():close(getattr(row, name), expected)
        subset = metrics[(metrics.scope == row.scope) & (metrics.design == row.design) & (metrics.method == row.method)]
        assert row.site_month_groups == len(subset);close(row.equal_group_mae, subset.mae.mean())
    daily = pd.read_csv(audit / 'daily_errors.csv')
    day_groups = {key: part for key, part in scoped.groupby(keys + ['day'])}
    assert len(daily) == len(day_groups)
    for row in daily.itertuples():
        part = day_groups[tuple(getattr(row, name) for name in keys + ['day'])]
        assert row.n == len(part);close(row.mae, (part.prediction - part.actual).abs().mean())
    result = {'verified_at_utc': pd.Timestamp.now(tz='UTC').isoformat(), 'models_splits_and_preprocessors_checked': model_checks,
        'median_training_objectives_checked': objective_checks, 'unchanged_control_prediction_rows': len(old),
        'prediction_rows_replayed': len(predictions), 'metric_rows_checked': len(metrics),
        'pooled_rows_checked': len(pooled), 'daily_rows_checked': len(daily),
        'verifier_sha256': digest(Path(__file__)), 'shared_verifier_sha256': digest(ROOT / 'scripts/verify_transfer.py')}
    receipt.write_text(json.dumps(result, indent=2) + '\n');print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--transfer', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    verify(args.parent, args.transfer, args.audit)
