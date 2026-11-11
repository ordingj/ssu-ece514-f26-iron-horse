"""Synthetic episode and warning examples with independently specified outcomes."""
import unittest

import numpy as np
import pandas as pd

from iron_horse.episodes import find_spells, associate_positive_hours, warning_rows

H = 3_600_000_000_000
BASE = pd.Timestamp('2026-07-10T00:00Z').value


class EpisodeChecks(unittest.TestCase):
    def spells(self, hours, values, reset=6):
        return find_spells('fixture', BASE + np.asarray(hours) * H,
                           np.asarray(values, dtype=float), reset)

    def test_repeated_dry_readings_and_brief_wetting_are_one_episode(self):
        rows = self.spells(range(1, 11), [-400] * 6 + [-500, -600, -400, -550])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['confirmed'])
        self.assertEqual(rows[0]['onset_ns'], BASE + 7 * H)
        self.assertEqual(rows[0]['last_dry_ns'], BASE + 10 * H)
        self.assertEqual(rows[0]['end_reason'], 'study_end')

    def test_complete_wet_reset_starts_a_second_episode(self):
        rows = self.spells(range(1, 16), [-400] * 6 + [-600] + [-400] * 6 + [-500, -600])
        self.assertEqual([r['onset_ns'] for r in rows], [BASE + 7 * H, BASE + 14 * H])
        self.assertTrue(all(r['confirmed'] for r in rows))
        self.assertEqual(rows[0]['end_reason'], 'wet_reset')

    def test_initial_dry_and_dry_after_long_gap_have_uncertain_onsets(self):
        rows = self.spells([1, 2, 6, 7], [-600] * 4)
        self.assertEqual(len(rows), 2)
        self.assertFalse(any(r['confirmed'] for r in rows))
        self.assertEqual(rows[0]['end_reason'], 'observation_gap')

    def test_missing_hour_breaks_wet_reset_and_exact_two_hour_gap_is_allowed(self):
        rows = self.spells([1, 2, 3, 4, 5, 7, 8], [-400] * 6 + [-600])
        self.assertFalse(rows[0]['confirmed'])
        rows = self.spells([1, 2, 3, 4, 5, 6, 7, 9], [-400] * 6 + [-600, -600])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['confirmed'])

    def test_one_dry_raw_reading_prevents_a_wet_hour(self):
        rows = self.spells([1, 2, 3, 4, 5, 5.5, 6, 7], [-400] * 5 + [-500, -400, -600])
        self.assertFalse(rows[0]['confirmed'])
        self.assertEqual(len(rows), 1)

    def test_positive_forecasts_share_one_event_and_post_onset_is_not_warning(self):
        times = BASE + np.arange(1, 12) * H
        values = np.array([-400] * 6 + [-600] * 5)
        spells = find_spells('fixture', times, values, 6)
        f = pd.DataFrame({'site': 'fixture', 'time': pd.to_datetime(
            BASE + np.array([5, 6, 8]) * H, utc=True), 'partition': 'test',
            'target': 1., 'baseline_prediction': [1, 1, 1],
            'rf_prediction': [0, 0, 0], 'lr_prediction': [0, 1, 0]})
        assigned = associate_positive_hours(f, {'fixture': (times, values)}, spells)
        self.assertEqual(assigned.episode_id.nunique(), 1)
        self.assertEqual(assigned.lead_hours.tolist(), [2., 1., -1.])
        rows = warning_rows(spells, assigned)
        by_method = {r['method']: r for r in rows}
        self.assertEqual(by_method['drying_trend']['warning_hours'], 2)
        self.assertEqual(by_method['drying_trend']['earliest_warning_lead_hours'], 2.)
        self.assertEqual(by_method['drying_trend']['latest_warning_lead_hours'], 1.)
        self.assertEqual(by_method['logistic_regression']['earliest_warning_lead_hours'], 1.)
        self.assertFalse(by_method['random_forest']['detected'])

    def test_one_forecast_is_assigned_only_to_its_first_future_dry_spell(self):
        times = BASE + np.arange(1, 16) * H
        values = np.array([-400] * 6 + [-600] + [-400] * 6 + [-600] * 2)
        spells = find_spells('fixture', times, values, 6)
        f = pd.DataFrame({'site': ['fixture'], 'time': pd.to_datetime([BASE + 6 * H], utc=True),
                          'partition': ['test'], 'target': [1.], 'baseline_prediction': [1],
                          'rf_prediction': [0], 'lr_prediction': [0]})
        assigned = associate_positive_hours(f, {'fixture': (times, values)}, spells)
        rows = [r for r in warning_rows(spells, assigned) if r['method'] == 'drying_trend']
        self.assertEqual([r['detected'] for r in rows], [True, False])
        self.assertEqual([r['scored_pre_onset_hours'] for r in rows], [1, 0])

    def test_development_baseline_has_lead_times_without_claiming_model_test_scores(self):
        onset = pd.Timestamp('2026-05-30T12:00Z')
        spell = {'episode_id': 'one', 'site': 'fixture', 'confirmed': True,
                 'partition': 'train', 'onset_ns': onset.value}
        assigned = pd.DataFrame({'episode_id': ['one'], 'partition': ['train'],
                                 'lead_hours': [12.], 'baseline_prediction': [1]})
        rows = warning_rows([spell], assigned)
        self.assertEqual({r['method'] for r in rows}, {'drying_trend', 'always_defer'})
        self.assertTrue(rows[0]['detected'])
        self.assertEqual(rows[0]['earliest_warning_lead_hours'], 12.)


if __name__ == '__main__':
    unittest.main()
