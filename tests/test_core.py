"""Synthetic checks before any experimental labels or models are calculated."""
import unittest
import numpy as np
import pandas as pd
from iron_horse.core import (H, JUNE, JULY, GRID, FrozenPreprocessor, decode_weather, latest, partition, slopes)
from iron_horse.checkpoint import forecast_labels
from iron_horse.matric import decode_matric


class ProtocolChecks(unittest.TestCase):
    def test_fault_temperature_invalidates_apparently_valid_potential(self):
        self.assertTrue(np.isnan(decode_matric('-40 -9992')))
        self.assertTrue(np.isnan(decode_matric('-9999 20')))
        self.assertEqual(decode_matric('0-40.5+20.2'), -40.5)
        self.assertTrue(np.isnan(decode_matric('0-40+20+99')))

    def test_weather_placeholder_cannot_shift_humidity(self):
        vals = [100, 1, 2, 3, 4, 5, 6, 7, 8, 9, .51, 11, 12, 13, -9999, 15, 16]
        raw = '0' + ''.join(f'{v:+}' for v in vals)
        self.assertEqual(decode_weather(raw), [100, 1, 4, 7, 51])
        self.assertTrue(all(np.isnan(v) for v in decode_weather(raw + '+99')))

    def test_current_crossing_is_not_a_future_event(self):
        anchor = pd.Timestamp('2026-01-02', tz='UTC')
        t = anchor.value
        times = t + np.arange(25) * H
        values = np.full(25, -400.)
        values[0] = -550
        y, count, _ = forecast_labels(times, values, [anchor])
        self.assertEqual(y[0], 0)
        self.assertEqual(count[0], 24)
        values[-1] = -500
        self.assertEqual(forecast_labels(times, values, [anchor])[0][0], 1)

    def test_sparse_positive_is_unlabeled_just_like_sparse_negative(self):
        anchor = pd.Timestamp('2026-01-02', tz='UTC')
        times = anchor.value + np.array([1, 24]) * H
        for values in (np.array([-550., -400.]), np.array([-400., -400.])):
            self.assertTrue(np.isnan(forecast_labels(times, values, [anchor])[0][0]))

    def test_large_gap_invalidates_window_even_when_20_bins_occupied(self):
        anchor = pd.Timestamp('2026-01-02', tz='UTC')
        hours = np.array([i for i in range(1, 25) if i not in (7, 8, 9)])
        y, count, gap = forecast_labels(anchor.value + hours * H, np.full(len(hours), -400.), [anchor])
        self.assertEqual(count[0], 21)
        self.assertEqual(gap[0], 4)
        self.assertTrue(np.isnan(y[0]))

    def test_boundary_targets_are_purged(self):
        self.assertEqual(partition(JUNE - pd.Timedelta(hours=24)), 'purged')
        self.assertEqual(partition(JUNE - pd.Timedelta(hours=25)), 'train')
        self.assertEqual(partition(JUNE), 'validation')
        self.assertEqual(partition(JULY - pd.Timedelta(hours=24)), 'purged')
        self.assertEqual(partition(JULY), 'test')

    def test_scaling_and_imputation_never_fit_test_values(self):
        train = np.array([[1., 10., np.nan], [3., 10., np.nan], [np.nan, 10., np.nan]])
        transformer = FrozenPreprocessor().fit(train)
        self.assertEqual(transformer.keep_.tolist(), [0])
        medians = transformer.medians_.copy()
        out = transformer.transform([[1000., -10000., 999.], [np.nan, 5., 8.]])
        np.testing.assert_array_equal(transformer.medians_, medians)
        self.assertEqual(out[1, 1], 1)
        self.assertEqual(out[1, 0], 0)

    def test_trends_are_causal_and_use_elapsed_hours(self):
        x = np.array([-10., -11., -12., -13., -14., -15., -16.])
        original = slopes(x, 6)
        x[-1] = -500
        revised = slopes(x, 6)
        np.testing.assert_equal(original[:-1], revised[:-1])
        self.assertAlmostEqual(original[-1], -1)

    def test_stale_soil_reading_is_missing(self):
        result = latest(np.array([GRID[0].value]), np.array([12.]))
        self.assertEqual(result[0], 12)
        self.assertEqual(result[1], 12)
        self.assertTrue(np.isnan(result[2]))


if __name__ == '__main__':
    unittest.main()
