"""Independently replay pooled block-transfer splits, models, and score scopes."""
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
SITES = [f'SDI-12-LS-US915-{i}' for i in (1, 2, 4, 5)]
FOLDS = ['2026-06', '2026-07', '2026-08']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def close(a, b):
    np.testing.assert_allclose(a, b, rtol=1e-10, atol=1e-10, equal_nan=True)


def scores(part):
    errors = part.prediction.to_numpy() - part.actual.to_numpy()
    reference = np.abs(part.actual).mean();mae = np.abs(errors).mean()
    return {'n': len(part), 'days': part.day.nunique(), 'mae': mae, 'rmse': np.sqrt(np.square(errors).mean()),
            'bias': errors.mean(), 'persistence_mae': reference,
            'mae_skill_vs_persistence': 1 - mae / reference if reference else np.nan}


def verify(parent, audit):
    receipt = audit / 'independent_verification.json'
    if receipt.exists(): raise FileExistsError('Receipt already exists')
    summary = json.loads((audit / 'summary.json').read_text())
    for name, expected in summary['parent_input_hashes'].items(): assert digest(parent / name) == expected, name
    for name, expected in summary['artifact_hashes'].items(): assert digest(audit / name) == expected, name
    assert digest(ROOT / 'iron_horse/transfer.py') == summary['analysis_code_sha256']
    assert digest(ROOT / 'docs/block-transfer-plan.md') == summary['plan_sha256']
    all_examples = pd.read_parquet(parent / 'examples.parquet')
    data = all_examples[all_examples.outcome == 'water']
    predictions = pd.read_parquet(audit / 'predictions.parquet')
    counts = pd.read_csv(audit / 'split_counts.csv').set_index('fit_id')
    template = joblib.load(parent / summary['template_path'])
    expected_parameters = template['model'].named_steps['regressor'].get_params() | {'criterion': 'absolute_error'}
    start_season = pd.Timestamp('2026-01-01', tz=TZ).tz_convert('UTC')
    end_season = pd.Timestamp('2026-09-01', tz=TZ).tz_convert('UTC')
    finish = data.time + pd.Timedelta(hours=24)
    eligible = data.eligible_covered & (data.time >= start_season) & (finish < end_season)
    expected_specifications = {('block_only', site, None) for site in SITES}
    expected_specifications |= {('block_time', site, fold) for site in SITES for fold in FOLDS}
    expected_specifications |= {('pooled_time', None, fold) for fold in FOLDS}
    assert {(fit['design'], fit['held_site'], fit['fold']) for fit in summary['fits']} == expected_specifications
    assert len(counts) == len(summary['fits']) == summary['models_fitted'] == 19
    model_checks = 0
    for fit in summary['fits']:
        design, held, fold = fit['design'], fit['held_site'], fit['fold']
        if design == 'block_only':
            train_mask, test_mask = eligible & (data.site != held), eligible & (data.site == held)
        else:
            start = pd.Timestamp(fold + '-01', tz=TZ).tz_convert('UTC')
            end = (pd.Timestamp(fold + '-01', tz=TZ) + pd.offsets.MonthBegin()).tz_convert('UTC')
            train_mask = eligible & (data.time < start) & (finish < start)
            test_mask = eligible & (data.time >= start) & (finish < end)
            if design == 'block_time':
                train_mask &= data.site != held
                test_mask &= data.site == held
        train, test = data[train_mask], data[test_mask].sort_values(['site', 'time'])
        if design != 'pooled_time': assert held not in set(train.site) and set(test.site) == {held}
        else: assert set(train.site) == set(test.site) == set(SITES)
        if design != 'block_only': assert (train.time + pd.Timedelta(hours=24) < start).all()
        assert len(train) == fit['train_rows'] and len(test) == fit['eval_rows']
        median = float(np.median(train.target_change));close(fit['median_change'], median)
        for key, value in {'first_train_issue': train.time.min().isoformat(),
            'last_train_outcome': (train.time.max() + pd.Timedelta(hours=24)).isoformat(),
            'first_eval_issue': test.time.min().isoformat(),
            'last_eval_outcome': (test.time.max() + pd.Timedelta(hours=24)).isoformat(),
            'train_sites': ','.join(sorted(train.site.unique())), 'eval_sites': ','.join(sorted(test.site.unique()))}.items():
            assert fit[key] == value and counts.loc[fit['fit_id'], key] == value
        close(counts.loc[fit['fit_id'], 'median_change'], median)
        assert counts.loc[fit['fit_id'], 'train_rows'] == len(train) and counts.loc[fit['fit_id'], 'eval_rows'] == len(test)
        part = predictions[predictions.fit_id == fit['fit_id']]
        assert set(part.method) == {'persistence', 'median_change', 'forest_absolute'}
        common = np.zeros(len(test), dtype=bool)
        for month in FOLDS:
            a = pd.Timestamp(month + '-01', tz=TZ).tz_convert('UTC')
            b = (pd.Timestamp(month + '-01', tz=TZ) + pd.offsets.MonthBegin()).tz_convert('UTC')
            common |= ((test.time >= a) & (test.time + pd.Timedelta(hours=24) < b)).to_numpy()
        for method in ['persistence', 'median_change', 'forest_absolute']:
            rows = part[part.method == method].sort_values(['site', 'time'])
            assert len(rows) == len(test) and set(rows.design) == {design}
            assert list(zip(rows.site, rows.time)) == list(zip(test.site, test.time))
            assert list(rows.day) == list(test.time.dt.tz_convert(TZ).dt.strftime('%Y-%m-%d'))
            assert list(rows.fold) == list(test.time.dt.tz_convert(TZ).dt.strftime('%Y-%m'))
            close(rows.actual, test.future - test.current)
            np.testing.assert_array_equal(rows.common_eval, common)
            if method == 'persistence':close(rows.prediction, np.zeros(len(test)))
            if method == 'median_change':close(rows.prediction, np.full(len(test), median))
        artifact = joblib.load(audit / fit['path']);model, columns = artifact['model'], artifact['columns']
        assert digest(audit / fit['path']) == fit['sha256']
        assert columns == template['columns'] and all(key.startswith('history__') for key in columns)
        assert model.named_steps['regressor'].get_params() == expected_parameters == fit['parameters']
        a = train[columns].to_numpy();keep = [j for j in range(a.shape[1]) if np.isfinite(a[:, j]).any() and np.ptp(a[np.isfinite(a[:, j]), j]) > 0]
        pre = model.named_steps['preprocess'];np.testing.assert_array_equal(pre.keep_, keep)
        medians = np.array([np.median(a[np.isfinite(a[:, j]), j]) for j in keep]);close(pre.medians_, medians)
        filled = np.where(np.isfinite(a[:, keep]), a[:, keep], medians)
        close(pre.means_, filled.mean(axis=0));std = filled.std(axis=0);std[std == 0] = 1;close(pre.scales_, std)
        forest_rows = part[part.method == 'forest_absolute'].sort_values(['site', 'time'])
        close(forest_rows.prediction, model.predict(test[columns]));model_checks += 1
    assert len(predictions) == 3 * sum(fit['eval_rows'] for fit in summary['fits'])
    # The three designs must share both identities and actual outcomes in summer.
    anchor = None
    for design in ['block_only', 'block_time', 'pooled_time']:
        part = predictions[(predictions.design == design) & predictions.common_eval & (predictions.method == 'persistence')]
        frame = part.sort_values(['site', 'time'])[['site', 'time', 'actual']].reset_index(drop=True)
        if anchor is None: anchor = frame
        else: pd.testing.assert_frame_equal(anchor, frame)
    scoped = pd.concat([predictions[predictions.design == 'block_only'].assign(scope='full_season'),
                        predictions[predictions.common_eval].assign(scope='common_summer')], ignore_index=True)
    metrics = pd.read_csv(audit / 'metrics.csv')
    keys = ['scope', 'design', 'site', 'fold', 'method']
    groups = {key: part for key, part in scoped.groupby(keys)}
    assert len(metrics) == len(groups)
    for row in metrics.itertuples():
        part = groups[tuple(getattr(row, key) for key in keys)]
        for name, value in scores(part).items():close(getattr(row, name), value)
    pooled = pd.read_csv(audit / 'pooled_metrics.csv')
    for row in pooled.itertuples():
        part = scoped[(scoped.scope == row.scope) & (scoped.design == row.design) & (scoped.method == row.method)]
        for name, value in scores(part).items():close(getattr(row, name), value)
        subset = metrics[(metrics.scope == row.scope) & (metrics.design == row.design) & (metrics.method == row.method)]
        assert row.site_month_groups == len(subset);close(row.equal_group_mae, subset.mae.mean())
    daily = pd.read_csv(audit / 'daily_errors.csv')
    by_day = {key: part for key, part in scoped.groupby(keys + ['day'])}
    assert len(daily) == len(by_day)
    for row in daily.itertuples():
        part = by_day[tuple(getattr(row, key) for key in keys + ['day'])]
        assert row.n == len(part);close(row.mae, (part.prediction - part.actual).abs().mean())
    result = {'verified_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
        'models_splits_and_preprocessors_checked': model_checks, 'prediction_rows_replayed': len(predictions),
        'metric_rows_checked': len(metrics), 'pooled_rows_checked': len(pooled), 'daily_rows_checked': len(daily),
        'common_evaluation_rows_per_method_per_design': len(anchor), 'verifier_sha256': digest(Path(__file__))}
    receipt.write_text(json.dumps(result, indent=2) + '\n');print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    verify(args.parent, args.audit)
