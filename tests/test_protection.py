"""Prevent accidental raw-input exposure/overwrite and validate packaging guards."""
import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from spend_pipeline.pipeline import run_pipeline
from spend_pipeline.config import PipelineError

ROOT=Path(__file__).resolve().parents[1]


class ProtectionTests(unittest.TestCase):
    def test_ignore_rules_keep_private_inputs_out_but_allow_required_outputs(self):
        with tempfile.TemporaryDirectory() as work:
            path=Path(work)
            subprocess.run(['git','init','--quiet',work],check=True,capture_output=True)
            (path/'.gitignore').write_text((ROOT/'.gitignore').read_text())
            ignored=['company_A/raw.csv','company_B/taxonomy.csv','company_C/inputs.csv','Cantill_DataML_Task_Brief.pdf','plan.md','AGENTS.md','private/splits.json','models/trained.pkl','diagnostics/trace.json','data/raw.csv','.env','secret.key']
            visible=['src/spend_pipeline/pipeline.py','README.md','submission/Ayush_Kumar__A.csv','submission/Ayush_Kumar__B.csv','submission/Ayush_Kumar__A2.csv','submission/Ayush_Kumar__B2.csv','submission/Ayush_Kumar__C.csv','submission/C.json']
            result=subprocess.run(['git','-C',work,'check-ignore','--no-index','--stdin'],input='\n'.join(ignored+visible)+'\n',text=True,capture_output=True,check=True)
            self.assertEqual(set(result.stdout.splitlines()),set(ignored))

    def test_output_cannot_overwrite_raw_config_or_taxonomy(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work)
            raw='id,amount,text\n1,100,pump\n';tree='l1\nPumps\n'
            (root/'rows.csv').write_text(raw);(root/'tree.csv').write_text(tree)
            config={'version':1,'reporting_currency':'USD','taxonomy':{'file':'tree.csv','columns':['l1']},'sources':[{'name':'x','file':'rows.csv','columns':{'record_id':'id','amount':'amount','description':'text'},'currency':'USD','status':{'missing':'approved'}}]}
            (root/'config.json').write_text(json.dumps(config))
            for filename in ('rows.csv','tree.csv','config.json'):
                target=root/filename;before=target.read_bytes()
                with self.subTest(filename=filename),self.assertRaises(PipelineError):run_pipeline(root/'config.json',root,target)
                self.assertEqual(target.read_bytes(),before)

    def test_production_does_not_import_evaluator_or_read_labels(self):
        for path in (ROOT/'src/spend_pipeline').glob('*.py'):
            if path.name in ('cli.py','supervised.py'):
                continue  # Explicit evaluation/train commands are separate user actions.
            text=path.read_text()
            self.assertNotIn('from evaluation',text,path)
            self.assertNotIn('labels_A.csv',text,path)
            self.assertNotIn('seed_labels.csv',text,path)


if __name__=='__main__':unittest.main()
