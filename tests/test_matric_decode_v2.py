"""Regression cases for the actual dropped B North responses and framing guards."""
import math
import unittest
from iron_horse.matric import decode_matric, decode_response


class MatricDecoderTests(unittest.TestCase):
    def test_logged_b_north_zero_is_not_missing(self):
        self.assertEqual(decode_matric('0.0 16.2v'), 0.0)
        reading = decode_response('0.0 16.2v')
        self.assertEqual(reading.temperature_c, 16.2)
        self.assertEqual(reading.checksum_status, 'unavailable')

    def test_logged_addressed_frame_and_checksum(self):
        reading = decode_response('0-11.1 13.4v@N ')
        self.assertIsNotNone(reading)
        self.assertEqual((reading.potential_kpa, reading.temperature_c), (-11.1, 13.4))
        self.assertEqual(reading.checksum_status, 'verified')

    def test_corrupt_checksum_is_not_silently_discarded(self):
        self.assertIsNone(decode_response('0-11.1 13.4v@O'))
        self.assertIsNone(decode_response('0-11.1 13.4vAN'))

    def test_partial_checksum_and_unsigned_addressed_frame(self):
        reading = decode_response('0.0 9.5v6')
        self.assertEqual(reading.potential_kpa, 0)
        self.assertEqual(reading.checksum_status, 'legacy_verified_crc_unavailable')
        self.assertIsNone(decode_response('0.0 9.5v7'))
        reading = decode_response('00.0 10.3v\\7 ')
        self.assertEqual(reading.potential_kpa, 0)
        self.assertEqual(reading.checksum_status, 'verified')

    def test_no_arbitrary_suffix_or_extra_channel(self):
        for raw in ['0.0 16.2garbage', '0.0 16.2V', '0.0 16.2vv', '0.0 16.2v9',
                    '0.0 16.2v+7', '0.0 16.2 7', '0-40+20+99', 'nan 16.2v', '0.0 infv']:
            with self.subTest(raw=raw):
                self.assertTrue(math.isnan(decode_matric(raw)))

    def test_errors_in_either_field_still_invalidate_pair(self):
        for raw in ['-9999 16.2v', '0.0 -9992v', '-9992 16.2', '0-40-9999']:
            with self.subTest(raw=raw):
                self.assertTrue(math.isnan(decode_matric(raw)))

    def test_original_forms_and_nonzero_addressed_v(self):
        for raw, expected in [('0.0 14.0', 0), ('-426.1 19.', -426.1),
                              ('0-40.5+20.2', -40.5), ('0-14.4 13.1v', -14.4)]:
            with self.subTest(raw=raw):
                self.assertEqual(decode_matric(raw), expected)

    def test_documented_complete_ddi_frame(self):
        reading = decode_response('\t-34.8 22.3\rk@l')
        self.assertIsNotNone(reading)
        self.assertEqual(reading.potential_kpa, -34.8)
        self.assertEqual(reading.checksum_status, 'verified')


if __name__ == '__main__':
    unittest.main()
