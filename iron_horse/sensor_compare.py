"""Compare observed matric patterns with individual soil and weather channels.

The screens index cases for inspection. They do not identify faults, infer
irrigation, change cleaning rules, or train a model. All timestamps use observed
right-closed hourly bins; missing values remain missing.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from .core import ROOT, GRID, TZ, H, MATRIC, WEATHER, RAW, FLAG, SOIL_RE, WEATHER_FIELDS
from .core import sha256, save_json, now, decode_weather
from .episodes import load_audit_inputs
from .matric import decode_response
from .cc_policy import correct


def observed_runs(mask, minimum):
    """Return inclusive positional runs of observed true values."""
    padded = np.r_[False, np.asarray(mask, dtype=bool), False].astype(int)
    starts = np.flatnonzero(np.diff(padded) == 1)
    ends = np.flatnonzero(np.diff(padded) == -1) - 1
    return [(int(a), int(b)) for a, b in zip(starts, ends) if b - a + 1 >= minimum]


def window_change(series, before, after):
    """Compare medians only when at least half of both windows is observed."""
    pre, post = series.reindex(before).dropna(), series.reindex(after).dropna()
    enough = len(pre) >= math.ceil(len(before) / 2) and len(post) >= math.ceil(len(after) / 2)
    return {'pre_hours': len(pre), 'post_hours': len(post),
            'pre_median': float(pre.median()) if len(pre) else None,
            'post_median': float(post.median()) if len(post) else None,
            'delta': float(post.median() - pre.median()) if enough else None}


def strict_temperature(device, raw):
    """Use only strict Celsius fields, preserving the existing Cc uncertainty."""
    if device == 'SDI-12-LS-US915-2':
        value = correct(raw, 'standard_format')['temperature_c']
        return np.nan if value is None else value
    reading = decode_response(raw)
    return reading.temperature_c if reading else np.nan


def daily_pairs(x, y):
    """Return paired daily deviations for days with at least 18 observed pairs."""
    frame = pd.concat([x.rename('x'), y.rename('y')], axis=1).dropna()
    frame['day'] = pd.DatetimeIndex(frame.index).tz_convert(TZ).strftime('%Y-%m-%d')
    frame = frame[frame.groupby('day').x.transform('count') >= 18].copy()
    frame[['x', 'y']] -= frame.groupby('day')[['x', 'y']].transform('mean')
    return frame


def weather_hourly(raw):
    """Aggregate accepted weather keys; retain conflicts only in raw presence."""
    weather = raw[(raw.device_name == WEATHER) & raw.valid_key]
    values = np.asarray([decode_weather(value) for value in weather.value]).reshape(-1, len(WEATHER_FIELDS))
    frame = pd.DataFrame(values, columns=WEATHER_FIELDS, index=pd.DatetimeIndex(weather.time).ceil('h'))
    return pd.DataFrame({field: (frame[field].groupby(level=0).sum(min_count=1)
                                if field == 'precipitation_mm' else frame[field].groupby(level=0).mean())
                         for field in WEATHER_FIELDS})


def load_channels(folder):
    """Aggregate verified cached observations without revising validity rules."""
    prep, _, potential, _, expected = load_audit_inputs(folder)
    path = folder / 'cache/clean_measurements.parquet'
    expected['cache/clean_measurements.parquet'] = prep['derived_hashes'][path.name]
    if sha256(path) != expected['cache/clean_measurements.parquet']:
        raise ValueError('Cleaned source cache changed')
    metadata_path = ROOT / 'metadata/devices.json'
    if sha256(metadata_path) != prep['implementation_hashes']['metadata/devices.json']:
        raise ValueError('Device routing differs from the completed run')
    metadata = json.loads(metadata_path.read_text())['by_device_name']
    scan = pl.scan_parquet(path)
    hour = (((pl.col('time').cast(pl.Int64) + H - 1) // H) * H).cast(pl.Datetime('ns', 'UTC')).alias('hour')
    print('Counting observed source hours', flush=True)
    raw_counts = scan.with_columns(hour).group_by(['device_name', 'hour']).agg(pl.len().alias('records')).collect()
    raw_presence = raw_counts.to_pandas().pivot(index='hour', columns='device_name', values='records').reindex(GRID).fillna(0).astype(int)
    print('Aggregating individual soil probes with existing flag rules', flush=True)
    bad = scan.filter(pl.col('measurement') == FLAG).with_columns(
        pl.col('value').cast(pl.Float64, strict=False).alias('numeric')).filter(
        ~pl.col('valid_key') | (pl.col('numeric') == 0)).select('device_name', 'time')
    soil = scan.filter(pl.col('measurement').str.contains(SOIL_RE)).with_columns(
        pl.col('value').cast(pl.Float64, strict=False).alias('numeric'))
    soil = soil.filter(pl.col('valid_key') & pl.col('numeric').is_finite()).join(
        bad, on=['device_name', 'time'], how='anti')
    soil_hourly = soil.with_columns(hour).group_by(['device_name', 'measurement', 'hour']).agg(
        pl.col('numeric').median().alias('value'), pl.len().alias('observations')).collect().to_pandas()
    channels, info = {}, {}

    def add(key, series, device, kind, label, unit):
        channels[key] = series.reindex(GRID)
        info[key] = {'device': device, 'kind': kind, 'label': label, 'unit': unit, **metadata[device]}

    for (device, measurement), rows in soil_hourly.groupby(['device_name', 'measurement']):
        water = '_water_' in measurement
        probe = measurement.rsplit('SOIL', 1)[1] or '1'
        add(device + ':' + measurement, rows.set_index('hour').value, device,
            'water' if water else 'soil_temperature', f'{device} p{probe}',
            'reported VWC percent' if water else 'Celsius')
    raw = scan.filter(pl.col('measurement') == RAW).select('device_name', 'time', 'value', 'valid_key').collect().to_pandas()
    for device, (times, values) in potential.items():
        series = pd.Series(values, index=pd.to_datetime(times, utc=True).ceil('h')).groupby(level=0).median()
        add(device + ':potential', series, device, 'potential', device, 'reported kPa')
        part = raw[raw.device_name == device]
        # Temperature comparisons use the same accepted potential timestamps.
        part = part[part.time.isin(pd.to_datetime(times, utc=True))]
        temperatures = [strict_temperature(device, value) for value in part.value]
        series = pd.Series(temperatures, index=pd.DatetimeIndex(part.time).ceil('h')).groupby(level=0).median()
        add(device + ':temperature', series, device, 'matric_temperature', device + ' internal T', 'Celsius')
    print('Decoding observed hourly weather', flush=True)
    weather_frame = weather_hourly(raw)
    for field in WEATHER_FIELDS:
        add(WEATHER + ':' + field, weather_frame[field], WEATHER, field, field.replace('_', ' '),
            'mm per observed hour' if field == 'precipitation_mm' else 'reported weather units')
    return pd.DataFrame(channels, index=GRID), info, raw_presence, prep, expected


def screen_cases(hourly, info):
    """Index all large-jump groups and long near-zero runs for inspection."""
    cases = []
    for device in MATRIC:
        series = hourly[device + ':potential']
        block = info[device + ':potential']['block']
        change = series.diff()
        for direction in ('up', 'down'):
            flagged = change[(change >= 100) if direction == 'up' else (change <= -100)]
            group = (flagged.index.to_series().diff() > pd.Timedelta(hours=6)).cumsum()
            for number, (_, rows) in enumerate(flagged.groupby(group), 1):
                center = rows.abs().idxmax()
                cases.append({'case_id': f'{device}_jump_{direction}_{number:03d}', 'device': device,
                    'block': block, 'kind': 'jump_' + direction, 'start': rows.index.min(),
                    'end': rows.index.max(), 'center': center, 'flagged_hours': len(rows),
                    'jump_kpa': float(change.loc[center]),
                    'prior_potential': float(series.loc[center - pd.Timedelta(hours=1)]),
                    'center_potential': float(series.loc[center])})
        for number, (a, b) in enumerate(observed_runs(series.notna() & (series.abs() <= 1), 12), 1):
            cases.append({'case_id': f'{device}_near_zero_{number:03d}', 'device': device,
                'block': block, 'kind': 'near_zero', 'start': series.index[a], 'end': series.index[b],
                'center': series.index[a], 'flagged_hours': b - a + 1, 'jump_kpa': None,
                'prior_potential': float(series.iloc[a - 1]) if a and pd.notna(series.iloc[a - 1]) else None,
                'center_potential': float(series.iloc[a])})
    return pd.DataFrame(cases)


def compare_cases(cases, hourly, info):
    """Describe each channel and its observed coverage around each screened case."""
    rows, summaries = [], []
    rain = hourly[WEATHER + ':precipitation_mm']
    for case in cases.to_dict(orient='records'):
        t = case['center']
        if case['kind'] == 'near_zero':
            windows = [('last_vs_first_6h', pd.date_range(case['start'], periods=6, freq='h'),
                        pd.date_range(case['end'] - pd.Timedelta(hours=5), periods=6, freq='h'))]
            rain_index = pd.date_range(case['start'], case['end'], freq='h')
        else:
            before = pd.date_range(t - pd.Timedelta(hours=6), periods=6, freq='h')
            windows = [('post6_vs_pre6', before, pd.date_range(t, periods=6, freq='h')),
                       ('post24_vs_pre6', before, pd.date_range(t, periods=24, freq='h'))]
            rain_index = pd.date_range(t - pd.Timedelta(hours=6), periods=30, freq='h')
        own = info[case['device'] + ':potential']
        relevant = [key for key, m in info.items() if (
            m['block'] == case['block'] and m['kind'] in {'water', 'soil_temperature'}) or
            (m['device'] == case['device'] and m['kind'] == 'matric_temperature') or
            m['kind'] == 'air_temperature_c']
        for comparison, before, after in windows:
            for key in relevant:
                m = info[key]
                rows.append({'case_id': case['case_id'], 'comparison': comparison, 'channel': key,
                    'kind': m['kind'], 'device': m['device'], 'block': m['block'], 'slope': m['slope'],
                    'same_terrain': m['slope'] is not None and m['slope'] == own['slope'],
                    'unit': m['unit'], **window_change(hourly[key], before, after)})
        observed = rain.reindex(rain_index).dropna()
        response = [r for r in rows if r['case_id'] == case['case_id'] and r['kind'] == 'water' and
                    r['comparison'] == windows[-1][0] and r['delta'] is not None]
        other_jumps = [device for device in MATRIC if device != case['device'] and
            (hourly[device + ':potential'].diff().loc[t - pd.Timedelta(hours=1):t + pd.Timedelta(hours=1)].abs() >= 100).any()]
        summaries.append({'case_id': case['case_id'], 'rain_expected_bins': len(rain_index),
            'rain_observed_bins': len(observed), 'rain_recorded_mm': float(observed.sum()) if len(observed) else None,
            'paired_water_channels': len(response), 'water_channels_increasing': sum(r['delta'] > 0 for r in response),
            'water_channels_rise_at_least_1_reported_point': sum(r['delta'] >= 1 for r in response),
            'matched_terrain_water_channels': sum(r['same_terrain'] for r in response),
            'other_large_jump_devices_within_1h': ','.join(other_jumps)})
    return pd.DataFrame(rows), pd.DataFrame(summaries)


def gap_table(raw_presence, hourly):
    """Compare common matric raw-response gaps with other selected devices."""
    nonempty = {device: raw_presence.index[raw_presence[device] > 0] for device in MATRIC}
    start = max(index.min() for index in nonempty.values())
    end = min(index.max() for index in nonempty.values())
    absent = (raw_presence[MATRIC].sum(axis=1) == 0) & (raw_presence.index >= start) & (raw_presence.index <= end)
    records = []
    soil = [name for name in raw_presence if name.startswith(('SE01-', 'SE0X-'))]
    for a, b in observed_runs(absent, 6):
        frame = raw_presence.iloc[a:b + 1]
        records.append({'start': frame.index[0], 'end': frame.index[-1], 'hours': len(frame),
            'weather_raw_hours': int((frame[WEATHER] > 0).sum()),
            'weather_rain_observed_hours': int(hourly.loc[frame.index, WEATHER + ':precipitation_mm'].notna().sum()),
            'any_soil_raw_hours': int((frame[soil].sum(axis=1) > 0).sum()),
            'all_selected_devices_absent_hours': int((frame.sum(axis=1) == 0).sum())})
    return pd.DataFrame(records)


def temperature_associations(hourly, info):
    """Describe monthly daily-centered temperature associations, without causal tests."""
    rows = []
    for site in MATRIC:
        potential = hourly[site + ':potential']
        block = info[site + ':potential']['block']
        keys = [key for key, m in info.items() if (m['device'] == site and m['kind'] == 'matric_temperature') or
                (m['block'] == block and m['kind'] == 'soil_temperature') or m['kind'] == 'air_temperature_c']
        for key in keys:
            for month in range(1, 9):
                subset = pd.DatetimeIndex(hourly.index).tz_convert(TZ).month == month
                paired = daily_pairs(potential[subset], hourly.loc[subset, key])
                enough = len(paired) and paired.day.nunique() >= 3
                varying = enough and np.ptp(paired.x) > 0 and np.ptp(paired.y) > 0
                rows.append({'device': site, 'block': block, 'month': f'2026-{month:02d}',
                    'temperature_channel': key, 'kind': info[key]['kind'], 'slope': info[key]['slope'],
                    'paired_hours': len(paired), 'paired_days': paired.day.nunique(),
                    'daily_centered_correlation': float(paired.x.corr(paired.y)) if varying else None})
    return pd.DataFrame(rows)


def plot_evidence(output, cases, hourly, info, raw_presence, case_summary):
    """Draw availability and fixed representative cases with unfilled gaps."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    selected = []
    for device in MATRIC:
        group = cases[(cases.device == device) & (cases.kind == 'jump_up')]
        if len(group): selected.append(group.jump_kpa.idxmax())
    group = cases[cases.kind == 'jump_down']
    if len(group): selected.append(group.jump_kpa.idxmin())
    group = cases[cases.kind == 'near_zero']
    if len(group): selected.append(group.flagged_hours.idxmax())
    # Extra descriptive contrast, selected after the first response table.
    # It illustrates corroboration rather than selecting a model or cleaning rule.
    group = cases[cases.kind == 'jump_up'].merge(case_summary, on='case_id')
    if len(group) and group.water_channels_rise_at_least_1_reported_point.max() > 0:
        contrast = group.loc[group.water_channels_rise_at_least_1_reported_point.idxmax(), 'case_id']
        selected.append(cases.index[cases.case_id == contrast][0])
    selected = list(dict.fromkeys(selected))
    for index in selected:
        case = cases.loc[index]
        start = case.start - pd.Timedelta(hours=24)
        end = case.end + pd.Timedelta(hours=24) if case.kind == 'near_zero' else case.center + pd.Timedelta(hours=48)
        piece = hourly.loc[start:end]
        fig, axes = plt.subplots(4, 1, figsize=(12, 9), sharex=True, layout='constrained')
        axes[0].plot(piece.index.tz_convert(TZ), piece[case.device + ':potential'], label='Matric median')
        axes[0].set_ylabel('reported kPa')
        for key, m in info.items():
            if m['block'] != case.block or m['kind'] not in {'water', 'soil_temperature'}: continue
            ax = axes[1] if m['kind'] == 'water' else axes[2]
            ax.plot(piece.index.tz_convert(TZ), piece[key], lw=1, label=m['label'] + ' ' + str(m['slope']))
        axes[1].set_ylabel('reported VWC %')
        axes[2].plot(piece.index.tz_convert(TZ), piece[case.device + ':temperature'], color='black', lw=1.2, label='Matric internal T (strict)')
        axes[2].plot(piece.index.tz_convert(TZ), piece[WEATHER + ':air_temperature_c'], color='gray', alpha=.6, label='Station I air T')
        axes[2].set_ylabel('temperature C')
        axes[3].bar(piece.index.tz_convert(TZ), piece[WEATHER + ':precipitation_mm'], width=.03, label='Observed hourly rain at I')
        axes[3].set_ylabel('rain mm')
        for ax in axes:
            ax.axvline(case.center.tz_convert(TZ), color='red', ls='--', lw=.8)
            ax.grid(alpha=.2)
            ax.legend(loc='best', fontsize=6)
        fig.suptitle(f'{case.block}: {case.kind}; {case.center.tz_convert(TZ):%Y-%m-%d %H:%M}\nSame block does not establish identical placement or depth. Gaps are unfilled.')
        fig.savefig(output / (case.case_id + '.png'), dpi=130)
        plt.close(fig)
    availability, labels = [], []
    for device in raw_presence:
        availability.append((raw_presence[device] > 0).to_numpy());labels.append(device + ' raw')
        keys = [key for key, m in info.items() if m['device'] == device and m['kind'] != 'matric_temperature']
        availability.append(hourly[keys].notna().any(axis=1).to_numpy());labels.append(device + ' accepted fields')
    fig, ax = plt.subplots(figsize=(13, 8), layout='constrained')
    ax.imshow(np.asarray(availability), cmap='Blues', vmin=0, vmax=1, aspect='auto', interpolation='nearest')
    ax.set(yticks=np.arange(len(labels)), yticklabels=labels)
    ticks = [i for i, t in enumerate(GRID.tz_convert(TZ)) if t.day == 1 and t.hour == 0]
    ax.set(xticks=ticks, xticklabels=[GRID[i].tz_convert(TZ).strftime('%b %d') for i in ticks])
    ax.set_title('Selected-source hourly availability: blue observed, white absent/unaccepted\nRows distinguish raw records from accepted diagnostic fields')
    ax.tick_params(axis='y', labelsize=7)
    fig.savefig(output / 'availability.png', dpi=140);plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), layout='constrained')
    august = GRID.tz_convert(TZ).month == 8
    for ax, device in zip(axes.ravel(), MATRIC):
        key = device + ':temperature'
        paired = daily_pairs(hourly.loc[august, device + ':potential'], hourly.loc[august, key])
        if paired.day.nunique() < 3:
            key = WEATHER + ':air_temperature_c'
            paired = daily_pairs(hourly.loc[august, device + ':potential'], hourly.loc[august, key])
        if len(paired):
            ax.scatter(paired.y, paired.x, s=5, alpha=.35)
        ax.set(xlabel=info[key]['label'] + ' daily deviation (C)', ylabel='Potential daily deviation (kPa)',
               title=f"{info[device + ':potential']['block']}: {paired.day.nunique()} paired days")
        ax.grid(alpha=.2)
    fig.suptitle('August paired daily deviations: descriptive association, not causation\nInternal temperature when available; otherwise station I air temperature')
    fig.savefig(output / 'august-temperature.png', dpi=140);plt.close(fig)
    return [cases.loc[i, 'case_id'] for i in selected]


