"""End-to-end CLI tests use independently generated truth, not implementation helpers."""
import csv
from decimal import Decimal
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

from evaluation.metrics import score_predictions, grouping_metrics
from evaluation.real import evaluate_saved
from evaluation.scenarios import generate_case, write_csv, source, base_config, FIELDS

ROOT=Path(__file__).resolve().parents[1]


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work=Path(self.temporary.name)

    def invoke(self, case, output=None, command='run'):
        output=Path(output or self.work/'output.csv')
        proc=subprocess.run([sys.executable,'-m','spend_pipeline',command,
                             '--config',case['config'],'--input-root',case['raw'],'--output',str(output)],
                            env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),
                            cwd=self.work,capture_output=True,text=True,timeout=90)
        return proc,output

    def saved_rows(self,path):
        with path.open(encoding='utf-8-sig',newline='') as h:return list(csv.DictReader(h))

    def case(self,kind='C',size=80):
        return generate_case(self.work/kind,kind,43187,size)

    def test_config_only_unseen_four_level_company_preserves_full_contract(self):
        case=self.case()
        proc,path=self.invoke(case)
        self.assertEqual(proc.returncode,0,proc.stderr)
        predictions=self.saved_rows(path)
        truth=json.loads(Path(case['truth']).read_text())
        score=score_predictions(truth,predictions,case['paths'])
        self.assertEqual(score['contract_errors'],{})
        self.assertEqual(score['rows'],80)
        self.assertEqual(score['financial']['lines_within_one_cent'],80)
        self.assertEqual(score['inclusion']['legitimate_rows_removed'],0)
        self.assertTrue(any(p['l4'] for p in predictions if p['include']=='1'))
        self.assertTrue(any(not p['l4'] for p in predictions if p['include']=='1'))
        validated,_=self.invoke(case,path,'validate')
        self.assertEqual(validated.returncode,0,validated.stderr)

    def test_multicurrency_line_rate_month_fallback_credits_and_bad_optional_dates(self):
        case=self.case('B',150)
        proc,path=self.invoke(case)
        self.assertEqual(proc.returncode,0,proc.stderr)
        score=score_predictions(json.loads(Path(case['truth']).read_text()),self.saved_rows(path),case['paths'])
        self.assertEqual(score['financial']['lines_within_one_cent'],150)
        self.assertEqual(Decimal(score['financial']['signed_error']),0)
        self.assertEqual(score['contract_errors'],{})
        self.assertEqual(score['inclusion']['legitimate_rows_removed'],0)

    def test_two_sources_count_once_reexports_vat_and_cancelled_capacity(self):
        raw=self.work/'raw';raw.mkdir()
        write_csv(raw/'taxonomy.csv',[{'l1':'Facilities','l2':'Plumbing','l3':'Water pumps','l4':''}],['l1','l2','l3','l4'])
        erp=source('erp','erp.csv','ERP:',0)
        tool=source('tool','tool.csv','TOOL:',1,True)
        config=base_config([erp,tool]);config_path=self.work/'config.json';config_path.write_text(json.dumps(config))
        def row(identifier,amount,po,invoice,status='Paid',vat=''):
            r={k:'' for k in FIELDS}
            r.update(line_id=identifier,amount=amount,description='water pump',vendor='vendor-1',supplier='Example Pumps Ltd',
                     material='pump-25mm',po=po,po_item='10',invoice=invoice,invoice_line='1',receipt='R-'+identifier,
                     qty='1',currency='USD',invoice_date='2024-02-29',status=status,vat=vat,supplier_type='trade')
            return r
        write_csv(raw/'erp.csv',[row('e1','100','PO-1','INV-1'),row('e2','100','PO-2','INV-2')],FIELDS)
        t1=row('t1','115','PO-1','INV-1',vat='15%');t1['receipt']=''
        t2=row('t2','230','PO-3','INV-3',vat='15');t2['receipt']=''
        repeated=dict(t2);repeated['line_id']='z2'
        cancelled=row('t3','115','PO-2','INV-2','Cancelled','0.15');cancelled['receipt']=''
        write_csv(raw/'tool.csv',[t1,t2,repeated,cancelled],FIELDS)
        proc,path=self.invoke({'config':str(config_path),'raw':str(raw)})
        self.assertEqual(proc.returncode,0,proc.stderr)
        saved={r['record_id']:r for r in self.saved_rows(path)}
        self.assertEqual(len(saved),6)
        self.assertEqual(saved['TOOL:t1']['exclusion_reason'],'DUPLICATE')
        self.assertEqual(saved['TOOL:z2']['exclusion_reason'],'DUPLICATE')
        self.assertEqual(saved['TOOL:t3']['exclusion_reason'],'CANCELLED')
        self.assertEqual(saved['ERP:e2']['include'],'1')
        self.assertEqual(sum(Decimal(r['spend']) for r in saved.values()),Decimal('400'))

    def test_shuffled_source_and_tree_have_same_per_record_decisions(self):
        case=self.case('B',100)
        first,path=self.invoke(case,self.work/'first.csv')
        self.assertEqual(first.returncode,0,first.stderr)
        before={r['record_id']:r for r in self.saved_rows(path)}
        for file in Path(case['raw']).glob('*.csv'):
            with file.open(newline='') as h:
                reader=csv.DictReader(h);rows=list(reader);fields=reader.fieldnames
            random.Random(71).shuffle(rows);write_csv(file,rows,fields)
        second,path=self.invoke(case,self.work/'second.csv')
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(before,{r['record_id']:r for r in self.saved_rows(path)})

    def test_input_root_relocation_does_not_change_namespace_or_output(self):
        case=self.case('B',35)
        first,path=self.invoke(case,self.work/'first.csv')
        self.assertEqual(first.returncode,0,first.stderr)
        expected={r['record_id']:r for r in self.saved_rows(path)}
        shutil.copytree(case['raw'],self.work/'relocated')
        case['raw']=str(self.work/'relocated')
        second,path=self.invoke(case,self.work/'second.csv')
        self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(expected,{r['record_id']:r for r in self.saved_rows(path)})

    def test_missing_amount_fails_without_publishing_partial_output(self):
        case=self.case(size=12);file=Path(case['raw'])/'invoices.csv'
        with file.open(newline='') as h:
            reader=csv.DictReader(h);rows=list(reader);fields=reader.fieldnames
        rows[1]['net_total']='not-an-amount';rows[1]['status']='Approved';rows[1]['supplier_type']='trade'
        write_csv(file,rows,fields)
        proc,path=self.invoke(case)
        self.assertNotEqual(proc.returncode,0)
        self.assertFalse(path.exists(),'failed runs must not publish plausible partial CSVs')

    def test_duplicate_record_ids_fail_before_output(self):
        case=self.case(size=12);file=Path(case['raw'])/'invoices.csv'
        with file.open(newline='') as h:
            reader=csv.DictReader(h);rows=list(reader);fields=reader.fieldnames
        rows[1]['transaction_ref']=rows[0]['transaction_ref'];write_csv(file,rows,fields)
        proc,path=self.invoke(case)
        self.assertNotEqual(proc.returncode,0)
        self.assertFalse(path.exists())

    def test_unknown_config_keys_fail_instead_of_being_ignored(self):
        case=self.case(size=1);config=Path(case['config'])
        data=json.loads(config.read_text());data['silently_ignore_this']=True;config.write_text(json.dumps(data))
        proc,path=self.invoke(case)
        self.assertNotEqual(proc.returncode,0)
        self.assertFalse(path.exists())

    def test_validator_rejects_tampered_amount_and_path(self):
        case=self.case(size=12)
        proc,path=self.invoke(case)
        self.assertEqual(proc.returncode,0,proc.stderr)
        rows=self.saved_rows(path)
        target=next(r for r in rows if r['include']=='1');target['spend']='NaN';target['l4']='not in taxonomy'
        write_csv(path,rows,list(rows[0]))
        checked,_=self.invoke(case,path,'validate')
        self.assertNotEqual(checked.returncode,0)

    def test_grouping_metrics_penalise_false_merges_and_singletons(self):
        merged=grouping_metrics([('one','all'),('one','all'),('two','all'),('two','all')])
        singletons=grouping_metrics([('one','a'),('one','b'),('two','c'),('two','d')])
        self.assertAlmostEqual(merged['pairwise_precision'],1/3)
        self.assertEqual(merged['pairwise_recall'],1)
        self.assertEqual(singletons['pairwise_recall'],0)
        self.assertEqual(singletons['bcubed_recall'],.5)

    def test_optional_missing_model_falls_back_locally_without_keys(self):
        case=self.case(size=15);config=Path(case['config']);data=json.loads(config.read_text())
        data['classifier']={'mode':'auto','model':'/nonexistent/offline/local/encoder','local_files_only':True}
        config.write_text(json.dumps(data))
        proc,path=self.invoke(case)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(len(self.saved_rows(path)),15)
        self.assertEqual(json.loads(proc.stdout)['classification']['mode'],'lexical')

    def test_explicit_missing_semantic_model_fails_without_partial_export(self):
        case=self.case(size=15);config=Path(case['config']);data=json.loads(config.read_text())
        data['classifier']={'mode':'semantic','model':'/nonexistent/offline/local/encoder','local_files_only':True}
        config.write_text(json.dumps(data))
        proc,path=self.invoke(case)
        self.assertNotEqual(proc.returncode,0)
        self.assertFalse(path.exists())

    def test_saved_label_evaluation_counts_exclusions_without_category_paths(self):
        predictions=[dict(record_id='included',include='1',exclusion_reason='',supplier_key='s',item_key='i',
                          spend='100',l1='Goods',l2='Pumps',l3='',l4='',confidence='.7'),
                     dict(record_id='excluded',include='0',exclusion_reason='NON_PROCUREMENT',supplier_key='s',item_key='e',
                          spend='0',l1='',l2='',l3='',l4='',confidence='0')]
        labels=[dict(line_id='included',include='1',exclusion_reason='',category_l1='Goods',category_l2='Pumps',category_l3=''),
                dict(line_id='excluded',include='0',exclusion_reason='NON_PROCUREMENT',category_l1='',category_l2='',category_l3='')]
        prediction_path=self.work/'prediction.csv';label_path=self.work/'labels.csv'
        write_csv(prediction_path,predictions,list(predictions[0]));write_csv(label_path,labels,list(labels[0]))
        result=evaluate_saved(prediction_path,label_path)
        self.assertEqual(result['matched_label_rows'],2)
        self.assertEqual(result['matched_labelled_paths'],1)
        self.assertEqual(result['supplied_inclusion_labels']['support'],2)
        self.assertEqual(result['supplied_inclusion_labels']['macro_f1'],1)
        self.assertEqual(result['classification']['exact_path_accuracy'],1)
        self.assertIsNone(result['classification']['spend_weighted_exact_accuracy'])

    def test_end_to_end_metrics_keep_wrongly_removed_credits_in_denominator(self):
        path_a=('Goods','Pumps','','');path_b=('Goods','Valves','','')
        truth=[{'record_id':'a','include':True,'reason':'','spend':'100','path':path_a},
               {'record_id':'b','include':True,'reason':'','spend':'-100','path':path_b}]
        def prediction(identifier,included,path,spend,reason=''):
            result=dict(record_id=identifier,include='1' if included else '0',exclusion_reason=reason,
                        supplier_key='s',item_key=identifier,spend=spend,confidence='.5')
            result.update({f'l{i+1}':name for i,name in enumerate(path)})
            return result
        predictions=[prediction('a',True,path_a,'100'),prediction('b',False,('','','',''),'0','DUPLICATE')]
        result=score_predictions(truth,predictions,[path_a,path_b])
        self.assertEqual(result['classification']['support'],2)
        self.assertEqual(result['classification']['spend_weighted_exact_accuracy'],.5)
        self.assertEqual(result['inclusion']['legitimate_rows_removed'],1)
        self.assertEqual(result['duplicates']['precision'],0)


if __name__=='__main__':unittest.main()
