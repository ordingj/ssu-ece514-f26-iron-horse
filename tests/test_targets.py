"""Synthetic target outcomes and chronological audit rules."""
import unittest

import numpy as np
import pandas as pd

from iron_horse.targets import future_summary, target_frame, candidate_partition, trend_prediction
from iron_horse.episodes import find_spells

H = 3_600_000_000_000
ANCHOR = pd.Timestamp('2026-05-15T12:00Z')


class TargetChecks(unittest.TestCase):
    def window(self, values, hours=None):
        hours = np.arange(1, len(values) + 1) if hours is None else np.asarray(hours)
        return future_summary(ANCHOR.value + hours * H, np.asarray(values, dtype=float),
                              pd.DatetimeIndex([ANCHOR]), 6)

    def inputs(self, current=-50.):
        return pd.DataFrame({'time': [ANCHOR], 'site': ['fixture'], 'block': ['fixture'],
                             'current_potential_kpa': [current], 'forecast_eligible': [True],
                             'trend_6h_kpa_per_h': [-10.]})

    def test_window_excludes_current_and_includes_right_endpoint(self):
        future = self.window([-900, -50, -50, -50, -50, -50, -100], range(7))
        self.assertTrue(future['covered'][0])
        self.assertEqual(future['minimum_raw'][0], -100)
        self.assertEqual(future['occupied'][0], 6)
        f = target_frame(self.inputs(), future, -100., 6, 'new_dry_event')
        self.assertEqual(f.target.iloc[0], 1)

    def test_coverage_scales_to_five_sixths_and_keeps_two_hour_gap_limit(self):
        future = self.window([-50] * 5, [1, 2, 4, 5, 6])
        self.assertTrue(future['covered'][0])
        self.assertEqual(future['max_gap_hours'][0], 2.)
        future = self.window([-50] * 5, [2.1, 3, 4, 5, 6])
        self.assertFalse(future['covered'][0])
        twelve = future_summary(ANCHOR.value + np.arange(1, 10) * H,
                                 np.full(9, -50.), pd.DatetimeIndex([ANCHOR]), 12)
        self.assertFalse(twelve['covered'][0])

    def test_majority_unknown_bins_can_make_a_label_uncertain(self):
        for values, expected in (([-150] * 3 + [-50] * 2, 1.),
                                 ([-150] + [-50] * 4, 0.),
                                 ([-150] * 2 + [-50] * 3, np.nan)):
            future = self.window(values, [1, 2, 4, 5, 6])
            f = target_frame(self.inputs(), future, -100., 6, 'future_dry_majority')
            if np.isnan(expected):
                self.assertTrue(np.isnan(f.target.iloc[0]))
                self.assertFalse(f.evaluation_eligible.iloc[0])
            else:
                self.assertEqual(f.target.iloc[0], expected)

    def test_already_dry_is_excluded_only_from_new_event(self):
        future = self.window([-150] * 6)
        for family, expected in (('new_dry_event', False), ('future_dry_occurrence', True),
                                  ('future_dry_majority', True)):
            f = target_frame(self.inputs(-150.), future, -100., 6, family)
            self.assertEqual(f.evaluation_eligible.iloc[0], expected)

    def test_purge_uses_each_candidate_horizon_and_strict_boundary(self):
        tz = 'America/Los_Angeles'
        self.assertEqual(candidate_partition(pd.Timestamp('2026-05-31 17:00', tz=tz), 6), 'train')
        self.assertEqual(candidate_partition(pd.Timestamp('2026-05-31 18:00', tz=tz), 6), 'purged')
        self.assertEqual(candidate_partition(pd.Timestamp('2026-05-31 17:00', tz=tz), 24), 'purged')
        self.assertEqual(candidate_partition(pd.Timestamp('2026-08-30 00:00', tz=tz), 48), 'purged')

    def test_trend_references_follow_the_outcome_question(self):
        frame = pd.DataFrame({'current_potential_kpa': [-50., -150., -150.],
                              'trend_6h_kpa_per_h': [-10., 20., -1.]})
        np.testing.assert_array_equal(trend_prediction(frame, -100, 6, 'new_dry_event'), [1, 0, 1])
        np.testing.assert_array_equal(trend_prediction(frame, -100, 6, 'future_dry_occurrence'), [1, 1, 1])
        np.testing.assert_array_equal(trend_prediction(frame, -100, 6, 'future_dry_majority'), [0, 0, 1])

    def test_episode_threshold_is_explicit_and_default_stays_minus_500(self):
        times = ANCHOR.value + np.arange(1, 8) * H
        values = np.array([-50.] * 6 + [-150.])
        self.assertEqual(find_spells('fixture', times, values), [])
        spells = find_spells('fixture', times, values, threshold=-100.)
        self.assertEqual(len(spells), 1)
        self.assertTrue(spells[0]['confirmed'])


if __name__ == '__main__':
    unittest.main()
