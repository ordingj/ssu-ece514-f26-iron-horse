"""Synthetic split and scoring contracts for block-transfer experiments."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from iron_horse.transfer import select_split, summer_mask, summarize, run


class TransferChecks(unittest.TestCase):
    def fixture(self):
        return pd.DataFrame({'site': ['A', 'B', 'A', 'B', 'B', 'A'],
            'time': pd.to_datetime(['2026-05-20T12:00Z', '2026-05-20T12:00Z', '2026-06-10T12:00Z',
                                    '2026-06-10T12:00Z', '2026-08-10T12:00Z', '2026-05-31T07:00Z']),
            'eligible_covered': True})

    def test_block_only_excludes_entire_target_block_but_allows_other_future_months(self):
        data = self.fixture();train, test = select_split(data, 'block_only', 'A')
        self.assertEqual(list(train.index), [1, 3, 4])
        self.assertEqual(list(test.index), [0, 2, 5])

    def test_block_time_excludes_target_and_training_labels_at_month_boundary(self):
        data = self.fixture()
        extra = pd.DataFrame({'site': ['B'], 'time': pd.to_datetime(['2026-05-31T07:00Z']), 'eligible_covered': True})
        data = pd.concat([data, extra], ignore_index=True)
        train, test = select_split(data, 'block_time', 'A', '2026-06')
        self.assertEqual(list(train.index), [1])
        self.assertEqual(list(test.index), [2])

    def test_pooled_time_uses_earlier_target_history_without_future_rows(self):
        train, test = select_split(self.fixture(), 'pooled_time', None, '2026-06')
        self.assertEqual(list(train.index), [0, 1])
        self.assertEqual(list(test.index), [2, 3])

    def test_common_summer_rows_have_strict_month_endpoint_purge(self):
        times = pd.to_datetime(['2026-05-20T12:00Z', '2026-06-29T06:00Z',
                                '2026-06-30T07:00Z', '2026-08-30T06:00Z', '2026-08-31T07:00Z'])
        np.testing.assert_array_equal(summer_mask(times), [False, True, False, True, False])

    def test_scoring_keeps_full_season_and_common_cases_separate(self):
        frame = pd.DataFrame({'design': 'block_only', 'site': 'A', 'fold': ['2026-01', '2026-06'],
            'method': 'persistence', 'day': ['2026-01-02', '2026-06-02'],
            'common_eval': [False, True], 'actual': [10., 2.], 'prediction': [0., 0.]})
        metrics, pooled, daily = summarize(frame)
        self.assertEqual(pooled.query("scope == 'full_season'").iloc[0].mae, 6.)
        self.assertEqual(pooled.query("scope == 'common_summer'").iloc[0].mae, 2.)
        self.assertEqual(len(metrics), 3)
        self.assertEqual(len(daily), 3)

    def test_output_protection_precedes_parent_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder) / 'parent';parent.mkdir()
            with self.assertRaises(ValueError):run(parent, parent / 'nested')
            output = Path(folder) / 'existing';output.mkdir()
            with self.assertRaises(FileExistsError):run(parent, output)


if __name__ == '__main__':
    unittest.main()
