"""Run the current ECE514 RF protocol with separate preparation and test stages."""
from __future__ import annotations

import argparse
import itertools
import json
import math
import platform
import subprocess
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import polars as pl
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from threadpoolctl import threadpool_limits

from .core import (
    ROOT, H, TZ, START, END, GRID, MATRIC, WEATHER, RAW, FLAG, SOIL_RE,
    WEATHER_FIELDS, FrozenPreprocessor, decode_weather, ns, partition, slopes,
    window_stat, latest, scores, probabilities, coverage, sha256, save_json, now,
)
from .matric import decode_response
from .cc_policy import correct

THRESHOLD = -500.
CUTOFF = .70
SOURCE_SHA256 = '5770aeb5645c181e636f4f87ccb52555e7327525f389b82f91c0cdc18bfa9b04'
DEFAULT_SOURCE = ROOT / 'data/ihv-sensor-data-2026.csv'
REGISTRATION = ROOT / 'protocol'
DEFAULT_OUTPUT = ROOT / 'runs/checkpoint'
DEPENDENCIES = [Path(__file__), ROOT / 'iron_horse/core.py',
                ROOT / 'iron_horse/matric.py', ROOT / 'iron_horse/cc_policy.py',
                ROOT / 'metadata/devices.json', ROOT / 'metadata/probe_inventory.csv',
                ROOT / 'requirements.lock.txt', REGISTRATION / 'preregistration.txt',
                REGISTRATION / 'IMPLEMENTATION.md']


def implementation_hashes():
    return {str(p.relative_to(ROOT)): sha256(p) for p in DEPENDENCIES}


def matric_value(device, raw):
    """Keep supported kPa fields and exclude Cc fields with unresolved units."""
    reading = decode_response(raw)
    if reading is None:
        return np.nan
    if device == 'SDI-12-LS-US915-2':
        value = correct(raw, 'standard_format')['matric_potential_kpa']
        return np.nan if value is None else value
    return reading.potential_kpa


