"""Recount sensor-comparison evidence and spot-check hourly aggregates from raw cache.

Use the pinned environment and trusted local completed-run caches. This checker
does not import the comparison kernels or modify source data. The existing
weather decoder is reused only to check its new hourly aggregation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from iron_horse.core import decode_weather, WEATHER_FIELDS

H = 3_600_000_000_000
TZ = 'America/Los_Angeles'
FLAG = 'device_frmpayload_data_s_flag'


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def equal(actual, expected):
    if expected is None:
        assert pd.isna(actual), (actual, expected)
    else:
        assert abs(actual - expected) < 1e-10, (actual, expected)


def verify(run, audit, receipt):
    if receipt.exists():
        raise FileExistsError('Receipt exists. Choose a new --receipt path')
    summary = json.loads((audit / 'summary.json').read_text())
    for name, expected in summary['input_hashes'].items():
        assert file_hash(run / name) == expected, name
    hourly = pd.read_parquet(audit / 'hourly_diagnostics.parquet')
    cases = pd.read_csv(audit / 'cases.csv')
    for key in ('start', 'end', 'center'):
        cases[key] = pd.to_datetime(cases[key], utc=True)
    responses = pd.read_csv(audit / 'channel_responses.csv')
    potential_inputs = pd.read_parquet(run / 'cache/hourly_inputs.parquet')
    for site, frame in potential_inputs.groupby('site'):
        expected = frame.set_index('time').current_potential_kpa.reindex(hourly.index)
        np.testing.assert_allclose(hourly[site + ':potential'], expected, equal_nan=True)
    # Rebuild case boundaries from the frozen hourly values with a sequential walk.
    expected_cases = []
    for site in potential_inputs.site.unique():
        series = hourly[site + ':potential']
        changes = series.diff()
        for direction, sign in [('up', 1), ('down', -1)]:
            groups = []
            for time, change in changes.items():
                if not pd.notna(change) or sign * change < 100: continue
                if not groups or time - groups[-1][-1] > pd.Timedelta(hours=6):
                    groups.append([])
                groups[-1].append(time)
            for number, group in enumerate(groups, 1):
                center = max(group, key=lambda t: abs(changes[t]))
                expected_cases.append((f'{site}_jump_{direction}_{number:03d}', group[0], group[-1], center, len(group)))
        start, number = None, 0
        for position in range(len(series) + 1):
            near = position < len(series) and pd.notna(series.iloc[position]) and abs(series.iloc[position]) <= 1
            if near and start is None: start = position
            if not near and start is not None:
                if position - start >= 12:
                    number += 1
                    expected_cases.append((f'{site}_near_zero_{number:03d}', series.index[start],
                                           series.index[position - 1], series.index[start], position - start))
                start = None
    actual_cases = list(cases[['case_id', 'start', 'end', 'center', 'flagged_hours']].itertuples(index=False, name=None))
    assert sorted(actual_cases) == sorted(expected_cases)
    for row in responses.itertuples():
        case = cases[cases.case_id == row.case_id].iloc[0]
        if row.comparison == 'last_vs_first_6h':
            before = (hourly.index >= case.start) & (hourly.index < case.start + pd.Timedelta(hours=6))
            after = (hourly.index > case.end - pd.Timedelta(hours=6)) & (hourly.index <= case.end)
            post_length = 6
        else:
            post_length = 6 if row.comparison == 'post6_vs_pre6' else 24
            before = (hourly.index >= case.center - pd.Timedelta(hours=6)) & (hourly.index < case.center)
            after = (hourly.index >= case.center) & (hourly.index < case.center + pd.Timedelta(hours=post_length))
        a = hourly.loc[before, row.channel].dropna().to_numpy()
        b = hourly.loc[after, row.channel].dropna().to_numpy()
        assert row.pre_hours == len(a) and row.post_hours == len(b)
        equal(row.pre_median, float(np.median(a)) if len(a) else None)
        equal(row.post_median, float(np.median(b)) if len(b) else None)
        enough = len(a) >= 3 and len(b) >= post_length / 2
        equal(row.delta, float(np.median(b) - np.median(a)) if enough else None)
    correlations = pd.read_csv(audit / 'temperature_associations.csv')
    for row in correlations.itertuples():
        mask = hourly.index.tz_convert(TZ).strftime('%Y-%m') == row.month
        pairs = hourly.loc[mask, [row.device + ':potential', row.temperature_channel]].dropna()
        x, y, days = [], [], 0
        for _, group in pairs.groupby(pairs.index.tz_convert(TZ).date):
            if len(group) < 18: continue
            a, b = group.iloc[:, 0].to_numpy(), group.iloc[:, 1].to_numpy()
            x.extend(a - a.mean());y.extend(b - b.mean());days += 1
        assert row.paired_hours == len(x) and row.paired_days == days
        x, y = np.asarray(x), np.asarray(y)
        varying = days >= 3 and np.ptp(x) > 0 and np.ptp(y) > 0
        expected = float(np.corrcoef(x, y)[0, 1]) if varying else None
        equal(row.daily_centered_correlation, expected)
    case_summary = pd.read_csv(audit / 'case_summary.csv')
    rain = hourly['SDI-12-LS-US915-3:precipitation_mm']
    for row in case_summary.itertuples():
        case = cases[cases.case_id == row.case_id].iloc[0]
        left = case.start if case.kind == 'near_zero' else case.center - pd.Timedelta(hours=6)
        right = case.end if case.kind == 'near_zero' else case.center + pd.Timedelta(hours=23)
        values = rain.loc[left:right]
        assert row.rain_expected_bins == len(values) and row.rain_observed_bins == values.notna().sum()
        equal(row.rain_recorded_mm, float(values.sum()) if values.notna().any() else None)
        comparison = 'last_vs_first_6h' if case.kind == 'near_zero' else 'post24_vs_pre6'
        water = responses[(responses.case_id == row.case_id) & (responses.kind == 'water') &
                          (responses.comparison == comparison) & responses.delta.notna()]
        assert row.paired_water_channels == len(water)
        assert row.water_channels_increasing == (water.delta > 0).sum()
        assert row.water_channels_rise_at_least_1_reported_point == (water.delta >= 1).sum()
        assert row.matched_terrain_water_channels == water.same_terrain.sum()
    source = pl.scan_parquet(run / 'cache/clean_measurements.parquet')
    gaps = pd.read_csv(audit / 'common_gaps.csv')
    for row in gaps.itertuples():
        left = pd.Timestamp(row.start) - pd.Timedelta(hours=1)
        right = pd.Timestamp(row.end)
        count = source.filter((pl.col('time') > left.to_pydatetime()) &
                              (pl.col('time') <= right.to_pydatetime())).select(pl.len()).collect().item()
        assert count == 0
        assert row.all_selected_devices_absent_hours == row.hours
    # Inspect first, middle, and last observed hour for every individual soil channel.
    checks = []
    for key, m in summary['channel_metadata'].items():
        if m['kind'] not in {'water', 'soil_temperature'}: continue
        valid = hourly[key].dropna()
        for position in sorted({0, len(valid) // 2, len(valid) - 1}):
            if not len(valid): continue
            checks.append({'device_name': m['device'], 'hour': valid.index[position],
                           'channel': key, 'measurement': key.split(':', 1)[1]})
    keys = pl.from_pandas(pd.DataFrame(checks)[['device_name', 'hour']].drop_duplicates())
    floor = pl.col('time').dt.truncate('1h')
    ceiling = pl.when(pl.col('time') == floor).then(floor).otherwise(floor + pl.duration(hours=1)).alias('hour')
    sample = source.with_columns(ceiling).join(keys.lazy(), on=['device_name', 'hour']).select(
        'device_name', 'hour', 'time', 'measurement', 'value', 'valid_key').collect().to_pandas()
    for check in checks:
        group = sample[(sample.device_name == check['device_name']) & (sample.hour == check['hour'])]
        flags = group[group.measurement == FLAG]
        bad = set(flags[(~flags.valid_key) | (pd.to_numeric(flags.value, errors='coerce') == 0)].time)
        values = group[(group.measurement == check['measurement']) & group.valid_key & ~group.time.isin(bad)]
        values = pd.to_numeric(values.value, errors='coerce')
        values = values[np.isfinite(values)]
        equal(hourly.loc[check['hour'], check['channel']], float(values.median()))
    weather_keys = [key for key, m in summary['channel_metadata'].items() if m['device'] == 'SDI-12-LS-US915-3']
    weather_hours = set()
    for key in weather_keys:
        valid = hourly[key].dropna()
        weather_hours.update(valid.index[[0, len(valid) // 2, len(valid) - 1]])
    rain = hourly['SDI-12-LS-US915-3:precipitation_mm']
    positive = rain[rain > 0]
    weather_hours.update(positive.index[[0, len(positive) // 2, len(positive) - 1]])
    keys = pl.DataFrame({'hour': pd.DatetimeIndex(sorted(weather_hours))})
    sample = source.filter((pl.col('device_name') == 'SDI-12-LS-US915-3') & pl.col('valid_key') &
                           (pl.col('measurement') == 'device_frmpayload_data_data_sum')).with_columns(ceiling).join(
        keys.lazy(), on='hour').select('hour', 'value').collect().to_pandas()
    weather_checks = 0
    for hour, group in sample.groupby('hour'):
        values = pd.DataFrame([decode_weather(value) for value in group.value], columns=WEATHER_FIELDS)
        for field in WEATHER_FIELDS:
            good = values[field].dropna()
            expected = float(good.sum()) if field == 'precipitation_mm' else float(good.mean())
            equal(hourly.loc[hour, 'SDI-12-LS-US915-3:' + field], expected)
            weather_checks += 1
    value = {'verified_at_utc': pd.Timestamp.now(tz='UTC').isoformat(),
             'frozen_hourly_potential_matches': True, 'response_rows_checked': len(responses),
             'case_identities_and_boundaries_checked': len(cases), 'case_summaries_checked': len(case_summary),
             'temperature_associations_checked': len(correlations),
             'common_gaps_checked_directly_in_source': len(gaps),
             'raw_soil_hour_medians_spot_checked': len(checks), 'weather_hour_field_checks': weather_checks,
             'verifier_sha256': file_hash(Path(__file__))}
    receipt.write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    verify(args.run, args.audit, args.receipt or args.audit / 'independent_verification.json')
