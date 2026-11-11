"""Pooled soil-water forecasts with block-only and block-plus-time holdouts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import pandas as pd

from .core import ROOT, TZ, START, END, now, save_json, sha256
from .continuous import FOLDS, WATER_DEVICES, fold_masks, regression_scores
from .robust import load_parent, fit_absolute


def summer_mask(times):
    """Identify the common month-purged June–August evaluation rows."""
    times = pd.DatetimeIndex(times)
    result = np.zeros(len(times), dtype=bool)
    for fold in FOLDS:
        start = pd.Timestamp(fold + '-01', tz=TZ).tz_convert('UTC')
        end = (pd.Timestamp(fold + '-01', tz=TZ) + pd.offsets.MonthBegin()).tz_convert('UTC')
        _, test = fold_masks(times, start, end)
        result |= test
    return result


def select_split(data, design, held_site, fold=None):
    """Apply the fixed block and time rules to covered examples."""
    finish = data.time + pd.Timedelta(hours=24)
    eligible = data.eligible_covered & (data.time >= START) & (finish < END)
    if design == 'block_only':
        return data[eligible & (data.site != held_site)], data[eligible & (data.site == held_site)]
    if design not in {'block_time', 'pooled_time'}: raise ValueError('Unknown transfer design')
    start = pd.Timestamp(fold + '-01', tz=TZ).tz_convert('UTC')
    end = (pd.Timestamp(fold + '-01', tz=TZ) + pd.offsets.MonthBegin()).tz_convert('UTC')
    train_mask, test_mask = fold_masks(data.time, start, end)
    if design == 'block_time':
        train_mask &= data.site != held_site
        test_mask &= data.site == held_site
    return data[eligible & train_mask], data[eligible & test_mask]


def summarize(predictions):
    """Score full-season spatial and matched summer cases as separate scopes."""
    scoped = pd.concat([
        predictions[predictions.design == 'block_only'].assign(scope='full_season'),
        predictions[predictions.common_eval].assign(scope='common_summer')], ignore_index=True)
    keys = ['scope', 'design', 'site', 'fold', 'method']
    records = []
    for identifiers, part in scoped.groupby(keys):
        records.append(dict(zip(keys, identifiers)) | {'days': part.day.nunique(), **regression_scores(part.actual, part.prediction)})
    metrics = pd.DataFrame(records)
    pooled = []
    for identifiers, part in scoped.groupby(['scope', 'design', 'method']):
        scope, design, method = identifiers
        groups = metrics[(metrics.scope == scope) & (metrics.design == design) & (metrics.method == method)]
        pooled.append({'scope': scope, 'design': design, 'method': method, 'days': part.day.nunique(),
            'site_month_groups': len(groups), 'equal_group_mae': float(groups.mae.mean()),
            **regression_scores(part.actual, part.prediction)})
    daily = scoped.assign(absolute_error=(scoped.prediction - scoped.actual).abs()).groupby(
        keys + ['day'], as_index=False).agg(n=('actual', 'size'), mae=('absolute_error', 'mean'))
    return metrics, pd.DataFrame(pooled), daily


def plot_scores(output, pooled, metrics):
    """Display scope differences and matched monthly transfer errors."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), layout='constrained')
    for ax, scope in zip(axes, ['full_season', 'common_summer']):
        rows = pooled[pooled.scope == scope]
        ax.barh(rows.design + ' / ' + rows.method, rows.mae)
        ax.set(title=f'{scope}: {int(rows.n.max())} location-hours', xlabel='MAE (reported percentage points)')
        ax.grid(axis='x', alpha=.2)
    fig.suptitle('Exploratory block transfer: full-season and common-summer scores use different cases')
    fig.savefig(output / 'transfer-mae.png', dpi=140);plt.close(fig)
    fig, axes = plt.subplots(1, 4, figsize=(14, 4), layout='constrained')
    for ax, site in zip(axes, WATER_DEVICES):
        rows = metrics[(metrics.scope == 'common_summer') & (metrics.site == site)]
        for design, part in rows[rows.method == 'forest_absolute'].groupby('design'):
            ax.plot(part.fold.str[-2:], part.mae, marker='o', label=design)
        baseline = rows[(rows.design == 'pooled_time') & (rows.method == 'persistence')]
        ax.plot(baseline.fold.str[-2:], baseline.mae, marker='o', color='black', ls='--', label='persistence')
        ax.set(title=site.rsplit('-', 1)[-1], ylabel='MAE (points)');ax.grid(alpha=.2)
    axes[0].legend(fontsize=6)
    fig.suptitle('Identical summer cases: block suffixes 1=P, 2=Cc, 4=B North, 5=F')
    fig.savefig(output / 'transfer-monthly.png', dpi=140);plt.close(fig)


