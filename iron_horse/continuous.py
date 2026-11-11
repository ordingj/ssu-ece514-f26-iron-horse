"""Exploratory next-day change forecasts with fixed chronological comparisons."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline

from .core import ROOT, TZ, FrozenPreprocessor, now, save_json, sha256, slopes
from .sensor_compare import load_channels

WATER_DEVICES = dict(zip([f'SDI-12-LS-US915-{i}' for i in (1, 2, 4, 5)],
                         [f'SE01-LS-{i}' for i in (2, 1, 3, 4)]))
POLICIES = ('covered', 'complete')
FOLDS = ('2026-06', '2026-07', '2026-08')


def longest_missing(values):
    """Count the longest consecutive missing run within an hourly window."""
    best = length = 0
    for value in values:
        length = 0 if value else length + 1
        best = max(best, length)
    return best


def build_examples(hourly, info, water_devices=WATER_DEVICES):
    """Build trailing predictors and explicit observed-endpoint outcomes."""
    records = []
    local = hourly.index.tz_convert(TZ)
    calendar = {'history__hour_sin': np.sin(2 * np.pi * local.hour / 24),
                'history__hour_cos': np.cos(2 * np.pi * local.hour / 24),
                'history__day_sin': np.sin(2 * np.pi * local.dayofyear / 365),
                'history__day_cos': np.cos(2 * np.pi * local.dayofyear / 365)}
    for site, water in water_devices.items():
        potential_key = site + ':potential'
        water_key = water + ':device_frmpayload_data_water_SOIL'
        block = info[potential_key]['block']
        for outcome, key in [('water', water_key), ('potential', potential_key)]:
            series = hourly[key]
            present = series.notna().astype(float)
            future_count = present.rolling(24, min_periods=24).sum().shift(-24)
            past_gap = present.rolling(25, min_periods=25).apply(longest_missing, raw=True)
            future_gap = present.rolling(24, min_periods=24).apply(longest_missing, raw=True).shift(-24)
            count6, count24 = present.rolling(6, min_periods=1).sum(), present.rolling(24, min_periods=1).sum()
            past = series.notna() & series.shift(6).notna() & series.shift(24).notna() & (count6 >= 4) & (count24 >= 18) & (past_gap <= 2)
            complete = present.rolling(25, min_periods=25).sum() == 25
            future = series.shift(-24).notna() & (future_count >= 20) & (future_gap <= 2)
            values = {'time': hourly.index, 'site': site, 'block': block, 'outcome': outcome,
                      'current': series, 'future': series.shift(-24),
                      'target_change': series.shift(-24) - series,
                      'trend_change': 4 * (series - series.shift(6)),
                      'past_covered': past, 'past_complete': complete,
                      'eligible_covered': past & future,
                      'eligible_complete': complete & (future_count == 24),
                      'near_zero': (series.abs() <= 1) if outcome == 'potential' else False,
                      'recent_jump': (series.diff().abs() >= 100).rolling(24, min_periods=1).max().astype(bool) if outcome == 'potential' else False,
                      **calendar,
                      'history__current': series,
                      'history__lag1': series.shift(1), 'history__lag6': series.shift(6),
                      'history__lag24': series.shift(24),
                      'history__mean6': series.rolling(6, min_periods=1).mean(),
                      'history__mean24': series.rolling(24, min_periods=1).mean(),
                      'history__std24': series.rolling(24, min_periods=2).std(),
                      'history__slope6': slopes(series.to_numpy(), 6),
                      'history__slope24': slopes(series.to_numpy(), 24)}
            relevant = [name for name, meta in info.items() if name != key and
                        (meta['block'] == block or meta['device'] == 'SDI-12-LS-US915-3' or
                         meta['kind'] == 'air_temperature_c')]
            for name in relevant:
                channel = hourly[name]
                prefix = 'extra__' + name + '__'
                values[prefix + 'current'] = channel
                for width in (6, 24):
                    window = channel.rolling(width, min_periods=1)
                    rain = info[name]['kind'] == 'precipitation_mm'
                    values[prefix + ('sum' if rain else 'mean') + str(width)] = window.sum() if rain else window.mean()
                    values[prefix + 'change' + str(width)] = channel - channel.shift(width)
                values[prefix + 'count24'] = channel.notna().rolling(24, min_periods=1).sum()
            records.append(pd.DataFrame(values, index=hourly.index).reset_index(drop=True))
    return pd.concat(records, ignore_index=True)


def fold_masks(times, start, end):
    """Purge endpoints at or beyond each chronological partition boundary."""
    times = pd.DatetimeIndex(times)
    finish = times + pd.Timedelta(hours=24)
    return (times < start) & (finish < start), (times >= start) & (finish < end)


def regression_scores(actual, prediction):
    """Score paired changes in native outcome units, with persistence as zero."""
    actual, prediction = np.asarray(actual), np.asarray(prediction)
    error = prediction - actual
    mae = float(np.mean(np.abs(error)))
    reference = float(np.mean(np.abs(actual)))
    return {'n': len(actual), 'mae': mae, 'rmse': float(np.sqrt(np.mean(error ** 2))),
            'bias': float(np.mean(error)), 'persistence_mae': reference,
            'mae_skill_vs_persistence': 1 - mae / reference if reference else None}


def aggregate_predictions(predictions):
    """Retain comparable scores by month, location, historical regime, and day."""
    rows = []
    keys = ['outcome', 'policy', 'fold', 'site', 'method']
    for identifiers, part in predictions.groupby(keys):
        for stratum, subset in [('all', part), ('near_zero', part[part.near_zero]),
                                ('recent_jump', part[part.recent_jump])]:
            if not len(subset): continue
            rows.append(dict(zip(keys, identifiers)) | {'stratum': stratum,
                'days': subset.day.nunique(), **regression_scores(subset.actual, subset.prediction)})
    metrics = pd.DataFrame(rows)
    pooled = []
    for identifiers, part in predictions.groupby(['outcome', 'policy', 'method']):
        base = dict(zip(['outcome', 'policy', 'method'], identifiers))
        groups = metrics[(metrics.outcome == base['outcome']) & (metrics.policy == base['policy']) &
                         (metrics.method == base['method']) & (metrics.stratum == 'all')]
        pooled.append(base | {'days': part.day.nunique(), 'site_month_groups': len(groups),
            'equal_group_mae': float(groups.mae.mean()), **regression_scores(part.actual, part.prediction)})
    daily = predictions.assign(absolute_error=(predictions.prediction - predictions.actual).abs()).groupby(
        keys + ['day'], as_index=False).agg(n=('actual', 'size'), mae=('absolute_error', 'mean'))
    common = []
    pair_keys = ['outcome', 'fold', 'site', 'method', 'time']
    paired = predictions[predictions.policy == 'covered'].merge(
        predictions[predictions.policy == 'complete'], on=pair_keys, suffixes=('_covered', '_complete'), validate='one_to_one')
    for identifiers, part in paired.groupby(pair_keys[:-1]):
        common.append(dict(zip(pair_keys[:-1], identifiers)) | {'n_common': len(part),
            'covered_fit_mae': float((part.prediction_covered - part.actual_covered).abs().mean()),
            'complete_fit_mae': float((part.prediction_complete - part.actual_complete).abs().mean())})
    return metrics, pd.DataFrame(pooled), daily, pd.DataFrame(common)


def plot_results(output, metrics, pooled):
    """Plot native-unit error and temporal consistency without mixing outcomes."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout='constrained')
    for ax, outcome, unit in zip(axes, ['water', 'potential'], ['percentage points', 'kPa']):
        frame = pooled[(pooled.outcome == outcome) & (pooled.policy == 'covered')]
        ax.barh(frame.method, frame.mae)
        ax.set(title=outcome + ': covered windows', xlabel='Pooled MAE (' + unit + ')')
        ax.grid(axis='x', alpha=.2)
    fig.suptitle('Exploratory 24-hour change forecasts: earlier months fit each evaluated month')
    fig.savefig(output / 'forecast-mae.png', dpi=140);plt.close(fig)
    fig, axes = plt.subplots(2, 4, figsize=(14, 7), sharex=True, layout='constrained')
    for row, outcome in enumerate(['water', 'potential']):
        for col, site in enumerate(WATER_DEVICES):
            ax = axes[row, col]
            frame = metrics[(metrics.outcome == outcome) & (metrics.site == site) &
                            (metrics.policy == 'covered') & (metrics.stratum == 'all')]
            for method, part in frame.groupby('method'):
                ax.plot(part.fold.str[-2:], part.mae, marker='o', markersize=3, label=method)
            ax.set(title=site.rsplit('-', 1)[-1] + ' / ' + outcome, ylabel='MAE (points)' if row == 0 else 'MAE (kPa)')
            ax.grid(alpha=.2)
    axes[0, 0].legend(fontsize=6)
    fig.suptitle('Location and month differences; site suffixes: 1=P, 2=Cc, 4=B North, 5=F')
    fig.savefig(output / 'monthly-mae.png', dpi=140);plt.close(fig)


