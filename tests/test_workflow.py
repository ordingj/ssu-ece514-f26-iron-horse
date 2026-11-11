"""Synthetic quality-contract checks and public command behavior."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError

from iron_horse import api_checkpoint as api

ROOT = Path(__file__).resolve().parents[1]


class WorkflowCommands(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, '-W', 'error', '-m', 'iron_horse', *args],
                              cwd=ROOT, text=True, capture_output=True)

    def test_default_summary_is_the_recorded_api_run_with_its_quality_status(self):
        r = self.invoke('summary')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('1638', r.stdout)
        self.assertIn('InfluxDB API', r.stdout)
        self.assertIn('reported-kpa-v1', r.stdout)
        self.assertNotIn('pending', r.stdout)

    def test_run_help_is_api_first_and_csv_is_explicit(self):
        r = self.invoke('run', '--help')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--snapshot', r.stdout)
        self.assertNotIn('--source ', r.stdout)
        old = self.invoke('legacy-csv', '--help')
        self.assertEqual(old.returncode, 0, old.stderr)
        self.assertIn('--source', old.stdout)

    def test_primary_verifier_refuses_recorded_aggregate_mutation(self):
        r = self.invoke('verify', 'results/api-checkpoint-2026-11-05')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('read-only', r.stderr)

    def test_unscored_run_summary_reports_the_reason_without_inventing_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'results.json').write_text(json.dumps({'status':'not_evaluable',
                'reason':'Training and validation must each contain both classes'}))
            result=self.invoke('summary','--folder',str(root))
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('not_evaluable',result.stdout)
            self.assertIn('both classes',result.stdout)
            self.assertNotIn('Baseline F1:',result.stdout)


class QualityContract(unittest.TestCase):
    start = '2026-08-25T07:00:00+00:00'
    stop = '2026-08-25T08:00:00+00:00'

    def row(self, **changes):
        row = dict(time='2026-08-25T07:02:00.000000001Z', measurement='matric_potential_kpa',
            value=-510., sensor='sensor-aaaaaaaaaaaaaaaaaaaaaaaa', dev_eui='a8404185fc5c53fe',
            device_name='SDI-12-LS-US915-2', block='Cc', slope='downslope',
            response_format='original_pair', checksum_status='not_present',
            potential_quality='reported_kpa_calibration_not_validated',
            temperature_quality='numeric_field_complete')
        row.update(changes)
        return row

    def page(self, params, rows):
        return dict(source='influxdb-standby', start=params['start'], stop=params['stop'],
            measurement=params['measurement'], limit=params['limit'], offset=params['offset'],
            next_offset=None, readings=rows)

    def snapshot(self, root, rows):
        requests=[]
        def get(params):
            requests.append(dict(params));return json.dumps(self.page(params, rows)).encode()
        records=api.capture_window('matric_potential_kpa',self.start,self.stop,root,get=get)
        (root/'snapshot.json').write_text(json.dumps({'pages':records}))
        return requests

    def test_unknown_units_are_excluded_and_supported_framed_values_are_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'output';out.mkdir()
            requests=self.snapshot(root,[self.row(value=-.1234,potential_quality='unknown_first_field_units'),
                self.row(time='2026-08-25T07:03:00Z',response_format='historical_v_terminated_pair',checksum_status='unavailable')])
            self.assertEqual(requests[0].get('include_quality'),'true')
            clean=api.clean_snapshot(root,root/'clean.parquet')
            _,potential=api.build_inputs(clean,out)
            self.assertEqual(potential['SDI-12-LS-US915-2'][1].tolist(),[-510.])
            audit=json.loads((out/'decode_audit.json').read_text())
            self.assertEqual(audit['SDI-12-LS-US915-2']['unknown_unit_keys_excluded'],1)

    def test_missing_unknown_and_inconsistent_quality_provenance_are_rejected(self):
        missing=self.row();del missing['potential_quality']
        bad=[missing,self.row(potential_quality='assumed_kpa'),self.row(value=-9999.),self.row(value=-9992.),
             self.row(response_format='meter_complete_frame',checksum_status='unavailable')]
        for row in bad:
            with self.subTest(row=row),tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError,'quality|checksum'):
                    self.snapshot(Path(folder),[row])

    def test_conflicting_quality_marks_the_entire_observation_key_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.snapshot(root,[self.row(),self.row(potential_quality='unknown_first_field_units')])
            clean=api.clean_snapshot(root,root/'clean.parquet')
            self.assertFalse(clean['valid_key'][0])

    def test_old_snapshot_fails_before_reading_any_source_page(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'snapshot.json').write_text(json.dumps({'pages':[{'file':'absent.gz','request':{
                'measurement':'matric_potential_kpa','include_metadata':'true'}}]}))
            with self.assertRaisesRegex(ValueError,'quality'):
                api.verify_snapshot(root)

    def test_capability_probe_accepts_explicit_supported_provenance(self):
        def get(params):
            self.assertEqual(params['include_quality'],'true')
            self.assertEqual(params['include_metadata'],'true')
            return json.dumps(self.page(params,[self.row()])).encode()
        report=api.check_api(get=get)
        self.assertTrue(report['quality_contract_supported'])
        self.assertEqual(report['quality_policy'],'reported-kpa-v1')
        self.assertEqual(report['sample_readings'],1)

    def test_capability_probe_reports_unsupported_live_contract(self):
        def get(params):
            self.assertEqual(params['include_quality'],'true')
            raise HTTPError('https://example.invalid',400,'unsupported',{},None)
        with self.assertRaisesRegex(ValueError,'quality'):
            api.check_api(get=get)


if __name__=='__main__':unittest.main()
