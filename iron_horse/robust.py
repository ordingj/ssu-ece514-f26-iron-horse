"""Controlled soil-water comparison of training medians, forest loss, and windows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone

from .core import ROOT, TZ, now, save_json, sha256
from .continuous import FOLDS, WATER_DEVICES, fold_masks, regression_scores


def split_panel(panel, start, end, window_days=None):
    """Reuse covered rows and strict purges, with an optional elapsed-day limit."""
    train_mask, test_mask = fold_masks(panel.time, start, end)
    if window_days is not None:
        train_mask &= panel.time >= start - pd.Timedelta(days=window_days)
    return panel[train_mask & panel.eligible_covered], panel[test_mask & panel.eligible_covered]


def training_references(values):
    """Return the signed median and linear 90th percentile of absolute changes."""
    values = np.asarray(values, dtype=float)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError('Training changes must be nonempty and finite')
    return {'median_change': float(np.median(values)),
            'larger_cutoff': float(np.quantile(np.abs(values), .9, method='linear'))}


def fit_absolute(control, features, target):
    """Clone the control, changing only forest loss before fitting training data."""
    model = clone(control).set_params(regressor__criterion='absolute_error')
    model.fit(features, target)
    return model


def summarize(predictions):
    """Retain overall and training-defined larger-change scores, including empties."""
    def score(part):
        if len(part): return regression_scores(part.actual, part.prediction)
        return dict(n=0, mae=None, rmse=None, bias=None, persistence_mae=None, mae_skill_vs_persistence=None)
    metrics, pooled = [], []
    keys = ['window', 'site', 'fold', 'method']
    for identifiers, part in predictions.groupby(keys):
        for stratum in ('all', 'larger'):
            subset = part if stratum == 'all' else part[part.actual.abs() > part.larger_cutoff]
            metrics.append(dict(zip(keys, identifiers)) | {'stratum': stratum, 'days': subset.day.nunique(), **score(subset)})
    metrics = pd.DataFrame(metrics)
    for identifiers, part in predictions.groupby(['window', 'method']):
        window, method = identifiers
        for stratum in ('all', 'larger'):
            subset = part if stratum == 'all' else part[part.actual.abs() > part.larger_cutoff]
            groups = metrics[(metrics.window == window) & (metrics.method == method) & (metrics.stratum == stratum)]
            pooled.append({'window': window, 'method': method, 'stratum': stratum,
                'days': subset.day.nunique(), 'nonempty_site_month_groups': int((groups.n > 0).sum()),
                'equal_group_mae': float(groups.mae.dropna().mean()) if groups.mae.notna().any() else None,
                **score(subset)})
    daily = predictions.assign(absolute_error=(predictions.prediction - predictions.actual).abs()).groupby(
        keys + ['day'], as_index=False).agg(n=('actual', 'size'), mae=('absolute_error', 'mean'))
    return metrics, pd.DataFrame(pooled), daily


def needs_rolling(pooled):
    """Trigger the fixed second step unless the first forest beats both constants."""
    rows = pooled[(pooled.window == 'expanding') & (pooled.stratum == 'all')].set_index('method')
    forest = rows.loc['forest_absolute', 'mae']
    return not (forest < rows.loc['persistence', 'mae'] and forest < rows.loc['median_change', 'mae'])


def load_parent(parent):
    """Verify trusted parent inputs and identify its twelve squared-error controls."""
    summary = json.loads((parent / 'summary.json').read_text())
    receipt = json.loads((parent / 'independent_verification.json').read_text())
    if summary['analysis_code_sha256'] != sha256(ROOT / 'iron_horse/continuous.py'):
        raise ValueError('Parent analysis code differs from the recorded implementation')
    if summary['plan_sha256'] != sha256(ROOT / 'docs/continuous-forecast-plan.md'):
        raise ValueError('Parent plan changed')
    if receipt['verifier_sha256'] != sha256(ROOT / 'scripts/verify_continuous.py'):
        raise ValueError('Parent verifier changed')
    controls = {(fit['site'], fit['fold']): fit for fit in summary['fits'] if fit['outcome'] == 'water'
                and fit['policy'] == 'covered' and fit['method'] == 'forest_history'}
    if set(controls) != {(site, fold) for site in WATER_DEVICES for fold in FOLDS}:
        raise ValueError('Parent controls do not cover the planned twelve panels')
    inputs = {name: sha256(parent / name) for name in ['summary.json', 'independent_verification.json']}
    for name in ['examples.parquet', 'predictions.parquet', *[fit['path'] for fit in controls.values()]]:
        expected = summary['artifact_hashes'][name]
        if sha256(parent / name) != expected: raise ValueError('Parent artifact changed: ' + name)
        inputs[name] = expected
    return summary, pd.read_parquet(parent / 'examples.parquet'), pd.read_parquet(parent / 'predictions.parquet'), controls, inputs


def plot_scores(output, pooled):
    """Show the fixed arms on identical rows, in reported percentage points."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), layout='constrained')
    for ax, stratum in zip(axes, ['all', 'larger']):
        rows = pooled[pooled.stratum == stratum]
        ax.barh(rows.window + ' / ' + rows.method, rows.mae)
        ax.set(title=f'{stratum}: {int(rows.n.max())} scored location-hours', xlabel='MAE (reported percentage points)')
        ax.grid(axis='x', alpha=.2)
    fig.suptitle('Exploratory soil-water forecasts: fixed loss and window comparisons')
    fig.savefig(output / 'robust-mae.png', dpi=140);plt.close(fig)


