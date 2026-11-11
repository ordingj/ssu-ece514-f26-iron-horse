"""Synthetic checks for descriptive sensor comparisons, without fault labels."""
import unittest

import numpy as np
import pandas as pd

from iron_horse.sensor_compare import observed_runs, window_change, strict_temperature, daily_pairs, weather_hourly


class SensorComparisonChecks(unittest.TestCase):
    def test_conflicting_weather_packet_is_not_an_observation(self):
        def packet(rain, temperature):
            fields = [1., rain, 0., 0., 2., 0., 0., temperature, 0., 0., .5] + [0.] * 6
            return '0' + ''.join(f'{value:+g}' for value in fields)
        packets = pd.DataFrame({
            'device_name': ['SDI-12-LS-US915-3'] * 3,
            'time': pd.to_datetime(['2026-08-01T10:10Z', '2026-08-01T10:20Z', '2026-08-01T11:10Z']),
            'value': [packet(0., 20.), packet(99., 99.), packet(99., 99.)],
            'valid_key': [True, False, False],
        })
        hourly = weather_hourly(packets)
        self.assertEqual(hourly.loc[pd.Timestamp('2026-08-01T11:00Z'), 'precipitation_mm'], 0.)
        self.assertEqual(hourly.loc[pd.Timestamp('2026-08-01T11:00Z'), 'air_temperature_c'], 20.)
        self.assertNotIn(pd.Timestamp('2026-08-01T12:00Z'), hourly.index)

    def test_missing_hours_break_near_zero_runs(self):
        values = np.array([0., 0., np.nan, 0., 0., 0., -5.])
        self.assertEqual(observed_runs(np.isfinite(values) & (np.abs(values) <= 1), 3), [(3, 5)])

    def test_window_change_preserves_missing_values_and_requires_half_observed(self):
        t = pd.Timestamp('2026-07-10T12:00Z')
        index = pd.date_range(t - pd.Timedelta(hours=6), periods=12, freq='h')
        values = pd.Series([10., np.nan, 10., np.nan, 10., np.nan,
                            12., np.nan, 12., np.nan, 12., np.nan], index=index)
        comparison = window_change(values, index[:6], index[6:])
        self.assertEqual(comparison['delta'], 2.)
        self.assertEqual(comparison['pre_hours'], 3)
        self.assertEqual(comparison['post_hours'], 3)
        values.loc[index[6]] = np.nan
        self.assertIsNone(window_change(values, index[:6], index[6:])['delta'])

    def test_cc_temperature_never_uses_an_estimated_truncated_field(self):
        self.assertTrue(np.isnan(strict_temperature('SDI-12-LS-US915-2', '-577.4 20.')))
        self.assertTrue(np.isnan(strict_temperature('SDI-12-LS-US915-2', '-0.1234 78')))
        self.assertEqual(strict_temperature('SDI-12-LS-US915-2', '-577.4 20.5'), 20.5)
        self.assertTrue(np.isnan(strict_temperature('SDI-12-LS-US915-1', '-500 -9992')))

    def test_daily_centering_does_not_mix_different_days(self):
        index = pd.date_range('2026-08-01', periods=48, freq='h', tz='America/Los_Angeles')
        x = np.r_[np.arange(24), 100 + np.arange(24)]
        y = np.r_[np.arange(24), -100 + np.arange(24)]
        pairs = daily_pairs(pd.Series(x, index=index), pd.Series(y, index=index))
        self.assertEqual(len(pairs), 48)
        self.assertEqual(pairs.day.nunique(), 2)
        self.assertAlmostEqual(pairs.x.corr(pairs.y), 1.)
        self.assertTrue((pairs.groupby('day').x.mean().abs() < 1e-12).all())

    def test_short_paired_days_remain_excluded(self):
        index = pd.date_range('2026-08-01', periods=24, freq='h', tz='America/Los_Angeles')
        x = pd.Series(np.arange(24, dtype=float), index=index)
        y = x.copy(); y.iloc[:7] = np.nan
        self.assertTrue(daily_pairs(x, y).empty)


if __name__ == '__main__':
    unittest.main()
