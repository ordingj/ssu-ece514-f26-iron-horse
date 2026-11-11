"""Synthetic checks for training references, robust loss, and fixed windows."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline

from iron_horse.core import FrozenPreprocessor
from iron_horse.robust import split_panel, training_references, fit_absolute, summarize, needs_rolling, run


class RobustChecks(unittest.TestCase):
    def test_training_median_and_linear_quantile_ignore_evaluation_values(self):
        values = np.array([-10., -1., 0., 2., 3.])
        reference = training_references(values)
        self.assertEqual(reference['median_change'], 0.)
        self.assertAlmostEqual(reference['larger_cutoff'], 7.2)

    def test_rolling_window_includes_lower_endpoint_and_purges_label_boundary(self):
        start = pd.Timestamp('2026-06-01T00:00Z');end = pd.Timestamp('2026-07-01T00:00Z')
        times = pd.DatetimeIndex([start - pd.Timedelta(days=90, hours=1), start - pd.Timedelta(days=90),
                                  start - pd.Timedelta(hours=25), start - pd.Timedelta(hours=24),
                                  start, end - pd.Timedelta(hours=24)])
        panel = pd.DataFrame({'time': times, 'eligible_covered': True})
        train, test = split_panel(panel, start, end, 90)
        self.assertEqual(list(train.index), [1, 2])
        self.assertEqual(list(test.index), [4])
        expanded, _ = split_panel(panel, start, end)
        self.assertEqual(list(expanded.index), [0, 1, 2])

    def test_absolute_forest_uses_median_without_mutating_control(self):
        x = pd.DataFrame({'x': np.arange(6.)});y = np.array([0., 0., 0., 0., 0., 100.])
        control = Pipeline([('preprocess', FrozenPreprocessor()), ('regressor', RandomForestRegressor(
            n_estimators=1, bootstrap=False, min_samples_leaf=24, random_state=514))])
        control.fit(x, y)
        robust = fit_absolute(control, x, y)
        self.assertEqual(control.named_steps['regressor'].criterion, 'squared_error')
        self.assertEqual(robust.named_steps['regressor'].criterion, 'absolute_error')
        self.assertAlmostEqual(control.predict(x)[0], 100 / 6)
        self.assertEqual(robust.predict(x)[0], 0.)
        self.assertEqual(control.named_steps['regressor'].n_estimators, robust.named_steps['regressor'].n_estimators)

    def predictions(self, actual, cutoff):
        return pd.DataFrame({'window': 'expanding', 'site': 'test', 'fold': '2026-06',
            'method': 'persistence', 'time': pd.date_range('2026-06-01', periods=len(actual), freq='h', tz='UTC'),
            'day': '2026-06-01', 'actual': actual, 'prediction': 0., 'larger_cutoff': cutoff})

    def test_large_subset_is_strict_and_empty_subset_is_retained(self):
        metrics, pooled, _ = summarize(self.predictions([1., 2., 3.], 2.))
        self.assertEqual(metrics.query("stratum == 'larger'").iloc[0]['n'], 1)
        self.assertEqual(pooled.query("stratum == 'larger'").iloc[0].mae, 3.)
        metrics, pooled, _ = summarize(self.predictions([1., 2.], 2.))
        row = pooled.query("stratum == 'larger'").iloc[0]
        self.assertEqual(row['n'], 0);self.assertTrue(pd.isna(row.mae))

    def test_rolling_trigger_requires_forest_to_beat_both_constants(self):
        table = pd.DataFrame({'window': 'expanding', 'stratum': 'all',
            'method': ['persistence', 'median_change', 'forest_absolute'], 'mae': [1., .8, .8]})
        self.assertTrue(needs_rolling(table))
        table.loc[2, 'mae'] = .7
        self.assertFalse(needs_rolling(table))

    def test_output_guard_runs_before_loading_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source';source.mkdir()
            with self.assertRaises(ValueError): run(source, source / 'nested')
            output = Path(folder) / 'existing';output.mkdir()
            with self.assertRaises(FileExistsError): run(source, output)


if __name__ == '__main__':
    unittest.main()
