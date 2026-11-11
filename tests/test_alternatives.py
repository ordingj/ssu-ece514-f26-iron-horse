"""Synthetic behavior checks for the two fixed alternative model forms."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from iron_horse.alternatives import fit_model, run


class AlternativeChecks(unittest.TestCase):
    def test_median_regression_recovers_line_despite_one_large_target_residual(self):
        x = pd.DataFrame({'history__x': np.arange(21, dtype=float)})
        y = 2 * np.arange(21, dtype=float) + 1;y[-1] += 100
        model = fit_model('median_regression', x, y)
        self.assertAlmostEqual(model.predict(pd.DataFrame({'history__x': [10.]}))[0], 21., places=5)
        self.assertEqual(model.named_steps['regressor'].quantile, .5)

    def test_boosting_uses_fixed_iterations_without_automatic_validation(self):
        x = pd.DataFrame({'history__x': np.arange(60, dtype=float)})
        model = fit_model('hist_boosting', x, np.full(60, 5.))
        regressor = model.named_steps['regressor']
        self.assertFalse(regressor.do_early_stopping_)
        self.assertEqual(regressor.n_iter_, 100)
        self.assertTrue(np.allclose(model.predict(x), 5.))

    def test_both_models_handle_missing_predictors_without_imputing_targets(self):
        x = pd.DataFrame({'history__x': [0., 1., np.nan, 3., 4., 5.]})
        for method in ['median_regression', 'hist_boosting']:
            with self.subTest(method=method):
                model = fit_model(method, x, np.arange(6, dtype=float))
                prediction = model.predict(pd.DataFrame({'history__x': [np.nan, 2.]}))
                self.assertTrue(np.isfinite(prediction).all())

    def test_unknown_model_fails_explicitly(self):
        with self.assertRaises(ValueError): fit_model('unplanned', pd.DataFrame({'x': [1.]}), np.array([1.]))

    def test_output_guards_protect_both_parents_and_existing_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder) / 'parent';parent.mkdir()
            transfer = Path(folder) / 'transfer';transfer.mkdir()
            for source in [parent, transfer]:
                with self.assertRaises(ValueError):run(parent, transfer, source / 'nested')
            output = Path(folder) / 'existing';output.mkdir()
            with self.assertRaises(FileExistsError):run(parent, transfer, output)


if __name__ == '__main__':
    unittest.main()