def run(parent, output):
    """Fit the nineteen predeclared pooled models in a new output directory."""
    parent, output = parent.resolve(), output.resolve()
    if output.is_relative_to(parent) or output.is_relative_to((ROOT / 'results').resolve()):
        raise ValueError('Choose an output outside the parent and recorded results')
    if output.exists(): raise FileExistsError('Output exists. Choose a new directory')
    code_hash, plan_hash = sha256(Path(__file__)), sha256(ROOT / 'docs/block-transfer-plan.md')
    parent_summary, examples, _, controls, inputs = load_parent(parent)
    water = examples[examples.outcome == 'water']
    template_path = controls[(next(iter(WATER_DEVICES)), FOLDS[0])]['path']
    template = joblib.load(parent / template_path)
    columns, control = template['columns'], template['model']
    if not all(key.startswith('history__') for key in columns): raise ValueError('Only common history predictors are permitted')
    output.mkdir(parents=True);(output / 'models').mkdir()
    predictions, references, fits = [], [], []
    specifications = [('block_only', site, None) for site in WATER_DEVICES]
    specifications += [('block_time', site, fold) for site in WATER_DEVICES for fold in FOLDS]
    specifications += [('pooled_time', None, fold) for fold in FOLDS]
    for design, held_site, fold in specifications:
        train, test = select_split(water, design, held_site, fold)
        if not len(train) or not len(test): raise ValueError('A planned split is empty')
        median = float(np.median(train.target_change))
        fit_id = f'{design}-{held_site or "all"}-{fold or "all"}'
        base = test[['site', 'time']].copy()
        base['fit_id'], base['design'] = fit_id, design
        local = test.time.dt.tz_convert(TZ)
        base['fold'], base['day'] = local.dt.strftime('%Y-%m'), local.dt.strftime('%Y-%m-%d')
        base['common_eval'], base['actual'] = summer_mask(test.time), test.target_change
        predictions.extend([base.assign(method='persistence', prediction=0.),
                            base.assign(method='median_change', prediction=median)])
        began = perf_counter()
        model = fit_absolute(control, train[columns], train.target_change)
        parameters = model.named_steps['regressor'].get_params()
        if parameters != control.named_steps['regressor'].get_params() | {'criterion': 'absolute_error'}:
            raise ValueError('Forest parameters differ from the fixed specification')
        name = 'models/' + fit_id + '.joblib'
        joblib.dump({'model': model, 'columns': columns}, output / name)
        reference = {'fit_id': fit_id, 'design': design, 'held_site': held_site, 'fold': fold,
            'train_rows': len(train), 'eval_rows': len(test), 'median_change': median,
            'train_sites': ','.join(sorted(train.site.unique())), 'eval_sites': ','.join(sorted(test.site.unique())),
            'first_train_issue': train.time.min().isoformat(),
            'last_train_outcome': (train.time.max() + pd.Timedelta(hours=24)).isoformat(),
            'first_eval_issue': test.time.min().isoformat(), 'last_eval_outcome': (test.time.max() + pd.Timedelta(hours=24)).isoformat()}
        references.append(reference)
        fits.append(reference | {'path': name, 'sha256': sha256(output / name), 'parameters': parameters,
                                 'fit_seconds': perf_counter() - began})
        predictions.append(base.assign(method='forest_absolute', prediction=model.predict(test[columns])))
        print(f'{fit_id}: {len(train)} fit, {len(test)} score, {fits[-1]["fit_seconds"]:.1f}s', flush=True)
    forecasts = pd.concat(predictions, ignore_index=True)
    # Every common-summer comparison must use the same outcomes at the same times.
    common = forecasts[(forecasts.method == 'persistence') & forecasts.common_eval]
    anchor = None
    for _, part in common.groupby('design'):
        identities = part.sort_values(['site', 'time'])[['site', 'time', 'actual']].reset_index(drop=True)
        if anchor is None: anchor = identities
        else: pd.testing.assert_frame_equal(identities, anchor)
    forecasts.to_parquet(output / 'predictions.parquet', index=False)
    metrics, pooled, daily = summarize(forecasts)
    for name, frame in [('metrics', metrics), ('pooled_metrics', pooled), ('daily_errors', daily),
                        ('split_counts', pd.DataFrame(references))]:frame.to_csv(output / (name + '.csv'), index=False)
    plot_scores(output, pooled, metrics)
    if sha256(Path(__file__)) != code_hash or sha256(ROOT / 'docs/block-transfer-plan.md') != plan_hash:
        raise ValueError('Implementation or plan changed during fitting')
    names = ['predictions.parquet', 'metrics.csv', 'pooled_metrics.csv', 'daily_errors.csv', 'split_counts.csv',
             'transfer-mae.png', 'transfer-monthly.png', *[fit['path'] for fit in fits]]
    save_json(output / 'summary.json', {'analysis': 'exploratory block transfer', 'created_at_utc': now(),
        'source_sha256': parent_summary['source_sha256'], 'parent_input_hashes': inputs, 'template_path': template_path,
        'analysis_code_sha256': code_hash, 'plan_sha256': plan_hash, 'models_fitted': len(fits),
        'new_cleaning_rules': False, 'formally_adopted_protocol': False,
        'artifact_hashes': {name: sha256(output / name) for name in names}, 'fits': fits})
    print(pooled.to_string(index=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/block-transfer')
    args = parser.parse_args()
    run(args.parent, args.output)