def analyze(folder, output):
    """Write new descriptive evidence while leaving all source runs unchanged."""
    folder, output = folder.resolve(), output.resolve()
    if output.is_relative_to(folder) or output.is_relative_to((ROOT / 'results').resolve()):
        raise ValueError('Use a separate output directory under runs/')
    if output.exists(): raise FileExistsError('Comparison output exists. Choose a new directory')
    hourly, info, raw_presence, prep, expected = load_channels(folder)
    cases = screen_cases(hourly, info)
    responses, case_summary = compare_cases(cases, hourly, info)
    gaps = gap_table(raw_presence, hourly)
    temperatures = temperature_associations(hourly, info)
    coverage = []
    for key, m in info.items():
        for month in range(1, 9):
            subset = GRID.tz_convert(TZ).month == month
            values = hourly.loc[subset, key].dropna()
            coverage.append({'channel': key, **m, 'month': f'2026-{month:02d}',
                'scheduled_hours': int(subset.sum()), 'observed_hours': len(values),
                'raw_device_hours': int((raw_presence.loc[subset, m['device']] > 0).sum()),
                'minimum': float(values.min()) if len(values) else None,
                'maximum': float(values.max()) if len(values) else None,
                'near_zero_hours': int((values.abs() <= 1).sum()) if m['kind'] == 'potential' else None})
    output.mkdir(parents=True)
    hourly.to_parquet(output / 'hourly_diagnostics.parquet')
    raw_presence.to_parquet(output / 'raw_hourly_counts.parquet')
    cases.to_csv(output / 'cases.csv', index=False)
    responses.to_csv(output / 'channel_responses.csv', index=False)
    case_summary.to_csv(output / 'case_summary.csv', index=False)
    gaps.to_csv(output / 'common_gaps.csv', index=False)
    temperatures.to_csv(output / 'temperature_associations.csv', index=False)
    pd.DataFrame(coverage).to_csv(output / 'channel_coverage.csv', index=False)
    plots = plot_evidence(output, cases, hourly, info, raw_presence, case_summary)
    summary = {'analysis': 'exploratory sensor comparison', 'created_at_utc': now(),
        'models_fitted': 0, 'cleaning_rules_adopted': False, 'source_sha256': prep['source_sha256'],
        'input_hashes': expected, 'analysis_code_sha256': sha256(Path(__file__)),
        'plan_sha256': sha256(ROOT / 'docs/sensor-comparison-plan.md'), 'channel_metadata': info,
        'case_counts': cases.groupby(['block', 'kind']).size().to_dict(), 'plotted_cases': plots,
        'additional_plot_selection': 'After the first table, add the upward case with most soil-water rises of at least one reported point.'}
    # Tuple keys are explicit records in the saved JSON.
    summary['case_counts'] = [{'block': block, 'kind': kind, 'count': int(count)}
                             for (block, kind), count in summary['case_counts'].items()]
    save_json(output / 'summary.json', summary)
    print(json.dumps({'case_counts': summary['case_counts'], 'common_gaps': len(gaps), 'plots': plots}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'runs/sensor-comparison')
    args = parser.parse_args()
    analyze(args.run, args.output)