def artifact_hashes(output, model_paths):
    """Hash declared scientific outputs, excluding incidental filesystem files."""
    names = ['hourly.parquet', 'examples.parquet', 'channel_metadata.json', 'predictions.parquet',
             'metrics.csv', 'pooled_metrics.csv', 'daily_errors.csv', 'common_policy_comparison.csv',
             'coverage.csv', 'forecast-mae.png', 'monthly-mae.png', *model_paths]
    return {name: sha256(output / name) for name in names}


def run(folder, output):
    """Fit the fixed exploration in a new folder, preserving all prior runs."""
    folder, output = folder.resolve(), output.resolve()
    if output.is_relative_to(folder) or output.is_relative_to((ROOT / 'results').resolve()):
        raise ValueError('Choose a separate output directory under runs/')
    if output.exists(): raise FileExistsError('Output exists. Choose a new directory')
    plan_hash = sha256(ROOT / 'docs/continuous-forecast-plan.md')
    hourly, info, _, prep, inputs = load_channels(folder)
    examples = build_examples(hourly, info)
    output.mkdir(parents=True);(output / 'models').mkdir()
    hourly.to_parquet(output / 'hourly.parquet')
    examples.to_parquet(output / 'examples.parquet', index=False)
    save_json(output / 'channel_metadata.json', info)
    forecasts, coverage, fits = [], [], []
    for (outcome, site), panel in examples.groupby(['outcome', 'site']):
        for fold in FOLDS:
            start = pd.Timestamp(fold + '-01', tz=TZ).tz_convert('UTC')
            end = (pd.Timestamp(fold + '-01', tz=TZ) + pd.offsets.MonthBegin()).tz_convert('UTC')
            train_mask, test_mask = fold_masks(panel.time, start, end)
            for policy in POLICIES:
                eligible = panel['eligible_' + policy]
                train, test = panel[train_mask & eligible], panel[test_mask & eligible]
                coverage.append({'outcome': outcome, 'site': site, 'fold': fold, 'policy': policy,
                    'training_rows': len(train), 'training_days': train.time.dt.tz_convert(TZ).dt.date.nunique(),
                    'scheduled_eval_rows': int(test_mask.sum()),
                    'past_eligible_rows': int((test_mask & panel['past_' + policy]).sum()),
                    'scored_rows': len(test), 'scored_days': test.time.dt.tz_convert(TZ).dt.date.nunique()})
                if not len(train) or not len(test): continue
                base = test[['time', 'near_zero', 'recent_jump']].copy()
                base['day'] = test.time.dt.tz_convert(TZ).dt.strftime('%Y-%m-%d')
                base['outcome'], base['site'], base['fold'], base['policy'] = outcome, site, fold, policy
                base['actual'] = test.target_change
                for method, prediction in [('persistence', np.zeros(len(test))), ('trend6', test.trend_change.to_numpy())]:
                    forecasts.append(base.assign(method=method, prediction=prediction))
                for featureset in ('history', 'expanded'):
                    columns = [key for key in examples if key.startswith('history__') or
                               (featureset == 'expanded' and key.startswith('extra__'))]
                    for kind in ('ridge', 'forest'):
                        estimator = Ridge(alpha=10.) if kind == 'ridge' else RandomForestRegressor(
                            n_estimators=200, max_depth=6, min_samples_leaf=24, random_state=514, n_jobs=2)
                        model = Pipeline([('preprocess', FrozenPreprocessor()), ('regressor', estimator)])
                        model.fit(train[columns], train.target_change)
                        prediction = model.predict(test[columns])
                        method = kind + '_' + featureset
                        name = f'models/{outcome}-{site}-{fold}-{policy}-{method}.joblib'
                        joblib.dump({'model': model, 'columns': columns}, output / name)
                        fits.append({'outcome': outcome, 'site': site, 'fold': fold, 'policy': policy,
                            'method': method, 'path': name, 'sha256': sha256(output / name),
                            'train_rows': len(train), 'eval_rows': len(test),
                            'latest_training_outcome': (train.time.max() + pd.Timedelta(hours=24)).isoformat(),
                            'evaluation_start': start.isoformat(), 'evaluation_end': end.isoformat()})
                        forecasts.append(base.assign(method=method, prediction=prediction))
                print(f'{outcome} {site} {fold} {policy}: {len(train)} fit, {len(test)} score', flush=True)
    predictions = pd.concat(forecasts, ignore_index=True)
    predictions.to_parquet(output / 'predictions.parquet', index=False)
    metrics, pooled, daily, common = aggregate_predictions(predictions)
    for name, frame in [('metrics', metrics), ('pooled_metrics', pooled), ('daily_errors', daily),
                        ('common_policy_comparison', common), ('coverage', pd.DataFrame(coverage))]:
        frame.to_csv(output / (name + '.csv'), index=False)
    plot_results(output, metrics, pooled)
    artifacts = artifact_hashes(output, [fit['path'] for fit in fits])
    save_json(output / 'summary.json', {'analysis': 'exploratory continuous forecasting', 'created_at_utc': now(),
        'source_sha256': prep['source_sha256'], 'input_hashes': inputs, 'plan_sha256': plan_hash,
        'analysis_code_sha256': sha256(Path(__file__)), 'aggregation_code_sha256': sha256(ROOT / 'iron_horse/sensor_compare.py'),
        'models_fitted': len(fits), 'folds': FOLDS, 'new_cleaning_exclusions': 'coverage only',
        'formally_adopted_protocol': False, 'artifact_hashes': artifacts, 'fits': fits})
    print(json.dumps({'models_fitted': len(fits), 'prediction_rows': len(predictions)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/continuous-forecast')
    args = parser.parse_args()
    run(args.run, args.output)
