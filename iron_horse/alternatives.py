"""Fixed median-regression and boosting comparison on verified transfer splits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import QuantileRegressor
from sklearn.pipeline import Pipeline
from threadpoolctl import threadpool_limits

from .core import ROOT, FrozenPreprocessor, now, save_json, sha256
from .robust import load_parent
from .transfer import select_split, summarize

METHODS = ('median_regression', 'hist_boosting')


def fit_model(method, features, target):
    """Fit a fixed new model with training-only preprocessing and bounded pools."""
    if method == 'median_regression':
        estimator = QuantileRegressor(quantile=.5, alpha=.001, fit_intercept=True, solver='highs')
    elif method == 'hist_boosting':
        estimator = HistGradientBoostingRegressor(loss='absolute_error', learning_rate=.05, max_iter=100,
            max_depth=3, max_leaf_nodes=7, min_samples_leaf=24, l2_regularization=1.,
            early_stopping=False, random_state=514)
    else: raise ValueError('Unknown fixed model')
    model = Pipeline([('preprocess', FrozenPreprocessor()), ('regressor', estimator)])
    with threadpool_limits(limits=2): model.fit(features, target)
    return model


def predict_model(model, features):
    """Keep native prediction pools under the same limit as fitting."""
    with threadpool_limits(limits=2): return model.predict(features)


def load_transfer(transfer, parent_inputs):
    """Verify the previous transfer experiment and all reused prediction bytes."""
    summary = json.loads((transfer / 'summary.json').read_text())
    receipt = json.loads((transfer / 'independent_verification.json').read_text())
    if summary['analysis_code_sha256'] != sha256(ROOT / 'iron_horse/transfer.py'):
        raise ValueError('Transfer implementation changed')
    if summary['plan_sha256'] != sha256(ROOT / 'docs/block-transfer-plan.md'):
        raise ValueError('Transfer plan changed')
    if receipt['verifier_sha256'] != sha256(ROOT / 'scripts/verify_transfer.py'):
        raise ValueError('Transfer verifier changed')
    if summary['parent_input_hashes'] != parent_inputs:
        raise ValueError('Transfer inputs differ from the supplied continuous parent')
    names = ['summary.json', 'independent_verification.json', 'predictions.parquet',
             *[fit['path'] for fit in summary['fits']]]
    inputs = {}
    for name in names:
        actual = sha256(transfer / name)
        if name in summary['artifact_hashes'] and actual != summary['artifact_hashes'][name]:
            raise ValueError('Transfer artifact changed: ' + name)
        inputs[name] = actual
    return summary, pd.read_parquet(transfer / 'predictions.parquet'), inputs


def plot_scores(output, pooled):
    """Show every fixed method on the separate scoring scopes."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    order = ['persistence', 'median_change', 'forest_absolute', *METHODS]
    fig, axes = plt.subplots(1, 4, figsize=(17, 5), layout='constrained')
    settings = [('full_season', 'block_only'), ('common_summer', 'block_only'),
                ('common_summer', 'block_time'), ('common_summer', 'pooled_time')]
    for ax, (scope, design) in zip(axes, settings):
        rows = pooled[(pooled.scope == scope) & (pooled.design == design)].set_index('method').loc[order]
        ax.barh(rows.index, rows.mae)
        ax.set(title=f'{scope}\n{design}; n={int(rows.n.max())}', xlabel='MAE (reported points)')
        ax.grid(axis='x', alpha=.2)
    fig.suptitle('Fixed alternative models: full-season and common-summer cases remain separate')
    fig.savefig(output / 'alternative-mae.png', dpi=140);plt.close(fig)