def forecast_labels(times, values, anchors):
    labels, counts, gaps = [], [], []
    for t in ns(anchors):
        left, right = np.searchsorted(times, [t, t + 24 * H], side='right')
        relative = times[left:right] - t
        count = len(np.unique((relative + H - 1) // H))
        gap = np.diff(np.concatenate(([0], relative, [24 * H]))).max()
        eligible = count >= 20 and gap <= 2 * H
        labels.append(float(np.any(values[left:right] <= THRESHOLD)) if eligible else np.nan)
        counts.append(count)
        gaps.append(float(gap / H))
    return np.asarray(labels), np.asarray(counts), np.asarray(gaps)


def baseline(frame):
    return ((frame.trend_6h_kpa_per_h < 0) &
            (frame.current_potential_kpa + 24 * frame.trend_6h_kpa_per_h <= THRESHOLD)).to_numpy(int)


class Preprocessor(FrozenPreprocessor):
    """Fit column retention and medians once, with optional numeric scaling."""
    def __init__(self, scale=True):
        self.scale = scale

    def transform(self, X):
        x = np.asarray(X, dtype=float)[:, self.keep_]
        missing = ~np.isfinite(x)
        numeric = np.where(missing, self.medians_, x)
        if self.scale:
            numeric = (numeric - self.means_) / self.scales_
        return np.concatenate((numeric, missing.astype(float)), axis=1)


def model_pipeline(kind, params):
    if kind == 'random_forest':
        classifier = RandomForestClassifier(
            n_estimators=300, criterion='gini', max_features='sqrt', bootstrap=True,
            random_state=514, **params)
    elif kind == 'logistic_regression':
        # scikit-learn 1.9.1 uses l1_ratio=0 for L2. Explicit penalty is deprecated.
        classifier = LogisticRegression(l1_ratio=0, solver='lbfgs', tol=.0001,
                                         max_iter=1000, **params)
    else:
        raise ValueError(f'Unknown model: {kind}')
    return Pipeline([('preprocess', Preprocessor(scale=kind == 'logistic_regression')),
                     ('classifier', classifier)])


def select_trial(kind, trials):
    if kind == 'random_forest':
        return max(trials, key=lambda r: (r['f1'], -r['max_depth'], r['min_samples_leaf']))
    return max(trials, key=lambda r: (r['f1'], -r['C']))


def bootstrap_interval(frame):
    days = pd.date_range('2026-07-01', '2026-08-31', freq='D').strftime('%Y-%m-%d')
    frame = frame.copy()
    frame['day'] = pd.DatetimeIndex(frame.time).tz_convert(TZ).strftime('%Y-%m-%d')
    counts = []
    for day in days:
        part = frame[frame.day == day]
        y = part.target.to_numpy(int)
        pair = []
        for column in ('rf_prediction', 'baseline_prediction'):
            p = part[column].to_numpy(int)
            pair.append([np.sum((y == 1) & (p == 1)), np.sum((y == 0) & (p == 1)),
                         np.sum((y == 1) & (p == 0))])
        counts.append(pair)
    counts = np.asarray(counts)
    rng = np.random.default_rng(514)
    differences = []
    for _ in range(2000):
        starts = rng.integers(0, len(days) - 6, size=math.ceil(len(days) / 7))
        sampled = np.concatenate([np.arange(s, s + 7) for s in starts])[:len(days)]
        f1 = []
        for tp, fp, fn in counts[sampled].sum(axis=0):
            denominator = 2 * tp + fp + fn
            f1.append(2 * tp / denominator if denominator else 0.)
        differences.append(f1[0] - f1[1])
    lo, hi = np.percentile(differences, [2.5, 97.5])
    return {'lower': float(lo), 'upper': float(hi), 'resamples': 2000,
            'block_days': 7, 'seed': 514}


def clean_measurements(source, destination):
    raw = pl.scan_csv(source, infer_schema_length=0)
    chosen = ((pl.col('device_name').is_in(MATRIC + [WEATHER]) & (pl.col('measurement') == RAW)) |
              (pl.col('device_name').str.contains(r'^SE0[1X]-LS-\d+$') &
               (pl.col('measurement').str.contains(SOIL_RE) | (pl.col('measurement') == FLAG))))
    fields = ['device_name', 'block', 'slope', 'measurement', 'value']
    selected = raw.filter(chosen).unique().select(['timestamp'] + fields).with_columns(
        pl.col('timestamp').str.to_datetime(time_zone='UTC', time_unit='ns').alias('time'))
    selected = selected.filter((pl.col('time') >= START.to_pydatetime()) &
                               (pl.col('time') < END.to_pydatetime()))
    cleaned = selected.group_by(['device_name', 'measurement', 'time']).agg(
        pl.col('value').first(), pl.col('value').n_unique().alias('value_versions'),
        pl.col('block').first(), pl.col('block').n_unique().alias('block_versions'),
        pl.col('slope').first(), pl.col('slope').n_unique().alias('slope_versions'),
        pl.len().alias('deduplicated_rows')).with_columns(
            ((pl.col('value_versions') == 1) & (pl.col('block_versions') == 1) &
             (pl.col('slope_versions') == 1)).alias('valid_key'))
    cleaned.sink_parquet(destination, compression='zstd')
    return pl.read_parquet(destination)


def build_inputs(cleaned, output):
    df = cleaned.to_pandas().sort_values(['device_name', 'time', 'measurement'])
    meta = json.loads((ROOT / 'metadata/devices.json').read_text())['by_device_name']
    disagreements = []
    for row in cleaned.select('device_name', 'block', 'slope').unique().to_dicts():
        expected = meta.get(row['device_name'], {})
        if any(row[k] != expected.get(k) for k in ('block', 'slope')):
            disagreements.append(row)
    audit = {'measurement_keys': len(df), 'conflicting_keys': int((~df.valid_key).sum()),
             'metadata_disagreements': disagreements}
    save_json(output / 'cleaning_audit.json', audit)
    if disagreements:
        raise ValueError('Source metadata differs from the captured device inventory')
    df.loc[~df.valid_key, 'value'] = None
    potential = {}
    decoder_audit = {}
    for device in MATRIC:
        part = df[(df.device_name == device) & (df.measurement == RAW)].copy()
        part['potential'] = [matric_value(device, v) for v in part.value]
        valid = part[np.isfinite(part.potential)]
        potential[device] = (ns(valid.time), valid.potential.to_numpy(float))
        decoder_audit[device] = {'responses': len(part), 'valid_kpa': len(valid),
                                 'excluded': len(part) - len(valid)}
    weather = df[(df.device_name == WEATHER) & (df.measurement == RAW)]
    decoded = np.asarray([decode_weather(v) for v in weather.value], dtype=float)
    weather_features = {f'weather__{field}__24h': window_stat(
        ns(weather.time), decoded[:, j], field == 'precipitation_mm')
        for j, field in enumerate(WEATHER_FIELDS)}
    decoder_audit['weather'] = {'responses': len(weather), 'valid_by_field': {
        field: int(np.isfinite(decoded[:, j]).sum()) for j, field in enumerate(WEATHER_FIELDS)}}
    soil = df[df.measurement.str.match(SOIL_RE)].copy()
    soil['numeric'] = pd.to_numeric(soil.value, errors='coerce')
    flags = df[df.measurement == FLAG].copy()
    flags['numeric'] = pd.to_numeric(flags.value, errors='coerce')
    bad = flags[(~flags.valid_key) | (flags.numeric == 0)][['device_name', 'time']].assign(bad=True)
    soil = soil.merge(bad, on=['device_name', 'time'], how='left')
    soil = soil[np.isfinite(soil.numeric) & soil.bad.isna()].copy()
    soil['slot'] = soil_slot_names(soil)
    inventory = pd.read_csv(ROOT / 'metadata/probe_inventory.csv')
    inventory = inventory[inventory.device_name.str.match(r'^SE0[1X]-LS-\d+$') &
                          inventory.measurement.str.match(SOIL_RE)].copy()
    slots = sorted(soil_slot_names(inventory).unique())
    save_json(output / 'decode_audit.json', decoder_audit)
    return assemble_inputs(potential, soil, weather_features, slots, output)


def soil_slot_names(frame):
    """Keep terrain and probe identities in the fixed soil predictor slots."""
    match = frame.measurement.str.extract(r'device_frmpayload_data_(water|temp)_SOIL([1-4]?)')
    return ('soil__' + frame.slope.fillna('unassigned') + '__probe' +
            match[1].replace('', '1') + '__' +
            match[0].map({'water': 'water_content', 'temp': 'temperature'}))


def assemble_inputs(potential, soil, weather_features, slots, output):
    """Build the fixed feature grid from accepted numeric observations."""
    meta = json.loads((ROOT / 'metadata/devices.json').read_text())['by_device_name']
    frames = []
    for device in MATRIC:
        times, values = potential[device]
        bins = pd.to_datetime(times, utc=True).ceil('h')
        hourly = pd.Series(values, index=bins).groupby(level=0).median().reindex(GRID).to_numpy(float)
        finite = np.isfinite(hourly)
        n6 = pd.Series(finite).rolling(6, min_periods=1).sum().to_numpy(int)
        n24 = pd.Series(finite).rolling(24, min_periods=1).sum().to_numpy(int)
        frame = pd.DataFrame({'time': GRID, 'site': device, 'block': meta[device]['block'],
            'partition': [partition(t) for t in GRID], 'current_potential_kpa': hourly,
            'trend_6h_kpa_per_h': slopes(hourly, 6), 'trend_24h_kpa_per_h': slopes(hourly, 24),
            'history_hours_6h': n6, 'history_hours_24h': n24})
        frame['forecast_eligible'] = finite & (n6 >= 4) & (n24 >= 18)
        frame['currently_dry'] = finite & (hourly <= THRESHOLD)
        frame['primary_input_eligible'] = frame.forecast_eligible & ~frame.currently_dry
        in_block = soil[soil.block == meta[device]['block']]
        for slot in slots:
            aligned = [latest(ns(rows.time), rows.numeric.to_numpy(float))
                       for _, rows in in_block[in_block.slot == slot].groupby('device_name')]
            frame[slot] = (pd.DataFrame(np.asarray(aligned).T).median(axis=1, skipna=True).to_numpy(float)
                           if aligned else np.nan)
        for name, values in weather_features.items():
            frame[name] = values
        frames.append(frame)
    inputs = pd.concat(frames, ignore_index=True).sort_values(['time', 'site']).reset_index(drop=True)
    columns = ['current_potential_kpa', 'trend_6h_kpa_per_h', 'trend_24h_kpa_per_h'] + slots + sorted(weather_features)
    save_json(output / 'feature_schema.json', {'columns': columns, 'soil_slots': slots, 'timezone': TZ})
    return inputs, potential


def label_partition(inputs, potential, parts):
    output = inputs[inputs.partition.isin(parts)].copy()
    output['target'] = np.nan
    output['future_occupied_hours'] = 0
    output['future_max_gap_hours'] = np.nan
    for site, positions in output.groupby('site').groups.items():
        labels, counts, gaps = forecast_labels(*potential[site], output.loc[positions, 'time'])
        output.loc[positions, 'target'] = labels
        output.loc[positions, 'future_occupied_hours'] = counts
        output.loc[positions, 'future_max_gap_hours'] = gaps
    output['evaluation_eligible'] = output.primary_input_eligible & output.target.notna()
    return output


def prepare(source, output):
    if (output / 'preparation.json').exists():
        raise FileExistsError('Preparation exists. Use develop or choose a new output directory')
    if sklearn.__version__ != '1.9.1':
        raise RuntimeError('This protocol requires scikit-learn 1.9.1')
    output.mkdir(parents=True, exist_ok=True)
    cache = output / 'cache'
    cache.mkdir(exist_ok=True)
    print('Verifying the complete source CSV checksum', flush=True)
    digest = sha256(source)
    if digest != SOURCE_SHA256:
        raise ValueError('Source CSV checksum differs from the registered complete export')
    print('Cleaning selected records from the complete source CSV', flush=True)
    cleaned = clean_measurements(source, cache / 'clean_measurements.parquet')
    inputs, potential = build_inputs(cleaned, output)
    inputs.to_parquet(cache / 'hourly_inputs.parquet', index=False)
    joblib.dump(potential, cache / 'potential.joblib')
    manifest = {'prepared_at_utc': now(), 'source': str(source), 'source_sha256': digest,
                'source_bytes': source.stat().st_size, 'implementation_hashes': implementation_hashes(),
                'python': platform.python_version(), 'scikit_learn': sklearn.__version__,
                'scheduled_hours': len(inputs), 'test_labels_constructed': False,
                'feature_schema_sha256': sha256(output / 'feature_schema.json'),
                'derived_hashes': {p.name: sha256(p) for p in cache.iterdir() if p.is_file()}}
    save_json(output / 'preparation.json', manifest)
    print('Preparation complete. No future labels have been constructed', flush=True)


def verify_preparation(output):
    prep = json.loads((output / 'preparation.json').read_text())
    if prep['feature_schema_sha256'] != sha256(output / 'feature_schema.json'):
        raise RuntimeError('The feature schema changed after preparation')
    if prep['implementation_hashes'] != implementation_hashes():
        raise RuntimeError('The implementation changed after preparation')
    for name, digest in prep['derived_hashes'].items():
        if sha256(output / 'cache' / name) != digest:
            raise RuntimeError(f'Prepared artifact changed: {name}')
    if prep.get('source_kind') == 'public_influx_api':
        from .api_checkpoint import verify_api_source
        verify_api_source(prep)
    return prep


def develop(output):
    if (output / 'model_freeze.json').exists() or (output / 'test_unlock.json').exists():
        raise FileExistsError('Models are already frozen. Use evaluate or choose a new output directory')
    verify_preparation(output)
    inputs = pd.read_parquet(output / 'cache/hourly_inputs.parquet')
    potential = joblib.load(output / 'cache/potential.joblib')
    columns = json.loads((output / 'feature_schema.json').read_text())['columns']
    dev = label_partition(inputs, potential, ['train', 'validation'])
    dev.to_parquet(output / 'cache/development_examples.parquet', index=False)
    train = dev[(dev.partition == 'train') & dev.evaluation_eligible]
    validation = dev[(dev.partition == 'validation') & dev.evaluation_eligible]
    counts = {part: {str(int(k)): int(v) for k, v in frame.target.value_counts().sort_index().items()}
              for part, frame in [('train', train), ('validation', validation)]}
    coverage(inputs[inputs.partition.isin(['train', 'validation'])], dev).to_csv(
        output / 'development_coverage.csv', index=False)
    if any(set(part_counts) != {'0', '1'} for part_counts in counts.values()):
        development_metrics = {part: {
            'drying_trend': scores(frame.target.to_numpy(int), baseline(frame)) if len(frame) else None,
            'always_defer': scores(frame.target.to_numpy(int), np.zeros(len(frame), dtype=int)) if len(frame) else None}
            for part, frame in [('train', train), ('validation', validation)]}
        save_json(output / 'development.json', {'class_counts': counts, 'baseline_metrics': development_metrics})
        save_json(output / 'results.json', {'status': 'not_evaluable',
                  'reason': 'Training and validation must each contain both classes',
                  'development_class_counts': counts, 'test_labels_constructed': False})
        print('Not evaluable: insufficient development class support', flush=True)
        return False
    trials = {}
    selected = {}
    development_metrics = {}
    models_dir = output / 'models'
    models_dir.mkdir(exist_ok=True)
    for kind in ('random_forest', 'logistic_regression'):
        candidates = ([{'max_depth': d, 'min_samples_leaf': leaf}
                       for d, leaf in itertools.product((4, 8), (10, 30))]
                      if kind == 'random_forest' else [{'C': c} for c in (.1, 1., 10.)])
        trials[kind] = []
        for params in candidates:
            model = model_pipeline(kind, params).fit(train[columns], train.target.to_numpy(int))
            metric = scores(validation.target.to_numpy(int), probabilities(model, validation[columns]) >= CUTOFF)
            trial = {**params, **metric}
            trials[kind].append(trial)
            print(kind, json.dumps(trial), flush=True)
        winner = select_trial(kind, trials[kind])
        selected[kind] = {key: winner[key] for key in candidates[0]}
        fit = dev[dev.evaluation_eligible]
        final = model_pipeline(kind, selected[kind]).fit(fit[columns], fit.target.to_numpy(int))
        joblib.dump(final, models_dir / f'{kind}.joblib')
    for part, frame in [('train', train), ('validation', validation)]:
        development_metrics[part] = {
            'drying_trend': scores(frame.target.to_numpy(int), baseline(frame)),
            'always_defer': scores(frame.target.to_numpy(int), np.zeros(len(frame), dtype=int))}
    save_json(output / 'development.json', {'class_counts': counts, 'validation_trials': trials,
                                           'selected': selected, 'baseline_metrics': development_metrics})
    frozen = {'frozen_at_utc': now(), 'selected': selected, 'score_cutoff': CUTOFF,
              'threshold_kpa': THRESHOLD, 'implementation_hashes': implementation_hashes(),
              'feature_schema_sha256': sha256(output / 'feature_schema.json'),
              'implementation_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'model_hashes': {p.name: sha256(p) for p in models_dir.glob('*.joblib')},
              'development_sha256': sha256(output / 'development.json'), 'test_labels_constructed': False}
    save_json(output / 'model_freeze.json', frozen)
    print('RF and logistic regression frozen before test labels', flush=True)
    return True


def evaluate(output):
    if (output / 'test_unlock.json').exists():
        raise FileExistsError('Test evaluation was already started. Choose a new output for a reproduction')
    prep = verify_preparation(output)
    frozen = json.loads((output / 'model_freeze.json').read_text())
    if frozen['feature_schema_sha256'] != sha256(output / 'feature_schema.json'):
        raise RuntimeError('The feature schema changed after model freeze')
    if frozen['implementation_hashes'] != implementation_hashes():
        raise RuntimeError('Implementation changed after model freeze')
    if sha256(output / 'development.json') != frozen['development_sha256']:
        raise RuntimeError('Development results changed after model freeze')
    for name, digest in frozen['model_hashes'].items():
        if sha256(output / 'models' / name) != digest:
            raise RuntimeError(f'Frozen model changed: {name}')
    save_json(output / 'test_unlock.json', {'unlocked_at_utc': now(),
              'model_freeze_sha256': sha256(output / 'model_freeze.json')})
    print('Opening July-August targets after model freeze', flush=True)
    inputs = pd.read_parquet(output / 'cache/hourly_inputs.parquet')
    potential = joblib.load(output / 'cache/potential.joblib')
    columns = json.loads((output / 'feature_schema.json').read_text())['columns']
    test_all = label_partition(inputs, potential, ['test'])
    test_all.to_parquet(output / 'cache/test_examples.parquet', index=False)
    test = test_all[test_all.evaluation_eligible].copy()
    dev = pd.read_parquet(output / 'cache/development_examples.parquet')
    all_labeled = pd.concat([dev, test_all], ignore_index=True)
    coverage(inputs, all_labeled).to_csv(output / 'coverage.csv', index=False)
    if not len(test):
        save_json(output / 'results.json', {'status': 'not_evaluable',
                  'reason': 'No eligible test examples', 'test_examples': 0,
                  'test_labels_constructed': True, 'source_sha256': prep['source_sha256']})
        print('Not evaluable: no eligible test examples', flush=True)
        return
    metrics = {}
    for kind, prefix in [('random_forest', 'rf'), ('logistic_regression', 'lr')]:
        model = joblib.load(output / 'models' / f'{kind}.joblib')
        test[f'{prefix}_score'] = probabilities(model, test[columns])
        test[f'{prefix}_prediction'] = (test[f'{prefix}_score'] >= CUTOFF).astype(int)
        metrics[kind] = scores(test.target.to_numpy(int), test[f'{prefix}_prediction'].to_numpy(int))
    test['baseline_prediction'] = baseline(test)
    metrics['drying_trend'] = scores(test.target.to_numpy(int), test.baseline_prediction.to_numpy(int))
    metrics['always_defer'] = scores(test.target.to_numpy(int), np.zeros(len(test), dtype=int))
    test['local_day'] = pd.DatetimeIndex(test.time).tz_convert(TZ).strftime('%Y-%m-%d')
    sensor_days = {str(c): len(test[test.target == c][['site', 'local_day']].drop_duplicates()) for c in (0, 1)}
    development = json.loads((output / 'development.json').read_text())
    both_classes = all(set(v) == {'0', '1'} for v in development['class_counts'].values())
    evaluable = both_classes and min(sensor_days.values()) >= 20
    difference = metrics['random_forest']['f1'] - metrics['drying_trend']['f1']
    improvement_met = difference >= .05
    recall_met = metrics['random_forest']['recall'] >= .80
    by_site = {}
    for site, group in test.groupby('site'):
        site_metrics = {kind: scores(group.target.to_numpy(int), group[col].to_numpy(int))
                        for kind, col in [('random_forest', 'rf_prediction'),
                                          ('logistic_regression', 'lr_prediction'),
                                          ('drying_trend', 'baseline_prediction')]}
        site_metrics['always_defer'] = scores(group.target.to_numpy(int), np.zeros(len(group), dtype=int))
        by_site[site] = {'block': group.block.iloc[0], 'examples': len(group),
                         'positive_examples': int((group.target == 1).sum()), 'metrics': site_metrics}
    result = {'status': ('supported' if improvement_met and recall_met else 'failed') if evaluable else 'not_evaluable',
              'evaluation': 'exploratory', 'completed_at_utc': now(), 'threshold_kpa': THRESHOLD,
              'score_cutoff': CUTOFF, 'test_examples': len(test), 'positive_examples': int((test.target == 1).sum()),
              'negative_examples': int((test.target == 0).sum()), 'sensor_days_by_class': sensor_days,
              'development_both_classes': both_classes, 'selected': frozen['selected'],
              'metrics': metrics, 'rf_minus_baseline_f1': difference,
              'descriptive_paired_95pct_interval': bootstrap_interval(test),
              'success_conditions': {'f1_improvement_met': improvement_met, 'recall_met': recall_met,
                                     'minimum_improvement': .05, 'minimum_recall': .80},
              'by_site': by_site, 'source_sha256': prep['source_sha256'],
              'implementation_commit': frozen['implementation_commit'],
              'model_freeze_sha256': sha256(output / 'model_freeze.json')}
    test.to_csv(output / 'test_predictions.csv', index=False)
    save_json(output / 'results.json', result)
    save_json(output / 'artifact_manifest.json', {p.name: sha256(p) for p in output.iterdir()
              if p.is_file() and p.suffix in {'.json', '.csv'} and p.name != 'artifact_manifest.json'})
    print(json.dumps(result, indent=2), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--stage', choices=['prepare', 'develop', 'evaluate', 'all'], default='all')
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to((ROOT / 'results').resolve()):
        parser.error('Recorded results are read-only. Choose an output directory under runs/')
    if args.stage in {'prepare', 'all'} and not args.source.is_file():
        parser.error('Missing dataset. See data/README.md or supply --source PATH')
    with threadpool_limits(limits=2):
        if args.stage in {'prepare', 'all'}:
            prepare(args.source.resolve(), args.output.resolve())
        if args.stage in {'develop', 'all'}:
            if not develop(args.output.resolve()):
                return
        if args.stage in {'evaluate', 'all'}:
            evaluate(args.output.resolve())


if __name__ == '__main__':
    main()
