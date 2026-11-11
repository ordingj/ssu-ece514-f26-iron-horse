"""Check Cc response interpretation without generating corrected records or charts."""
import csv
import doctest
import math
from pathlib import Path
import subprocess
import sys
import unittest

from iron_horse import cc_policy as policy


class ResponsePolicyChecks(unittest.TestCase):
    """Keep unit uncertainty, literal fields, and strict values distinct."""

    def test_literal_fields_retain_precision_and_framing(self):
        """Extract tokens without filling missing digits or requiring a checksum."""
        cases = [
            ('0.0462 81', ('0.0462', '81')),
            ('-577.4 20.', ('-577.4', '20.')),
            ('0-40.5+20.2', ('-40.5', '+20.2')),
            (' \t-34.8 22.3\rk@l \n', ('-34.8', '22.3')),
            ('0-11.1 13.4v@O', ('-11.1', '13.4')),
            ('unrecognized', (None, None)),
            (None, (None, None)),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(policy.fields(raw), expected)

    def test_unknown_early_units_keep_only_explicit_estimates(self):
        """Keep early potential and strict Celsius unset in every phase."""
        for phase, basis, estimate in [
            ('before_scale_change', 'F_like_unconfirmed', 245 / 9),
            ('changed_scale_old_format', 'C_like_unconfirmed', 81.0),
            ('standard_format', 'C_like_unconfirmed', 81.0),
            ('unrecognized_phase', 'C_like_unconfirmed', 81.0),
        ]:
            with self.subTest(phase=phase):
                result = policy.correct('0.0462 81', phase)
                self.assertIsNone(result['matric_potential_kpa'])
                self.assertIsNone(result['temperature_c'])
                self.assertAlmostEqual(result['temperature_c_estimate'], estimate)
                self.assertEqual(result['temperature_unit_basis'], basis)
                self.assertEqual(result['potential_quality'], 'unknown_first_field_units')
                self.assertFalse(result['temperature_complete_numeric_field'])

    def test_single_digit_temperature_has_no_estimate(self):
        """Reject one-digit prefixes in early and later formats."""
        for raw in ('-0.0029 1', '-1917.2 1', '-1917.2 -1'):
            with self.subTest(raw=raw):
                result = policy.correct(raw, 'changed_scale_old_format')
                self.assertIsNone(result['temperature_c'])
                self.assertIsNone(result['temperature_c_estimate'])
                self.assertEqual(result['temperature_quality'], 'one_digit_prefix_unrecoverable')

    def test_integer_and_trailing_point_temperatures_are_estimates(self):
        """Keep multi-digit numeric prefixes out of strict Celsius values."""
        for raw in ('-577.4 20', '-577.4 20.'):
            with self.subTest(raw=raw):
                result = policy.correct(raw, 'standard_format')
                self.assertEqual(result['matric_potential_kpa'], -577.4)
                self.assertEqual(result['temperature_c_estimate'], 20.0)
                self.assertIsNone(result['temperature_c'])
                self.assertFalse(result['temperature_complete_numeric_field'])
                self.assertEqual(result['temperature_quality'], 'numeric_prefix_fraction_missing')

    def test_complete_fields_retain_strict_values_and_checksum_status(self):
        """Keep decoded values and their actual checksum status for later formats."""
        for raw, potential, temperature, checksum in [
            ('0.0 16.2v', 0.0, 16.2, 'unavailable'),
            ('0-11.1 13.4v@N ', -11.1, 13.4, 'verified'),
            ('0.0 9.5v6', 0.0, 9.5, 'legacy_verified_crc_unavailable'),
            ('0-40.5+20.2', -40.5, 20.2, 'not_present'),
        ]:
            with self.subTest(raw=raw):
                result = policy.correct(raw, 'before_scale_change')
                self.assertEqual(result['matric_potential_kpa'], potential)
                self.assertEqual(result['temperature_c'], temperature)
                self.assertEqual(result['temperature_c_estimate'], temperature)
                self.assertEqual(result['checksum_status'], checksum)
                self.assertTrue(result['temperature_complete_numeric_field'])

    def test_rejected_responses_keep_raw_fields_without_interpretation(self):
        """Retain shape-matched fields when faults or checksums reject a response."""
        for raw in ('0-11.1 13.4v@O', '-9999 20', '0.0 -9992', '-1e400 16.2', None):
            with self.subTest(raw=raw):
                result = policy.correct(raw, 'standard_format')
                self.assertEqual((result['first_field_text'], result['second_field_text']), policy.fields(raw))
                self.assertEqual(result['response_format'], 'rejected')
                self.assertEqual(result['temperature_quality'], 'parse_rejected')
                self.assertEqual(result['potential_quality'], 'parse_rejected')
                for key in ('matric_potential_kpa', 'temperature_c', 'temperature_c_estimate'):
                    self.assertIsNone(result[key])
        self.assertEqual(policy.correct('-9999 20', '')['first_field_raw'], -9999.0)

    def test_shared_phase_timestamps_preserve_nanosecond_values(self):
        """Retain the observed scale-change and standard-format instants."""
        self.assertEqual(policy.FIRST_CHANGED.isoformat(), '2026-03-21T14:52:24.985849+00:00')
        self.assertEqual(policy.FIRST_STANDARD.isoformat(), '2026-03-23T16:36:08.313361+00:00')

    def test_saved_boundary_evidence_matches_every_policy_field(self):
        """Reconcile interpretation with both saved boundary evidence tables."""
        directory = Path(__file__).resolve().parents[1] / 'tests/fixtures/cc-boundaries'
        for name in ('scale_change_evidence.csv', 'format_change_evidence.csv'):
            with self.subTest(file=name):
                with (directory / name).open(newline='') as stream:
                    rows = list(csv.DictReader(stream))
                self.assertGreater(len(rows), 0)
                for row in rows:
                    result = policy.correct(row['raw_response'], row['phase'])
                    for key, value in result.items():
                        with self.subTest(raw=row['raw_response'], key=key):
                            expected = row[key]
                            if value is None:
                                self.assertEqual(expected, '')
                            elif isinstance(value, bool):
                                self.assertEqual(str(value), expected)
                            elif isinstance(value, float):
                                self.assertTrue(math.isclose(value, float(expected), rel_tol=0, abs_tol=1e-12))
                            else:
                                self.assertEqual(value, expected)

    def test_policy_import_does_not_load_artifact_writers(self):
        """Import policy in a fresh process without plotting or experiment modules."""
        script = """import sys
from iron_horse import cc_policy
for name in ('correct_cc_records', 'run_experiment', 'matplotlib', 'polars'):
    assert name not in sys.modules, name
"""
        subprocess.run([sys.executable, '-W', 'error', '-c', script],
                       cwd=Path(__file__).resolve().parents[1], check=True)

    def test_documented_examples(self):
        """Check the numeric-prefix examples against the public policy function."""
        result = doctest.testmod(policy, verbose=False)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.attempted, 2)


if __name__ == '__main__':
    unittest.main()
