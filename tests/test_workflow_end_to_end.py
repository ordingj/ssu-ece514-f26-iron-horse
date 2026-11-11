"""Complete offline API workflow using explicitly synthetic sensor responses."""
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

from iron_horse import api_checkpoint as api

ROOT = Path(__file__).resolve().parents[1]


class SyntheticApiWorkflow(unittest.TestCase):
    def test_primary_commands_prepare_fit_freeze_score_and_verify_quality_snapshot(self):
        (ROOT/'runs').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'runs',prefix='synthetic-workflow-') as folder:
            root=Path(folder);source=root/'source';output=root/'output'
            rows=[]
            sites=[('SDI-12-LS-US915-1','P','upslope'),('SDI-12-LS-US915-2','Cc','downslope'),
                   ('SDI-12-LS-US915-4','B North','upslope'),('SDI-12-LS-US915-5','F','upslope')]
            for number,(device,block,slope) in enumerate(sites,1):
                for start in ['2026-01-29T08:00Z','2026-06-05T07:00Z','2026-07-10T07:00Z']:
                    for hour in range(120):
                        stamp=pd.Timestamp(start)+pd.Timedelta(hours=hour,minutes=30)
                        rows.append(dict(time=stamp.isoformat(),device_name=device,block=block,slope=slope,
                            dev_eui=f'{number:016x}',sensor=f'sensor-{number:024x}',
                            measurement='matric_potential_kpa',value=-600. if 72<=hour<84 else -400.,
                            response_format='meter_complete_frame',checksum_status='verified',
                            potential_quality='reported_kpa_calibration_not_validated',temperature_quality='numeric_field_complete'))
            uncertain=dict(rows[360]);uncertain.update(time='2026-01-29T08:01:00Z',value=-.1234,
                potential_quality='unknown_first_field_units',response_format='original_pair',checksum_status='not_present',
                temperature_quality='unknown_unit_and_incomplete_response')
            rows.append(uncertain)
            timed=[(pd.Timestamp(r['time']),r) for r in rows]
            def get(params):
                selected=[]
                if params['measurement']=='matric_potential_kpa':
                    left,right=pd.Timestamp(params['start']),pd.Timestamp(params['stop'])
                    selected=[r for stamp,r in timed if left<=stamp<right]
                return json.dumps(dict(source='influxdb-standby',start=params['start'],stop=params['stop'],
                    measurement=params['measurement'],limit=params['limit'],offset=0,next_offset=None,readings=selected)).encode()
            records=[];left=api.START
            while left<api.END:
                right=min(left+pd.Timedelta(days=7),api.END)
                for measurement in api.MEASUREMENTS:
                    records.extend(api.capture_window(measurement,left.isoformat(),right.isoformat(),source,get=get))
                left=right
            api.save_snapshot_json(source/'snapshot.json',dict(api=api.API,schema_version=2,quality_policy='reported-kpa-v1',
                start=api.START.isoformat(),stop=api.END.isoformat(),measurements=list(api.MEASUREMENTS),pages=records,
                fixture='synthetic; not physical vineyard observations'))
            for args in [('run','--snapshot',str(source),'--output',str(output),'--stage','all'),('verify',str(output))]:
                result=subprocess.run([sys.executable,'-W','error','-m','iron_horse',*args],cwd=ROOT,
                                      text=True,capture_output=True,timeout=120)
                self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
                if args[0]=='run':
                    second=root/'stage-verification';shutil.copytree(output,second)
            staged=subprocess.run([sys.executable,'-W','error','-m','iron_horse','run',
                '--output',str(second),'--stage','verify'],cwd=ROOT,text=True,capture_output=True,timeout=120)
            self.assertEqual(staged.returncode,0,staged.stdout+'\n'+staged.stderr)
            stage_receipt=json.loads((second/'independent_api_verification.json').read_text())
            self.assertTrue(stage_receipt['both_frozen_models_replay'])
            result=json.loads((output/'results.json').read_text())
            self.assertGreater(result['test_examples'],0)
            prep=json.loads((output/'preparation.json').read_text())
            self.assertEqual(prep['quality_policy'],'reported-kpa-v1')
            verification=json.loads((output/'independent_api_verification.json').read_text())
            self.assertTrue(verification['both_frozen_models_replay'])
            self.assertTrue(verification['all_labels_and_eligibility_match'])
            self.assertEqual(verification['unknown_unit_matric_keys_excluded'],1)
            self.assertEqual(verification['test_predictions'],result['test_examples'])
            frozen=json.loads((output/'model_freeze.json').read_text())
            unlocked=json.loads((output/'test_unlock.json').read_text())
            self.assertLess(frozen['frozen_at_utc'],unlocked['unlocked_at_utc'])


if __name__=='__main__':unittest.main()