def run(parent, transfer, output):
    """Fit both alternatives on the nineteen existing, unchanged split definitions."""
    parent, transfer, output = parent.resolve(), transfer.resolve(), output.resolve()
    if any(output.is_relative_to(source) for source in [parent, transfer, (ROOT / 'results').resolve()]):
        raise ValueError('Choose an output outside both parents and recorded results')
    if output.exists(): raise FileExistsError('Output exists. Choose a new directory')
    code_hash, plan_hash = sha256(Path(__file__)), sha256(ROOT / 'docs/alternative-models-plan.md')
    parent_summary, examples, _, _, parent_inputs = load_parent(parent)
    transfer_summary, previous, transfer_inputs = load_transfer(transfer, parent_inputs)
    if len(transfer_summary['fits']) != 19: raise ValueError('Expected nineteen transfer splits')
    water = examples[examples.outcome == 'water']
    template = joblib.load(parent / transfer_summary['template_path'])
    columns = template['columns']
    if not all(name.startswith('history__') for name in columns): raise ValueError('Only common history predictors are permitted')
    output.mkdir(parents=True);(output / 'models').mkdir()
    forecasts, fits = [previous.copy()], []
    for split in transfer_summary['fits']:
        train, test = select_split(water, split['design'], split['held_site'], split['fold'])
        test = test.sort_values(['site', 'time'])
        if len(train) != split['train_rows'] or len(test) != split['eval_rows']:
            raise ValueError('Split counts differ from the existing comparison')
        base = previous[(previous.fit_id == split['fit_id']) & (previous.method == 'persistence')].sort_values(['site', 'time'])
        if list(zip(base.site, base.time)) != list(zip(test.site, test.time)):
            raise ValueError('Evaluation identities differ from the existing comparison')
        np.testing.assert_allclose(base.actual, test.target_change, rtol=0, atol=0)
        base = base.drop(columns=['method', 'prediction'])
        for method in METHODS:
            began = perf_counter()
            model = fit_model(method, train[columns], train.target_change)
            estimator = model.named_steps['regressor']
            if method == 'hist_boosting' and estimator.do_early_stopping_:
                raise ValueError('Unexpected automatic boosting validation')
            name = f'models/{split["fit_id"]}-{method}.joblib'
            joblib.dump({'model': model, 'columns': columns}, output / name)
            fit = {'fit_id': split['fit_id'], 'design': split['design'], 'held_site': split['held_site'],
                'fold': split['fold'], 'method': method, 'path': name, 'sha256': sha256(output / name),
                'train_rows': len(train), 'eval_rows': len(test), 'parent_forest_path': split['path'],
                'parameters': estimator.get_params(deep=False), 'n_iter': int(estimator.n_iter_),
                'fit_seconds': perf_counter() - began}
            if method == 'median_regression':
                fit['nonzero_coefficients'] = int((np.abs(estimator.coef_) > 1e-8).sum())
            fits.append(fit)
            forecasts.append(base.assign(method=method, prediction=predict_model(model, test[columns])))
            print(f'{split["fit_id"]} {method}: {len(train)} fit, {len(test)} score, {fit["fit_seconds"]:.1f}s', flush=True)
    predictions = pd.concat(forecasts, ignore_index=True)
    predictions.to_parquet(output / 'predictions.parquet', index=False)
    metrics, pooled, daily = summarize(predictions)
    for name, frame in [('metrics', metrics), ('pooled_metrics', pooled), ('daily_errors', daily)]:
        frame.to_csv(output / (name + '.csv'), index=False)
    plot_scores(output, pooled)
    if sha256(Path(__file__)) != code_hash or sha256(ROOT / 'docs/alternative-models-plan.md') != plan_hash:
        raise ValueError('Implementation or plan changed during fitting')
    names = ['predictions.parquet', 'metrics.csv', 'pooled_metrics.csv', 'daily_errors.csv', 'alternative-mae.png',
             *[fit['path'] for fit in fits]]
    save_json(output / 'summary.json', {'analysis': 'exploratory alternative soil-water models', 'created_at_utc': now(),
        'source_sha256': parent_summary['source_sha256'], 'continuous_input_hashes': parent_inputs,
        'transfer_input_hashes': transfer_inputs, 'analysis_code_sha256': code_hash, 'plan_sha256': plan_hash,
        'models_fitted': len(fits), 'new_cleaning_rules': False, 'formally_adopted_protocol': False,
        'artifact_hashes': {name: sha256(output / name) for name in names}, 'fits': fits})
    print(pooled.to_string(index=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--transfer', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/alternative-models')
    args = parser.parse_args()
    run(args.parent, args.transfer, args.output)
