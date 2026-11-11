"""Audit fixed alternative targets without fitting or selecting a classifier."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd

from .core import H, TZ, ROOT, START, JUNE, JULY, END, ns, scores, save_json, sha256, now
from .episodes import calendar_partition, find_spells, load_audit_inputs

THRESHOLDS = (-100., -200., -300., -400., -500.)
HORIZONS = (6, 12, 24, 48)
FAMILIES = ('new_dry_event', 'future_dry_occurrence', 'future_dry_majority')


def candidate_partition(timestamp, horizon_hours):
    """Apply the strict future-window purge for this candidate's horizon."""
    for left, right, name in ((START, JUNE, 'train'), (JUNE, JULY, 'validation'),
                              (JULY, END, 'test')):
        if left <= timestamp < right:
            return name if timestamp + pd.Timedelta(hours=horizon_hours) < right else 'purged'
    return 'outside'


def future_summary(times, values, anchors, horizon_hours):
    """Describe observed future windows with unchanged raw gap semantics.

    Anchors must be whole UTC hours. Future raw observations are in (t, t+h].
    The matrix contains medians in the corresponding right-closed hourly bins.
    Missing bins remain NaN. No future values are imputed.
    """
    if horizon_hours < 1 or int(horizon_hours) != horizon_hours:
        raise ValueError('Horizon must be a positive integer number of hours')
    anchors_ns = ns(anchors)
    if np.any(anchors_ns % H):
        raise ValueError('Target audit anchors must be whole hours')
    hours = pd.to_datetime(times, utc=True).ceil('h')
    hourly = pd.Series(values, index=hours).groupby(level=0).median()
    grid = anchors_ns[:, None] + np.arange(1, horizon_hours + 1) * H
    medians = hourly.reindex(pd.to_datetime(grid.ravel(), utc=True)).to_numpy().reshape(grid.shape)
    occupied = np.isfinite(medians).sum(axis=1)
    left = np.searchsorted(times, anchors_ns, side='right')
    right = np.searchsorted(times, anchors_ns + horizon_hours * H, side='right')
    minimum = np.full(len(anchors), np.nan)
    gaps = np.full(len(anchors), float(horizon_hours))
    for i, (a, b) in enumerate(zip(left, right)):
        if a == b:
            continue
        minimum[i] = values[a:b].min()
        gaps[i] = max(times[a] - anchors_ns[i],
                      anchors_ns[i] + horizon_hours * H - times[b - 1],
                      np.diff(times[a:b]).max(initial=0)) / H
    return {'medians': medians, 'occupied': occupied, 'minimum_raw': minimum,
            'max_gap_hours': gaps,
            'covered': (occupied >= math.ceil(5 * horizon_hours / 6)) & (gaps <= 2)}


def target_frame(inputs, future, threshold, horizon_hours, family):
    """Create candidate labels and explicit input, coverage, and ambiguity masks."""
    if family not in FAMILIES:
        raise ValueError(f'Unknown target family: {family}')
    frame = inputs.copy()
    partition_column = f'partition_{horizon_hours}'
    frame['partition'] = (frame[partition_column] if partition_column in frame else
                          frame.time.map(lambda t: candidate_partition(t, horizon_hours)))
    frame['current_dry'] = frame.current_potential_kpa <= threshold
    frame['input_eligible'] = frame.forecast_eligible & (
        ~frame.current_dry if family == 'new_dry_event' else True)
    frame['future_covered'] = future['covered']
    if family == 'future_dry_majority':
        dry = (future['medians'] <= threshold).sum(axis=1)
        missing = horizon_hours - future['occupied']
        required = math.ceil(horizon_hours / 2)
        target = np.where(dry >= required, 1., np.where(dry + missing < required, 0., np.nan))
    else:
        target = (future['minimum_raw'] <= threshold).astype(float)
    frame['target'] = np.where(future['covered'], target, np.nan)
    frame['definition_ambiguous'] = future['covered'] & np.isnan(target)
    frame['evaluation_eligible'] = frame.input_eligible & frame.target.notna()
    return frame


