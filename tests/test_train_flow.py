"""Exercise explicit CLI training and artifact-assisted inference end to end."""
import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec('sklearn'),'optional sklearn environment required')
class TrainingFlowTests(unittest.TestCase):
    def test_cli_requires_explicit_training_scope_then_runs_and_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);private=root/'private';private.mkdir()
            def csvfile(name,fields,rows):
                with (root/name).open('w',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            csvfile('tree.csv',['l1','l2'],[{'l1':'Equipment','l2':'Pumps'},{'l1':'Supplies','l2':'Towels'}])
            records=[{'id':str(i),'amount':'100','text':'circulating water impeller pump' if i%2 else 'cotton absorbent bath towel'} for i in range(20)]
            csvfile('lines.csv',['id','amount','text'],records)
            csvfile('labels.csv',['rid','top','leaf'],[{'rid':r['id'],'top':'Equipment' if int(r['id'])%2 else 'Supplies','leaf':'Pumps' if int(r['id'])%2 else 'Towels'} for r in records])
            config={'version':1,'reporting_currency':'USD','taxonomy':{'file':'tree.csv','columns':['l1','l2']},'sources':[{'name':'ledger','file':'lines.csv','columns':{'record_id':'id','amount':'amount','description':'text'},'currency':'USD','status':{'missing':'approved'}}],'classifier':{'mode':'lexical'}}
            config_path=root/'config.json';config_path.write_text(json.dumps(config));artifact=private/'model.pkl';out=root/'output.csv'
            env=dict(os.environ,PYTHONPATH=str(ROOT/'src'))
            command=[sys.executable,'-m','spend_pipeline','train','--config',str(config_path),'--input-root',str(root),'--labels',str(root/'labels.csv'),'--artifact',str(artifact),'--label-id-column','rid','--label-columns','top','leaf']
            fail=subprocess.run(command,env=env,capture_output=True,text=True)
            self.assertNotEqual(fail.returncode,0);self.assertFalse(artifact.exists())
            trained=subprocess.run(command+['--all-labels'],env=env,capture_output=True,text=True)
            self.assertEqual(trained.returncode,0,trained.stderr);self.assertEqual(json.loads(trained.stdout)['trained_records'],20)
            run=[sys.executable,'-m','spend_pipeline','run','--config',str(config_path),'--input-root',str(root),'--output',str(out),'--artifact',str(artifact)]
            predicted=subprocess.run(run,env=env,capture_output=True,text=True)
            self.assertEqual(predicted.returncode,0,predicted.stderr)
            summary=json.loads(predicted.stdout);self.assertEqual(summary['supervised']['replaced'],20)
            self.assertEqual(summary['total_spend'],'2000.00')
            with out.open() as stream:saved=list(csv.DictReader(stream))
            for row in saved:self.assertEqual(row['l2'],'Pumps' if int(row['record_id'])%2 else 'Towels')
            check=subprocess.run([sys.executable,'-m','spend_pipeline','validate','--config',str(config_path),'--input-root',str(root),'--output',str(out)],env=env,capture_output=True,text=True)
            self.assertEqual(check.returncode,0,check.stderr)
            artifact.unlink()
            rerun=subprocess.run(run,env=env,capture_output=True,text=True)
            self.assertNotEqual(rerun.returncode,0,'explicit requested artifact cannot silently disappear')


if __name__=='__main__':unittest.main()
