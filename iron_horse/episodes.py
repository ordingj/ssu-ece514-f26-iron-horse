"""Audit observed drying episodes and warning times without refitting models.

An episode needs consecutive observed wet hours before its first dry reading.
One-hour, six-hour, and 24-hour wet resets describe definition sensitivity.
The registered hourly targets, partitions, predictions, and metrics stay fixed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

import joblib
import numpy as np
import pandas as pd

from .core import H, TZ, ROOT, START, JUNE, JULY, END, ns, sha256, save_json, now
from .checkpoint import THRESHOLD, baseline, label_partition

METHODS = {'drying_trend': 'baseline_prediction', 'random_forest': 'rf_prediction',
           'logistic_regression': 'lr_prediction', 'always_defer': None}


def calendar_partition(timestamp):
    """Assign an onset to a calendar period without applying forecast purges."""
    if START <= timestamp < JUNE:
        return 'train'
    if JUNE <= timestamp < JULY:
        return 'validation'
    if JULY <= timestamp < END:
        return 'test'
    return 'outside'


def find_spells(site, times, values, wet_reset_hours=6, *, threshold=THRESHOLD):
    """Group dry readings, keeping onsets without observed wet recovery uncertain.

    Arrays must contain sorted, unique timestamps in UTC nanoseconds and finite
    decoded potentials. Bins are right-closed UTC hours. A wet bin contains at
    least one reading and no value at or below the threshold. A raw observation
    gap above two hours censors the current spell and resets the wet history.
    """
    if wet_reset_hours < 1:
        raise ValueError('Wet reset hours must be positive')
    times = np.asarray(times, dtype=np.int64)
    values = np.asarray(values, dtype=float)
    if len(times) != len(values) or not np.isfinite(values).all():
        raise ValueError('Episode inputs must be finite, paired observations')
    if len(times) > 1 and not np.all(np.diff(times) > 0):
        raise ValueError('Episode timestamps must be unique and increasing')
    bins = (times + H - 1) // H
    edges = np.r_[0, np.flatnonzero(np.diff(bins)) + 1, len(times)]
    spells, active = [], None
    wet_hours, previous_bin, previous_time = 0, None, None

    def close(reason, end):
        nonlocal active
        if active is not None:
            active.update(end_reason=reason, end_ns=int(end))
            spells.append(active)
            active = None

    for left, right in zip(edges[:-1], edges[1:]):
        if left == right:
            continue
        hour = int(bins[left])
        if previous_time is not None and times[left] - previous_time > 2 * H:
            close('observation_gap', previous_time)
            wet_hours = 0
        if previous_bin is not None and hour != previous_bin + 1:
            wet_hours = 0
        dry = values[left:right] <= threshold
        if dry.any():
            indices = np.flatnonzero(dry) + left
            if active is None:
                onset = int(times[indices[0]])
                active = {'episode_id': f'{site}:{len(spells) + 1:04d}', 'site': site,
                          'onset_ns': onset, 'confirmed': wet_hours >= wet_reset_hours,
                          'partition': calendar_partition(pd.Timestamp(onset, tz='UTC')),
                          'minimum_kpa': float(values[indices].min()), 'dry_readings': 0}
            active['last_dry_ns'] = int(times[indices[-1]])
            active['minimum_kpa'] = min(active['minimum_kpa'], float(values[indices].min()))
            active['dry_readings'] += len(indices)
            wet_hours = 0
        else:
            wet_hours += 1
            if wet_hours >= wet_reset_hours:
                close('wet_reset', hour * H)
        previous_bin, previous_time = hour, int(times[right - 1])
    if previous_time is not None:
        close('study_end', previous_time)
    return spells


def associate_positive_hours(forecasts, potential, spells):
    """Assign each positive hour to the spell of its first future dry reading.

    This prevents one forecast from receiving credit for multiple future
    episodes. Negative lead times identify forecasts during an existing spell.
    The caller supplies only examples passing the registered eligibility rules.
    """
    result = forecasts[forecasts.target == 1].copy()
    result['episode_id'] = ''
    result['episode_confirmed'] = False
    result['lead_hours'] = np.nan
    for site, rows in result.groupby('site'):
        times, values = potential[site]
        dry_times = times[values <= THRESHOLD]
        candidates = [spell for spell in spells if spell['site'] == site]
        onsets = np.array([spell['onset_ns'] for spell in candidates], dtype=np.int64)
        for index, row in rows.iterrows():
            anchor = pd.Timestamp(row.time).value
            position = np.searchsorted(dry_times, anchor, side='right')
            if position == len(dry_times) or dry_times[position] > anchor + 24 * H:
                raise ValueError('A positive hour has no dry reading in its target window')
            dry_time = dry_times[position]
            spell_index = np.searchsorted(onsets, dry_time, side='right') - 1
            if spell_index < 0 or dry_time > candidates[spell_index]['last_dry_ns']:
                raise ValueError('A positive hour could not be assigned to a dry spell')
            spell = candidates[spell_index]
            result.loc[index, 'episode_id'] = spell['episode_id']
            result.loc[index, 'episode_confirmed'] = spell['confirmed']
            result.loc[index, 'lead_hours'] = (spell['onset_ns'] - anchor) / H
    return result


def warning_rows(spells, positive_hours):
    """Describe baseline warnings in all periods and frozen-model test warnings.

    An episode stays in the table even if it has no scored pre-onset opportunity.
    Model warnings use only original test predictions issued before onset.
    Earliest and latest describe issue time, so earliest has the largest lead.
    """
    records = []
    for spell in spells:
        if not spell['confirmed'] or spell['partition'] == 'outside':
            continue
        eligible = positive_hours[(positive_hours.episode_id == spell['episode_id']) &
                                  (positive_hours.partition == spell['partition']) &
                                  (positive_hours.lead_hours > 0) &
                                  (positive_hours.lead_hours <= 24)]
        for method, column in METHODS.items():
            if spell['partition'] != 'test' and method in {'random_forest', 'logistic_regression'}:
                continue
            warnings = eligible[eligible[column] == 1] if column else eligible.iloc[:0]
            records.append({'episode_id': spell['episode_id'], 'site': spell['site'],
                            'partition': spell['partition'],
                            'onset_local': pd.Timestamp(spell['onset_ns'], tz='UTC').tz_convert(TZ).isoformat(),
                            'method': method, 'scored_pre_onset_hours': len(eligible),
                            'detected': len(warnings) > 0, 'warning_hours': len(warnings),
                            'earliest_warning_lead_hours': float(warnings.lead_hours.max()) if len(warnings) else None,
                            'latest_warning_lead_hours': float(warnings.lead_hours.min()) if len(warnings) else None})
    return records


def summarize(spells, assigned, warnings):
    """Count confirmed and uncertain onsets separately from hourly examples."""
    periods = {}
    for period in ('train', 'validation', 'test'):
        selected = [spell for spell in spells if spell['partition'] == period]
        positive = assigned[assigned.partition == period]
        periods[period] = {
            'confirmed_episodes': sum(spell['confirmed'] for spell in selected),
            'uncertain_onsets': sum(not spell['confirmed'] for spell in selected),
            'positive_hours': len(positive),
            'positive_hours_before_confirmed_onset': int((positive.episode_confirmed &
                                                        (positive.lead_hours > 0)).sum()),
            'positive_hours_during_confirmed_spell': int((positive.episode_confirmed &
                                                        (positive.lead_hours <= 0)).sum()),
            'positive_hours_with_uncertain_onset': int((~positive.episode_confirmed).sum())}
    methods = {}
    for method in METHODS:
        rows = [row for row in warnings if row['method'] == method and row['partition'] == 'test']
        detected = [row for row in rows if row['detected']]
        leads = [row['earliest_warning_lead_hours'] for row in detected]
        methods[method] = {'observed_episodes': len(rows),
                           'episodes_with_scored_warning_opportunity': sum(row['scored_pre_onset_hours'] > 0 for row in rows),
                           'detected_episodes': len(detected),
                           'median_earliest_warning_lead_hours': float(np.median(leads)) if leads else None,
                           'minimum_earliest_warning_lead_hours': min(leads) if leads else None,
                           'maximum_earliest_warning_lead_hours': max(leads) if leads else None}
    return {'partitions': periods, 'test_methods': methods}


def load_audit_inputs(folder):
    """Verify input hashes before loading a trusted local run for an audit."""
    folder = Path(folder).resolve()
    prep = json.loads((folder / 'preparation.json').read_text())
    artifacts = json.loads((folder / 'artifact_manifest.json').read_text())
    expected = {'cache/' + name: prep['derived_hashes'][name]
                for name in ('potential.joblib', 'hourly_inputs.parquet')}
    expected.update({name: artifacts[name] for name in
                     ('preparation.json', 'results.json', 'test_predictions.csv', 'development.json')})
    for name, digest in expected.items():
        if sha256(folder / name) != digest:
            raise ValueError(f'Input hash mismatch: {name}')
    potential = joblib.load(folder / 'cache/potential.joblib')
    inputs = pd.read_parquet(folder / 'cache/hourly_inputs.parquet')
    result = json.loads((folder / 'results.json').read_text())
    return prep, result, potential, inputs, expected


def analyze(folder, output):
    """Verify saved inputs and write a new episode audit without modifying the run."""
    folder, output = folder.resolve(), output.resolve()
    if output.is_relative_to((ROOT / 'results').resolve()) or output.is_relative_to(folder):
        raise ValueError('Write episode analysis to a separate directory under runs/')
    if output.exists():
        raise FileExistsError('Episode output already exists. Choose a new directory')
    prep, result, potential, inputs, expected = load_audit_inputs(folder)
    labeled = label_partition(inputs, potential, ['train', 'validation', 'test'])
    eligible = labeled[labeled.evaluation_eligible].copy()
    predictions = pd.read_csv(folder / 'test_predictions.csv')
    predictions['time'] = pd.to_datetime(predictions.time, utc=True)
    join = ['time', 'site']
    original_test = eligible[eligible.partition == 'test'][join + ['target']].sort_values(join).reset_index(drop=True)
    saved_test = predictions[join + ['target']].sort_values(join).reset_index(drop=True)
    pd.testing.assert_frame_equal(original_test, saved_test, check_dtype=False)
    development = json.loads((folder / 'development.json').read_text())
    for period in ('train', 'validation'):
        frame = eligible[eligible.partition == period]
        counts = {str(int(k)): int(v) for k, v in frame.target.value_counts().items()}
        if counts != development['class_counts'][period]:
            raise ValueError('Replayed development labels differ from the checkpoint')
    eligible['baseline_prediction'] = baseline(eligible)
    eligible = eligible.merge(predictions[join + ['rf_prediction', 'lr_prediction']],
                              on=join, how='left', validate='one_to_one')
    blocks = inputs.groupby('site').block.first().to_dict()
    sensitivity = {}
    for reset in (1, 6, 24):
        spells = [spell for site, (times, values) in potential.items()
                  for spell in find_spells(site, times, values, reset)]
        assigned = associate_positive_hours(eligible, potential, spells)
        warnings = warning_rows(spells, assigned)
        sensitivity[str(reset)] = summarize(spells, assigned, warnings)
        if reset == 6:
            primary_spells, primary_assigned, primary_warnings = spells, assigned, warnings
    output.mkdir(parents=True)
    spells = pd.DataFrame(primary_spells)
    spells['block'] = spells.site.map(blocks)
    for column in ('onset', 'last_dry', 'end'):
        spells[column + '_local'] = pd.to_datetime(spells[column + '_ns'], utc=True).dt.tz_convert(TZ)
    counts = primary_assigned.groupby(['episode_id', 'partition']).size().unstack(fill_value=0)
    for period in ('train', 'validation', 'test'):
        spells[period + '_positive_hours'] = spells.episode_id.map(counts.get(period, pd.Series(dtype=int))).fillna(0).astype(int)
    spells.to_csv(output / 'drying_spells.csv', index=False)
    spells[spells.confirmed].to_csv(output / 'episodes.csv', index=False)
    pd.DataFrame(primary_warnings).to_csv(output / 'episode_warnings.csv', index=False)
    primary_assigned[['time', 'site', 'partition', 'episode_id', 'episode_confirmed',
                      'lead_hours']].to_csv(output / 'positive_hour_attribution.csv', index=False)
    summary = {'analysis': 'exploratory', 'created_at_utc': now(), 'wet_reset_hours': 6,
               'threshold_kpa': THRESHOLD, 'maximum_observation_gap_hours': 2,
               'primary': sensitivity['6'], 'sensitivity_by_wet_reset_hours': sensitivity,
               'original_hourly_metrics': result['metrics'],
               'original_test_examples': result['test_examples'],
               'original_positive_test_hours': result['positive_examples'],
               'original_hypothesis_status': result['status'],
               'provenance': {'base_commit': subprocess.check_output(
                   ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                   'analysis_code_sha256': sha256(Path(__file__)),
                   'source_sha256': prep['source_sha256'], 'input_hashes': expected}}
    save_json(output / 'summary.json', summary)
    print(json.dumps(summary['primary'], indent=2))


def main(argv=None):
    """Run the episode audit from a trusted, complete local checkpoint run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/episodes')
    args = parser.parse_args(argv)
    analyze(args.run, args.output)


if __name__ == '__main__':
    main()
