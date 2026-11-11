"""Synthetic timing, coverage, and score checks for continuous forecasts."""
import unittest
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from iron_horse.continuous import build_examples, fold_masks, regression_scores, run, artifact_hashes


class ContinuousChecks(unittest.TestCase):
    def fixture(self):
        index = pd.date_range('2026-05-28', periods=120, freq='h', tz='UTC')
        data = pd.DataFrame({'mat:potential': np.arange(120, dtype=float) - 500,
                             'soil:device_frmpayload_data_water_SOIL': np.arange(120, dtype=float),
                             'station:air_temperature_c': np.arange(120, dtype=float) + 10}, index=index)
        info = {'mat:potential': {'device': 'mat', 'block': 'P', 'slope': 'upslope', 'kind': 'potential'},
                'soil:device_frmpayload_data_water_SOIL': {'device': 'soil', 'block': 'P', 'slope': 'upslope', 'kind': 'water'},
                'station:air_temperature_c': {'device': 'station', 'block': 'I', 'slope': None, 'kind': 'air_temperature_c'}}
        return data, info

    def examples(self, data, info):
        return build_examples(data, info, {'mat': 'soil'})

    def test_endpoint_change_and_six_hour_trend_have_correct_units(self):
        data, info = self.fixture();frame = self.examples(data, info)
        row = frame[(frame.outcome == 'water') & (frame.time == data.index[30])].iloc[0]
        self.assertEqual(row.target_change, 24.)
        self.assertEqual(row.trend_change, 24.)
        self.assertEqual(row.current, 30.)
        self.assertTrue(row.eligible_complete)

    def test_coverage_distinguishes_small_gaps_from_complete_windows(self):
        data, info = self.fixture();data.iloc[28, 1] = np.nan
        row = self.examples(data, info).query("outcome == 'water'").iloc[30]
        self.assertTrue(row.eligible_covered)
        self.assertFalse(row.eligible_complete)
        data.iloc[27:30, 1] = np.nan
        row = self.examples(data, info).query("outcome == 'water'").iloc[30]
        self.assertFalse(row.past_covered)

    def test_missing_endpoint_or_exact_lag_never_gets_imputed(self):
        data, info = self.fixture();data.iloc[54, 1] = np.nan
        row = self.examples(data, info).query("outcome == 'water'").iloc[30]
        self.assertFalse(row.eligible_covered)
        self.assertTrue(np.isnan(row.target_change))
        data, info = self.fixture();data.iloc[24, 1] = np.nan
        row = self.examples(data, info).query("outcome == 'water'").iloc[30]
        self.assertFalse(row.past_covered)

    def test_future_changes_cannot_change_issued_predictors(self):
        data, info = self.fixture();a = self.examples(data, info)
        data.iloc[31:] = -99999.
        b = self.examples(data, info)
        keys = [key for key in a if key.startswith(('history__', 'extra__'))]
        a = a[a.time == data.index[30]].sort_values('outcome').reset_index(drop=True)
        b = b[b.time == data.index[30]].sort_values('outcome').reset_index(drop=True)
        pd.testing.assert_frame_equal(a[keys], b[keys])

    def test_training_and_evaluated_labels_stay_strictly_within_fold(self):
        times = pd.DatetimeIndex(['2026-05-30T23:00Z', '2026-05-31T00:00Z',
                                  '2026-06-01T00:00Z', '2026-06-29T23:00Z', '2026-06-30T00:00Z'])
        train, test = fold_masks(times, pd.Timestamp('2026-06-01T00:00Z'), pd.Timestamp('2026-07-01T00:00Z'))
        np.testing.assert_array_equal(train, [True, False, False, False, False])
        np.testing.assert_array_equal(test, [False, False, True, True, False])

    def test_scores_use_paired_changes_and_explicit_zero_reference(self):
        value = regression_scores(np.array([1., -3.]), np.array([2., -1.]))
        self.assertEqual(value['mae'], 1.5)
        self.assertEqual(value['bias'], 1.5)
        self.assertAlmostEqual(value['rmse'], np.sqrt(2.5))
        self.assertEqual(value['persistence_mae'], 2.)
        self.assertEqual(value['mae_skill_vs_persistence'], .25)
        self.assertIsNone(regression_scores(np.zeros(2), np.ones(2))['mae_skill_vs_persistence'])

    def test_run_refuses_source_mutation_and_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source';source.mkdir()
            with self.assertRaises(ValueError): run(source, source / 'nested')
            output = Path(folder) / 'existing';output.mkdir()
            with self.assertRaises(FileExistsError): run(source, output)

    def test_provenance_covers_declared_outputs_and_ignores_os_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            for name in ['hourly.parquet', 'examples.parquet', 'channel_metadata.json', 'predictions.parquet',
                         'metrics.csv', 'pooled_metrics.csv', 'daily_errors.csv', 'common_policy_comparison.csv',
                         'coverage.csv', 'forecast-mae.png', 'monthly-mae.png', 'model.joblib', '.DS_Store',
                         '._forecast-mae.png', 'desktop.ini', 'Thumbs.db']:
                (output / name).write_text('synthetic artifact')
            hashes = artifact_hashes(output, ['model.joblib'])
            self.assertEqual(len(hashes), 12)
            for name in ['.DS_Store', '._forecast-mae.png', 'desktop.ini', 'Thumbs.db']:
                self.assertNotIn(name, hashes)
            self.assertIn('model.joblib', hashes)


if __name__ == '__main__':
    unittest.main()