def trend_prediction(frame, threshold, horizon_hours, family):
    """Apply a fixed trend reference appropriate to each outcome family."""
    current = frame.current_potential_kpa
    trend = frame.trend_6h_kpa_per_h
    if family == 'future_dry_majority':
        prediction = current + horizon_hours / 2 * trend <= threshold
    else:
        prediction = (trend < 0) & (current + horizon_hours * trend <= threshold)
        if family == 'future_dry_occurrence':
            prediction |= current <= threshold
    return np.asarray(prediction, dtype=int)


def episode_links(inputs, potential, spells, threshold):
    """Locate each hour's first future dry spell and possible onset lead time."""
    lead = np.full(len(inputs), np.nan)
    onset = np.full(len(inputs), -1, dtype=np.int64)
    for site, rows in inputs.groupby('site'):
        times, values = potential[site]
        dry = times[values <= threshold]
        if not len(dry):
            continue
        selected = [spell for spell in spells if spell['site'] == site]
        starts = np.asarray([spell['onset_ns'] for spell in selected], dtype=np.int64)
        confirmed = np.asarray([spell['confirmed'] for spell in selected], dtype=bool)
        anchors = ns(rows.time)
        positions = np.searchsorted(dry, anchors, side='right')
        available = positions < len(dry)
        spell_positions = np.searchsorted(starts, dry[np.minimum(positions, len(dry) - 1)], side='right') - 1
        good = available & (spell_positions >= 0)
        good[good] &= confirmed[spell_positions[good]]
        indices = rows.index.to_numpy()[good]
        onset[indices] = starts[spell_positions[good]]
        lead[indices] = (onset[indices] - anchors[good]) / H
    return onset, lead


def partition_statistics(frame, onset, lead, spells, threshold, horizon, family):
    """Count exclusions and class support, and score fixed simple references."""
    counts, baselines = [], []
    for period in ('train', 'validation', 'test'):
        scheduled = frame[frame.partition == period]
        selected = scheduled[scheduled.evaluation_eligible]
        positive = selected[selected.target == 1]
        negative = selected[selected.target == 0]
        def sensor_days(rows):
            return len(rows.assign(day=pd.DatetimeIndex(rows.time).tz_convert(TZ).strftime('%Y-%m-%d'))[
                ['site', 'day']].drop_duplicates())
        period_spells = [spell for spell in spells if spell['partition'] == period]
        opportunities = positive.index[(lead[positive.index] > 0) & (lead[positive.index] <= horizon)]
        # The strict purge ensures an attributed future onset stays in this period.
        count = {'partition': period, 'scheduled_hours': len(scheduled),
                 'history_missing_hours': int((~scheduled.forecast_eligible).sum()),
                 'currently_dry_history_hours': int((scheduled.forecast_eligible & scheduled.current_dry).sum()),
                 'excluded_currently_dry_hours': int((scheduled.forecast_eligible & ~scheduled.input_eligible).sum()),
                 'input_eligible_hours': int(scheduled.input_eligible.sum()),
                 'future_coverage_missing_hours': int((scheduled.input_eligible & ~scheduled.future_covered).sum()),
                 'definition_ambiguous_hours': int((scheduled.input_eligible & scheduled.definition_ambiguous).sum()),
                 'eligible_hours': len(selected), 'positive_hours': len(positive), 'negative_hours': len(negative),
                 'positive_fraction': len(positive) / len(selected) if len(selected) else None,
                 'positive_sensor_days': sensor_days(positive), 'negative_sensor_days': sensor_days(negative),
                 'positive_locations': positive.site.nunique(), 'negative_locations': negative.site.nunique(),
                 'confirmed_episodes': sum(spell['confirmed'] for spell in period_spells),
                 'uncertain_onsets': sum(not spell['confirmed'] for spell in period_spells),
                 'episodes_with_positive_pre_onset_opportunity': len(set(zip(frame.loc[opportunities, 'site'], onset[opportunities]))),
                 'positive_pre_onset_hours': len(opportunities)}
        rejected = count['history_missing_hours'] + count['excluded_currently_dry_hours']
        rejected += count['future_coverage_missing_hours'] + count['definition_ambiguous_hours']
        if rejected + count['eligible_hours'] != count['scheduled_hours']:
            raise ValueError('Candidate exclusions do not partition the scheduled hours')
        counts.append(count)
        predictions = {'always_defer': np.zeros(len(selected), dtype=int),
                       'always_positive': np.ones(len(selected), dtype=int),
                       'persistence': (selected.current_potential_kpa <= threshold).to_numpy(int),
                       'trend_reference': trend_prediction(selected, threshold, horizon, family)}
        for method, prediction in predictions.items():
            metric = scores(selected.target.to_numpy(int), prediction) if len(selected) else {
                k: None for k in ('f1', 'precision', 'recall', 'tn', 'fp', 'fn', 'tp')}
            baselines.append({'partition': period, 'method': method, **metric})
    return counts, baselines


