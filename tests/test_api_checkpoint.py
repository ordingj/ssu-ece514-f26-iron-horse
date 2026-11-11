"""Synthetic public-response checks. These fixtures are not vineyard readings."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from iron_horse.api_checkpoint import capture_window, clean_snapshot, verify_snapshot, build_inputs, adapter_hashes, prepared_cache_hashes
from iron_horse.core import sha256, save_json
from iron_horse import checkpoint
import numpy as np
import pandas as pd
import polars as pl


class PublicCheckpointChecks(unittest.TestCase):
    start = '2026-08-01T07:00:00+00:00'
    stop = '2026-08-01T08:00:00+00:00'

    def page(self, rows, offset=0, next_offset=None):
        return {'source': 'influxdb-standby', 'measurement': 'soil_water',
                'start': self.start, 'stop': self.stop, 'limit': 10000,
                'offset': offset, 'next_offset': next_offset, 'readings': rows}

    def row(self, value=20., **extra):
        return {'time': '2026-08-01T07:00:00.000000001Z',
                'measurement': 'soil_water', 'value': value,
                'sensor': 'sensor-aaaaaaaaaaaaaaaaaaaaaaaa', 'dev_eui': 'a84041d4915dcaab',
                'device_name': 'SE01-LS-2', 'block': 'P', 'slope': 'upslope', **extra}

    def capture(self, folder, pages):
        requests = []
        def get(params):
            requests.append(dict(params))
            return json.dumps(pages.pop(0)).encode()
        records = capture_window('soil_water', self.start, self.stop, Path(folder), get=get)
        return records, requests

    def test_empty_decoded_page_still_advances_and_cache_replays_offline(self):
        with tempfile.TemporaryDirectory() as folder:
            records, requests = self.capture(folder, [self.page([], next_offset=10000),
                                            self.page([self.row()], offset=10000)])
            self.assertEqual([r['offset'] for r in requests], [0, 10000])
            self.assertTrue(all(r['include_metadata'] == 'true' for r in requests))
            again, requests = self.capture(folder, [])
            self.assertEqual(records, again)
            self.assertEqual(requests, [])

    def test_cursor_cycles_wrong_windows_and_outside_readings_are_rejected(self):
        for page in [self.page([], next_offset=0), self.page([self.row(time=self.stop)]),
                     dict(self.page([]), stop='2026-08-02T08:00:00Z')]:
            with self.subTest(page=page), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError): self.capture(folder, [page])

    def test_conflicting_values_are_excluded_but_identical_rows_collapse(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records, _ = self.capture(root, [self.page([self.row(), self.row(), self.row(21.),
                self.row(22., time='2026-08-01T07:10:00Z')])])
            (root / 'snapshot.json').write_text(json.dumps({'pages': records}))
            clean = clean_snapshot(root, root / 'clean.parquet').to_pandas()
            self.assertEqual(len(clean), 2)
            self.assertEqual(clean.valid_key.tolist(), [False, True])
            self.assertEqual(clean.time.iloc[0].value, 1785567600000000001)

    def test_metadata_disagreement_and_missing_identity_fail_closed(self):
        for row in [self.row(block='Cc'), self.row(dev_eui=None), self.row(sensor=None)]:
            with self.subTest(row=row), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError): self.capture(folder, [self.page([row])])

    def test_page_mutation_is_detected_before_offline_processing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records, _ = self.capture(root, [self.page([self.row()])])
            (root / 'snapshot.json').write_text(json.dumps({'pages': records}))
            verify_snapshot(root)
            (root / records[0]['file']).write_bytes(gzip.compress(b'{}'))
            with self.assertRaises(ValueError): verify_snapshot(root)

    def test_missing_metadata_and_incomplete_page_chains_are_rejected(self):
        row = self.row(); del row['device_name']
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'metadata'):
                self.capture(folder, [self.page([row])])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records, _ = self.capture(root, [self.page([], next_offset=10000),
                                             self.page([self.row()], offset=10000)])
            (root / 'snapshot.json').write_text(json.dumps({'pages': records[:-1]}))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                verify_snapshot(root)

    def test_hourly_medians_latest_probe_and_weather_use_only_observed_history(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = []
            for when, value in [('2026-08-01T07:10Z', -400.), ('2026-08-01T07:40Z', -420.),
                                 ('2026-08-01T08:10Z', -900.)]:
                rows.append(dict(time=pd.Timestamp(when), device_name='SDI-12-LS-US915-1',
                    measurement='matric_potential_kpa', value=value, block='P', slope='upslope', valid_key=True))
            for measurement, device, block, value in [
                ('soil_water', 'SE01-LS-2', 'P', 20.),
                ('atmos_air_temperature_c', 'SDI-12-LS-US915-3', 'I', 15.),
                ('atmos_precipitation_mm', 'SDI-12-LS-US915-3', 'I', 2.)]:
                rows.append(dict(time=pd.Timestamp('2026-08-01T07:30Z'), device_name=device,
                    measurement=measurement, value=value, block=block,
                    slope='upslope' if block == 'P' else None, valid_key=True))
            for row in rows:
                row['potential_quality'] = 'reported_kpa_calibration_not_validated' if row['measurement'] == 'matric_potential_kpa' else None
            frame, potential = build_inputs(pl.from_pandas(pd.DataFrame(rows)), Path(folder))
            at = frame[(frame.site == 'SDI-12-LS-US915-1') & (frame.time == pd.Timestamp('2026-08-01T08:00Z'))].iloc[0]
            self.assertEqual(at.current_potential_kpa, -410.)
            self.assertEqual(at.soil__upslope__probe1__water_content, 20.)
            self.assertEqual(at.weather__air_temperature_c__24h, 15.)
            self.assertEqual(at.weather__precipitation_mm__24h, 2.)
            later = frame[(frame.site == 'SDI-12-LS-US915-1') & (frame.time == pd.Timestamp('2026-08-01T09:00Z'))].iloc[0]
            self.assertTrue(np.isnan(later.soil__upslope__probe1__water_content))
            self.assertEqual(later.current_potential_kpa, -900.)
            self.assertEqual(len(json.loads((Path(folder) / 'feature_schema.json').read_text())['columns']), 24)
            self.assertEqual(potential['SDI-12-LS-US915-1'][1].tolist(), [-400., -420., -900.])

    def test_generic_development_checks_api_pages_before_reading_cached_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'source'; output = root / 'output'
            records, _ = self.capture(source, [self.page([self.row()])])
            save_json(source / 'snapshot.json', {'pages': records})
            (output / 'cache').mkdir(parents=True)
            (output / 'feature_schema.json').write_text('{}')
            save_json(output / 'preparation.json', {'source_kind': 'public_influx_api',
                'quality_policy': 'reported-kpa-v1',
                'source': str(source / 'snapshot.json'), 'source_sha256': sha256(source / 'snapshot.json'),
                'adapter_hashes': adapter_hashes(), 'implementation_hashes': checkpoint.implementation_hashes(),
                'feature_schema_sha256': sha256(output / 'feature_schema.json'), 'derived_hashes': {}})
            (source / records[0]['file']).write_bytes(b'changed synthetic page')
            with self.assertRaisesRegex(ValueError, 'snapshot page changed'):
                checkpoint.develop(output)
            self.assertFalse((output / 'cache/development_examples.parquet').exists())

    def test_incidental_files_do_not_change_the_scientific_cache_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scientific = ('clean_api_measurements.parquet', 'hourly_inputs.parquet', 'potential.joblib')
            for name in scientific: (root / name).write_bytes(b'synthetic scientific artifact')
            for name in ('.DS_Store', '._hourly_inputs.parquet', 'Thumbs.db', 'desktop.ini'):
                (root / name).write_bytes(b'incidental metadata')
            before = prepared_cache_hashes(root)
            self.assertEqual(set(before), set(scientific))
            (root / '.DS_Store').write_bytes(b'changed incidental metadata')
            self.assertEqual(prepared_cache_hashes(root), before)
            (root / 'hourly_inputs.parquet').write_bytes(b'changed scientific artifact')
            self.assertNotEqual(prepared_cache_hashes(root)['hourly_inputs.parquet'], before['hourly_inputs.parquet'])


if __name__ == '__main__': unittest.main()