def run(parent, output):
    """Run the fixed comparison and conditional follow-up without changing its parent."""
    parent, output = parent.resolve(), output.resolve()
    if output.is_relative_to(parent) or output.is_relative_to((ROOT / 'results').resolve()):
        raise ValueError('Choose a separate output outside the parent and recorded results')
    if output.exists(): raise FileExistsError('Output exists. Choose a new directory')
    code_hash, plan_hash = sha256(Path(__file__)), sha256(ROOT / 'docs/robust-forecast-plan.md')
    parent_summary, examples, previous, controls, inputs = load_parent(parent)
    water = examples[examples.outcome == 'water']
    output.mkdir(parents=True);(output / 'models').mkdir()
    predictions, references, fits = [], [], []
    thresholds = {}

    def fit_window(window, days):
        for site in WATER_DEVICES:
            panel = water[water.site == site]
            for fold in FOLDS:
                start = pd.Timestamp(fold + '-01', tz=TZ).tz_convert('UTC')
                end = (pd.Timestamp(fold + '-01', tz=TZ) + pd.offsets.MonthBegin()).tz_convert('UTC')
                train, test = split_panel(panel, start, end, days)
                if not len(train) or not len(test): raise ValueError('A planned panel is empty')
                ref = training_references(train.target_change)
                if window == 'expanding': thresholds[(site, fold)] = ref['larger_cutoff']
                cutoff = thresholds[(site, fold)]
                references.append({'window': window, 'site': site, 'fold': fold, 'train_rows': len(train),
                    'eval_rows': len(test), 'median_change': ref['median_change'], 'larger_cutoff': cutoff,
                    'window_training_q90': ref['larger_cutoff'], 'first_training_issue': train.time.min().isoformat(),
                    'last_training_outcome': (train.time.max() + pd.Timedelta(hours=24)).isoformat()})
                base = test[['time']].copy()
                base['day'] = test.time.dt.tz_convert(TZ).dt.strftime('%Y-%m-%d')
                base['window'], base['site'], base['fold'] = window, site, fold
                base['actual'], base['larger_cutoff'] = test.target_change, cutoff
                predictions.extend([base.assign(method='persistence', prediction=0.),
                                    base.assign(method='median_change', prediction=ref['median_change'])])
                control_fit = controls[(site, fold)]
                artifact = joblib.load(parent / control_fit['path'])
                columns, control = artifact['columns'], artifact['model']
                if not all(key.startswith('history__') for key in columns): raise ValueError('Control contains extra predictors')
                if window == 'expanding':
                    if len(train) != control_fit['train_rows'] or len(test) != control_fit['eval_rows']:
                        raise ValueError('Covered rows differ from the parent control')
                    old = previous[(previous.outcome == 'water') & (previous.site == site) & (previous.fold == fold)
                                   & (previous.policy == 'covered') & (previous.method == 'forest_history')].sort_values('time')
                    if list(old.time) != list(test.time): raise ValueError('Control forecast identities changed')
                    np.testing.assert_allclose(old.actual, test.target_change, rtol=0, atol=0)
                    predictions.append(base.assign(method='forest_squared', prediction=old.prediction.to_numpy()))
                began = perf_counter()
                model = fit_absolute(control, train[columns], train.target_change)
                parameters = model.named_steps['regressor'].get_params()
                expected = control.named_steps['regressor'].get_params() | {'criterion': 'absolute_error'}
                if parameters != expected: raise ValueError('Forest parameters changed beyond the criterion')
                name = f'models/{window}-{site}-{fold}.joblib'
                joblib.dump({'model': model, 'columns': columns}, output / name)
                fits.append({'window': window, 'site': site, 'fold': fold, 'path': name,
                    'sha256': sha256(output / name), 'control_path': control_fit['path'], 'parameters': parameters,
                    'train_rows': len(train), 'eval_rows': len(test), 'fit_seconds': perf_counter() - began})
                predictions.append(base.assign(method='forest_absolute', prediction=model.predict(test[columns])))
                print(f'{window} {site} {fold}: {len(train)} fit, {len(test)} score, {fits[-1]["fit_seconds"]:.1f}s', flush=True)

    fit_window('expanding', None)
    first = pd.concat(predictions, ignore_index=True)
    _, initial_pooled, _ = summarize(first)
    first.to_parquet(output / 'expanding_predictions.parquet', index=False)
    initial_pooled.to_csv(output / 'expanding_pooled.csv', index=False)
    trigger = needs_rolling(initial_pooled)
    initial_scores = initial_pooled[initial_pooled.stratum == 'all'].set_index('method').mae.to_dict()
    save_json(output / 'decision.json', {'rolling90_triggered': bool(trigger), 'expanding_overall_mae': initial_scores,
        'rule': 'Run rolling90 unless the expanding absolute-error forest beats both constant references.'})
    if trigger:
        print('Fixed rolling90 trigger met', flush=True)
        fit_window('rolling90', 90)
    forecasts = pd.concat(predictions, ignore_index=True)
    forecasts.to_parquet(output / 'predictions.parquet', index=False)
    metrics, pooled, daily = summarize(forecasts)
    for name, frame in [('metrics', metrics), ('pooled_metrics', pooled), ('daily_errors', daily),
                        ('training_references', pd.DataFrame(references))]:
        frame.to_csv(output / (name + '.csv'), index=False)
    plot_scores(output, pooled)
    if sha256(Path(__file__)) != code_hash or sha256(ROOT / 'docs/robust-forecast-plan.md') != plan_hash:
        raise ValueError('Experiment implementation or plan changed during fitting')
    names = ['expanding_predictions.parquet', 'expanding_pooled.csv', 'decision.json', 'predictions.parquet',
             'metrics.csv', 'pooled_metrics.csv', 'daily_errors.csv', 'training_references.csv', 'robust-mae.png',
             *[fit['path'] for fit in fits]]
    save_json(output / 'summary.json', {'analysis': 'exploratory robust soil-water forecasts', 'created_at_utc': now(),
        'source_sha256': parent_summary['source_sha256'], 'parent_input_hashes': inputs,
        'analysis_code_sha256': code_hash, 'plan_sha256': plan_hash, 'models_fitted': len(fits),
        'rolling90_triggered': bool(trigger), 'new_cleaning_rules': False, 'formally_adopted_protocol': False,
        'artifact_hashes': {name: sha256(output / name) for name in names}, 'fits': fits})
    print(pooled.to_string(index=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/robust-forecast')
    args = parser.parse_args()
    run(args.parent, args.output)