def plot_training_support(output, candidates):
    """Render training event counts and class fractions without ranking test F1."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), layout='constrained')
    reference = candidates[(candidates.family == 'new_dry_event') & (candidates.horizon_hours == 24)]
    reference = reference.set_index('threshold_kpa').loc[list(THRESHOLDS)]
    x = np.arange(len(THRESHOLDS))
    axes[0, 0].bar(x - .2, reference.train_confirmed_episodes, .4, label='Training')
    axes[0, 0].bar(x + .2, reference.validation_confirmed_episodes, .4, label='Validation')
    axes[0, 0].set(xticks=x, xticklabels=[str(int(t)) for t in THRESHOLDS],
                   xlabel='Threshold (kPa)', ylabel='Observed onsets', title='Six-hour wet reset: observed episodes')
    axes[0, 0].legend()
    for ax, family in zip((axes[0, 1], axes[1, 0], axes[1, 1]), FAMILIES):
        table = candidates[candidates.family == family].pivot(index='horizon_hours', columns='threshold_kpa',
                                                               values='train_positive_fraction')
        values = table.reindex(index=HORIZONS, columns=THRESHOLDS).to_numpy() * 100
        im = ax.imshow(values, vmin=0, vmax=100, cmap='Blues', aspect='auto')
        for i in range(len(HORIZONS)):
            for j in range(len(THRESHOLDS)):
                value = values[i, j]
                ax.text(j, i, f'{value:.1f}%' if np.isfinite(value) else 'N/A', ha='center', va='center',
                        color='white' if value > 60 else 'black', fontsize=8)
        ax.set(xticks=x, xticklabels=[str(int(t)) for t in THRESHOLDS], yticks=np.arange(len(HORIZONS)),
               yticklabels=HORIZONS, xlabel='Threshold (kPa)', ylabel='Horizon (hours)',
               title=family.replace('_', ' ') + ': training positives')
    fig.colorbar(im, ax=[axes[0, 1], axes[1, 0], axes[1, 1]], label='Positive training hours (%)', shrink=.7)
    fig.suptitle('Exploratory target audit: class balance and observed episode support')
    fig.savefig(output / 'training-support.png', dpi=160)
    plt.close(fig)


def audit(folder, output):
    """Write the fixed target matrix using a verified completed local run."""
    folder, output = folder.resolve(), output.resolve()
    if output.is_relative_to(folder) or output.is_relative_to((ROOT / 'results').resolve()):
        raise ValueError('Write target audit to a separate directory under runs/')
    if output.exists():
        raise FileExistsError('Target audit output already exists. Choose a new directory')
    prep, original, potential, inputs, input_hashes = load_audit_inputs(folder)
    columns = ['time', 'site', 'block', 'current_potential_kpa', 'forecast_eligible', 'trend_6h_kpa_per_h']
    inputs = inputs[columns].sort_values(['site', 'time']).reset_index(drop=True)
    future_by_horizon = {}
    for horizon in HORIZONS:
        print(f'Preparing {horizon}-hour observed windows', flush=True)
        parts = [future_summary(*potential[site], rows.time, horizon)
                 for site, rows in inputs.groupby('site', sort=True)]
        future_by_horizon[horizon] = {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}
        inputs[f'partition_{horizon}'] = inputs.time.map(lambda t: candidate_partition(t, horizon))
    all_counts, all_baselines, candidates, spell_inventory = [], [], [], []
    reference_matches = False
    for threshold in THRESHOLDS:
        print(f'Auditing {threshold:g} kPa', flush=True)
        spells = [spell for site, pair in potential.items()
                  for spell in find_spells(site, *pair, threshold=threshold)]
        spell_inventory.extend({'threshold_kpa': threshold, **spell} for spell in spells)
        onset, lead = episode_links(inputs, potential, spells, threshold)
        for horizon in HORIZONS:
            for family in FAMILIES:
                spec = {'candidate': f'{family}__kpa{abs(int(threshold))}__h{horizon}',
                        'family': family, 'threshold_kpa': threshold, 'horizon_hours': horizon}
                frame = target_frame(inputs, future_by_horizon[horizon], threshold, horizon, family)
                counts, baselines = partition_statistics(frame, onset, lead, spells, threshold, horizon, family)
                all_counts.extend({**spec, **row} for row in counts)
                all_baselines.extend({**spec, **row} for row in baselines)
                row = dict(spec)
                for count in counts:
                    period = count['partition']
                    row.update({period + '_' + key: value for key, value in count.items() if key != 'partition'})
                for baseline in baselines:
                    row[baseline['partition'] + '_' + baseline['method'] + '_f1'] = baseline['f1']
                row['meets_original_class_support_rule'] = all(
                    row[period + '_positive_hours'] > 0 and row[period + '_negative_hours'] > 0
                    for period in ('train', 'validation')) and min(
                        row['test_positive_sensor_days'], row['test_negative_sensor_days']) >= 20
                candidates.append(row)
                if threshold == -500 and horizon == 24 and family == 'new_dry_event':
                    for period, expected_positive in (('train', 24), ('validation', 45), ('test', 211)):
                        if row[period + '_positive_hours'] != expected_positive:
                            raise ValueError('The original target does not reproduce its class counts')
                    if row['test_eligible_hours'] != original['test_examples']:
                        raise ValueError('The original target does not reproduce test eligibility')
                    if row['test_trend_reference_f1'] != original['metrics']['drying_trend']['f1']:
                        raise ValueError('The original baseline F1 changed')
                    reference_matches = True
    output.mkdir(parents=True)
    table = pd.DataFrame(candidates)
    table.to_csv(output / 'candidates.csv', index=False)
    pd.DataFrame(all_counts).to_csv(output / 'coverage.csv', index=False)
    pd.DataFrame(all_baselines).to_csv(output / 'baselines.csv', index=False)
    pd.DataFrame(spell_inventory).to_csv(output / 'threshold_spells.csv', index=False)
    plot_training_support(output, table)
    summary = {'analysis': 'exploratory', 'created_at_utc': now(), 'candidate_count': len(table),
               'thresholds_kpa': THRESHOLDS, 'horizons_hours': HORIZONS, 'families': FAMILIES,
               'wet_reset_hours': 6, 'future_occupied_fraction_required': '5/6 rounded up',
               'maximum_gap_hours': 2, 'models_fitted': 0, 'target_adopted': False,
               'original_reference_reproduced': reference_matches,
               'provenance': {'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                    cwd=ROOT, text=True).strip(), 'source_sha256': prep['source_sha256'],
                    'input_hashes': input_hashes, 'code_hashes': {
                        str(p.relative_to(ROOT)): sha256(p) for p in (Path(__file__),
                            ROOT / 'iron_horse/episodes.py', ROOT / 'docs/target-audit-plan.md')}}}
    save_json(output / 'summary.json', summary)
    print(json.dumps({'candidates': len(table), 'models_fitted': 0,
                      'original_reference_reproduced': reference_matches}, indent=2))


def main(argv=None):
    """Run the fixed audit grid against an existing completed local run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/target-audit')
    args = parser.parse_args(argv)
    audit(args.run, args.output)


if __name__ == '__main__':
    main()
