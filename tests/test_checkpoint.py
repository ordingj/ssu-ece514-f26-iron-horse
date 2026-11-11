"""Synthetic checks for the current RF checkpoint protocol."""
import unittest
import json
import tempfile
from pathlib import Path
import joblib
import numpy as np
import pandas as pd

from iron_horse.checkpoint import (
    H, Preprocessor, baseline, forecast_labels, matric_value, model_pipeline,
    select_trial, bootstrap_interval,
    develop, evaluate, implementation_hashes, sha256, GRID,
)


class CurrentProtocolChecks(unittest.TestCase):
    def test_threshold_and_future_endpoints(self):
        anchor = pd.Timestamp('2026-06-10', tz='UTC')
        times = anchor.value + np.arange(25) * H
        values = np.full(25, -400.)
        values[0] = -600  # Present time is not in the future window.
        self.assertEqual(forecast_labels(times, values, [anchor])[0][0], 0)
        values[-1] = -500
        self.assertEqual(forecast_labels(times, values, [anchor])[0][0], 1)
        values[-1] = -499.99
        self.assertEqual(forecast_labels(times, values, [anchor])[0][0], 0)

    def test_sparse_labels_and_boundary_gaps(self):
        anchor = pd.Timestamp('2026-06-10', tz='UTC')
        for potential in (-400., -600.):
            y, _, _ = forecast_labels(anchor.value + np.array([1, 24]) * H,
                                       np.full(2, potential), [anchor])
            self.assertTrue(np.isnan(y[0]))
        hours = np.arange(4, 25)
        y, count, gap = forecast_labels(anchor.value + hours * H,
                                        np.full(len(hours), -600.), [anchor])
        self.assertEqual(count[0], 21)
        self.assertEqual(gap[0], 4)
        self.assertTrue(np.isnan(y[0]))

    def test_baseline_uses_six_hour_drying_forecast(self):
        frame = pd.DataFrame({'current_potential_kpa': [-400, -400, -400, -499, -500],
                              'trend_6h_kpa_per_h': [-5, -4, 2, 0, -1]})
        np.testing.assert_array_equal(baseline(frame), [1, 0, 0, 0, 1])

    def test_rf_unscaled_lr_scaled_and_fit_data_only(self):
        train = np.array([[1., 9., np.nan], [3., 9., np.nan], [np.nan, 9., np.nan]])
        rf = Preprocessor(scale=False).fit(train)
        lr = Preprocessor(scale=True).fit(train)
        np.testing.assert_array_equal(rf.transform([[np.nan, 999, 999]]), [[2, 1]])
        np.testing.assert_array_equal(lr.transform([[np.nan, 999, 999]]), [[0, 1]])
        np.testing.assert_array_equal(rf.transform([[1000, 999, 999]]), [[1000, 0]])
        np.testing.assert_array_equal(rf.medians_, [2])

    def test_model_settings_and_registered_ties(self):
        rf = model_pipeline('random_forest', {'max_depth': 4, 'min_samples_leaf': 30})
        p = rf.named_steps['classifier'].get_params()
        self.assertEqual((p['n_estimators'], p['random_state'], p['bootstrap']), (300, 514, True))
        self.assertEqual((p['criterion'], p['max_features'], p['class_weight']), ('gini', 'sqrt', None))
        trials = [{'f1': .5, 'max_depth': 8, 'min_samples_leaf': 10},
                  {'f1': .5, 'max_depth': 4, 'min_samples_leaf': 30},
                  {'f1': .5, 'max_depth': 4, 'min_samples_leaf': 10}]
        self.assertEqual(select_trial('random_forest', trials)['min_samples_leaf'], 30)
        self.assertEqual(select_trial('logistic_regression', [{'f1': .2, 'C': 10},
                                                             {'f1': .2, 'C': .1}])['C'], .1)

    def test_uncertain_cc_units_and_faults_stay_missing(self):
        self.assertTrue(np.isnan(matric_value('SDI-12-LS-US915-2', '-0.1234 78')))
        self.assertEqual(matric_value('SDI-12-LS-US915-2', '-577.4 20.'), -577.4)
        self.assertTrue(np.isnan(matric_value('SDI-12-LS-US915-1', '-500 -9992')))

    def test_bootstrap_keeps_paired_identical_predictions_zero(self):
        f = pd.DataFrame({'time': pd.to_datetime(['2026-07-02T12:00Z', '2026-08-02T12:00Z']),
                          'target': [1, 0], 'rf_prediction': [1, 1], 'baseline_prediction': [1, 1]})
        ci = bootstrap_interval(f)
        self.assertEqual((ci['lower'], ci['upper']), (0, 0))
        self.assertEqual(ci['resamples'], 2000)

    def make_fixture(self, output, negative_only=False, empty_test=False):
        cache = output / 'cache'
        cache.mkdir(parents=True)
        anchors = pd.to_datetime(['2026-01-02T12:00Z', '2026-01-04T12:00Z',
                                  '2026-06-02T12:00Z', '2026-06-04T12:00Z',
                                  '2026-07-02T12:00Z', '2026-07-04T12:00Z'])
        inputs = pd.DataFrame({'time': anchors, 'site': 'synthetic-site', 'block': 'synthetic',
            'partition': ['train', 'train', 'validation', 'validation', 'test', 'test'],
            'current_potential_kpa': -400., 'trend_6h_kpa_per_h': [-5., 0.] * 3,
            'history_hours_6h': 6, 'history_hours_24h': 24,
            'forecast_eligible': True, 'currently_dry': False, 'primary_input_eligible': True})
        times, values = [], []
        for i, anchor in enumerate(anchors):
            if empty_test and i >= 4:
                continue
            times.extend(anchor.value + np.arange(1, 25) * H)
            observations = np.full(24, -400.)
            if i % 2 == 0 and not negative_only:
                observations[-1] = -600.
            values.extend(observations)
        inputs.to_parquet(cache / 'hourly_inputs.parquet', index=False)
        joblib.dump({'synthetic-site': (np.asarray(times), np.asarray(values))}, cache / 'potential.joblib')
        (output / 'feature_schema.json').write_text(json.dumps({'columns': ['trend_6h_kpa_per_h']}))
        (output / 'preparation.json').write_text(json.dumps({
            'implementation_hashes': implementation_hashes(), 'source_sha256': 'synthetic',
            'feature_schema_sha256': sha256(output / 'feature_schema.json'),
            'derived_hashes': {p.name: sha256(p) for p in cache.iterdir()}}))

    def test_development_freeze_then_single_test_evaluation(self):
        # Deliberately synthetic observations with independently known labels.
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory)
            self.make_fixture(output)
            cache = output / 'cache'
            develop(output)
            self.assertTrue((output / 'model_freeze.json').exists())
            self.assertFalse((cache / 'test_examples.parquet').exists())
            self.assertFalse((output / 'test_unlock.json').exists())
            schema_path = output / 'feature_schema.json'
            schema = schema_path.read_text()
            schema_path.write_text(json.dumps({'columns': ['wrong_column']}))
            with self.assertRaisesRegex(RuntimeError, 'schema'):
                evaluate(output)
            self.assertFalse((output / 'test_unlock.json').exists())
            schema_path.write_text(schema)
            evaluate(output)
            result = json.loads((output / 'results.json').read_text())
            self.assertEqual(result['test_examples'], 2)
            self.assertEqual(result['positive_examples'], 1)
            self.assertEqual(result['metrics']['drying_trend']['f1'], 1)
            self.assertEqual(result['metrics']['always_defer']['f1'], 0)
            self.assertEqual(result['status'], 'not_evaluable')
            self.assertEqual(result['selected']['random_forest'], {'max_depth': 4, 'min_samples_leaf': 30})
            from iron_horse.verification import verify
            verify(output)
            receipt = json.loads((output / 'independent_verification.json').read_text())
            self.assertEqual(receipt['test_rows_replayed'], 2)
            with self.assertRaises(FileExistsError):
                evaluate(output)

    def test_single_class_development_records_not_evaluable(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.make_fixture(output, negative_only=True)
            self.assertFalse(develop(output))
            result = json.loads((output / 'results.json').read_text())
            self.assertEqual(result['status'], 'not_evaluable')
            self.assertFalse((output / 'test_unlock.json').exists())

    def test_empty_eligible_test_records_not_evaluable(self):
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            output = Path(directory)
            self.make_fixture(output, empty_test=True)
            develop(output)
            evaluate(output)
            result = json.loads((output / 'results.json').read_text())
            self.assertEqual(result['status'], 'not_evaluable')
            self.assertEqual(result['test_examples'], 0)
            self.assertTrue((output / 'coverage.csv').exists())


if __name__ == '__main__':
    unittest.main()
