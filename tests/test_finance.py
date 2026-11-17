"""Independent arithmetic oracles and failure policies across the complete flow."""
import csv
import json
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from spend_pipeline.normalize import parse_decimal,parse_date,parse_vat
from spend_pipeline.config import PipelineError,validate_config,input_path
from spend_pipeline.pipeline import run_pipeline,validate_pipeline_output
from spend_pipeline.export import COLUMNS,validate_rows


class FinancialTests(unittest.TestCase):
    def test_localised_signed_amounts(self):
        cases=[('1,234.56','.',',','1234.56'),('1.234,56',',','.','1234.56'),('(1,234.56)','.',',','-1234.56'),('−12.50','.',',','-12.50'),('1 234,50',',',' ','1234.50'),('0','.',',','0')]
        for text,dec,sep,want in cases:
            with self.subTest(text=text):self.assertEqual(parse_decimal(text,dec,sep),Decimal(want))
        for bad in ('NaN','inf','1,2,3','1.2.3','abc','--5','(-1)','(+1)'):
            with self.subTest(bad=bad),self.assertRaises(PipelineError):parse_decimal(bad)
        self.assertIsNone(parse_decimal('  '))

    def test_tax_fraction_percent_integer_default_and_zero(self):
        for text in ('0.15','15','15%','15,0%',''):
            self.assertEqual(parse_vat(text,'15%'),Decimal('.15'))
        self.assertEqual(parse_vat('0','15%'),0)
        self.assertEqual(parse_vat('0%','15%'),0)
        for text in ('-1','abc','150%'):
            with self.assertRaises(PipelineError):parse_vat(text,'15%')
        with self.assertRaises(PipelineError):parse_vat('',None)

    def test_dates_follow_explicit_order_without_fabrication(self):
        self.assertEqual(str(parse_date('03/04/2024',['%d/%m/%Y','%m/%d/%Y'])),'2024-04-03')
        self.assertEqual(str(parse_date('2024-02-29',['%Y-%m-%d'])),'2024-02-29')
        self.assertIsNone(parse_date('2023-02-29',['%Y-%m-%d']))
        self.assertIsNone(parse_date('',['%Y-%m-%d']))


class FullFinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.raw=self.root/'raw';self.raw.mkdir()
        self.config={'version':1,'reporting_currency':'USD','taxonomy':{'file':'tree.csv','columns':['one','two']},'sources':[{'name':'ledger','file':'lines.csv','columns':{'record_id':'id','amount':'amount','quantity':'qty','item_id':'item','description':'text','supplier_id':'vendor','date':'date','currency':'currency','fx_rate':'rate','status':'status','vat_rate':'vat'},'currency':'USD','status':{'missing':'approved','approved':['approved','paid'],'cancelled':['cancelled']},'date_formats':['%Y-%m-%d'],'amount_semantics':'net'}],'classifier':{'mode':'lexical'}}
        self.write('tree.csv',[{'one':'Equipment','two':'Pumps'}])
        self.base={'id':'1','amount':'100','qty':'1','item':'pump','text':'pump','vendor':'one','date':'2024-02-29','currency':'USD','rate':'','status':'paid','vat':''}

    def write(self,name,rows):
        with (self.raw/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

    def run_flow(self,rows):
        self.write('lines.csv',rows);self.path=self.root/'config.json';self.path.write_text(json.dumps(self.config))
        self.output=self.root/'output.csv'
        result=run_pipeline(self.path,self.raw,self.output)
        with self.output.open() as f:saved=list(csv.DictReader(f))
        return result,saved

    def test_all_vat_encodings_and_credit_rounding_end_to_end(self):
        self.config['sources'][0].update(amount_semantics='gross',default_vat='15%')
        rows=[dict(self.base,id=str(i),amount='115',vat=v) for i,v in enumerate(['15%','15','0.15','','0'])]
        rows += [dict(self.base,id='credit',amount='(115)',vat='15%')]
        _,saved=self.run_flow(rows)
        self.assertEqual([r['spend'] for r in saved],['100.00']*4+['115.00','-100.00'])
        self.assertEqual([r['include'] for r in saved],['1']*6)

    def test_fx_divide_line_month_usd_ignores_rate_and_credit(self):
        self.config['fx']={'file':'fx.csv','currency_column':'currency','month_column':'month','rate_column':'rate','direction':'units_per_reporting'}
        self.write('fx.csv',[{'currency':'EUR','month':'2024-02','rate':'0.8'}])
        _,saved=self.run_flow([dict(self.base,id='usd',rate='0'),dict(self.base,id='line',currency='EUR',amount='80',rate='0.8'),dict(self.base,id='fallback',currency='EUR',amount='80',rate='0'),dict(self.base,id='credit',currency='EUR',amount='-80',rate='')])
        self.assertEqual([r['spend'] for r in saved],['100.00','100.00','100.00','-100.00'])

    def test_strict_fx_missing_month_fails_and_explicit_estimate_is_flagged(self):
        self.config['fx']={'file':'fx.csv','currency_column':'currency','month_column':'month','rate_column':'rate'}
        self.write('fx.csv',[{'currency':'EUR','month':'2024-03','rate':'0.8'}])
        row=dict(self.base,currency='EUR',amount='80')
        with self.assertRaises(PipelineError):self.run_flow([row])
        self.assertFalse(self.output.exists())
        self.config['financial']={'missing_fx':'nearest_month','max_fx_gap_months':1}
        result,saved=self.run_flow([row])
        self.assertEqual(saved[0]['spend'],'100.00')
        self.assertEqual(result['quality_flags']['estimated_fx:nearest_month'],1)
        self.config['financial']['max_fx_gap_months']=0
        with self.assertRaises(PipelineError):self.run_flow([row])

    def test_missing_amount_strict_and_reporting_unit_estimate_not_currency_mix(self):
        self.config['fx']={'file':'fx.csv','currency_column':'currency','month_column':'month','rate_column':'rate'}
        self.write('fx.csv',[{'currency':'EUR','month':'2024-02','rate':'0.8'}])
        rows=[dict(self.base,id='one',amount='80',currency='EUR'),dict(self.base,id='two',amount='100',currency='USD'),dict(self.base,id='missing',amount='',qty='2',currency='EUR')]
        with self.assertRaises(PipelineError):self.run_flow(rows)
        self.config['financial']={'missing_amount':'estimate_unit_median'}
        result,saved=self.run_flow(rows)
        self.assertEqual(saved[-1]['spend'],'200.00')
        self.assertEqual(result['quality_flags']['estimated_amount:group_unit_median'],1)
        rows[-1]['item']='unseen'
        with self.assertRaises(PipelineError):self.run_flow(rows)

    def test_status_precedence_and_missing_financials_on_excluded(self):
        self.config['non_procurement']=[{'field':'text','values':['statutory remittance']}]
        rows=[dict(self.base,id='cancel',status='cancelled',text='statutory remittance',amount=''),dict(self.base,id='hold',status='on hold',text='statutory remittance'),dict(self.base,id='tax',text='statutory remittance'),dict(self.base,id='advisory',text='tax advisory services')]
        _,saved=self.run_flow(rows)
        self.assertEqual([r['exclusion_reason'] for r in saved],['CANCELLED','NOT_APPROVED','NON_PROCUREMENT',''])
        for r in saved[:3]:
            self.assertEqual(r['spend'],'0.00');self.assertFalse(any(r[k] for k in ['l1','l2','l3','l4']))

    def test_validation_replays_finance_and_eligibility(self):
        _,saved=self.run_flow([self.base])
        saved[0]['spend']='99.00'
        with self.output.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=COLUMNS);w.writeheader();w.writerows(saved)
        with self.assertRaisesRegex(PipelineError,'spend differs'):validate_pipeline_output(self.path,self.raw,self.output)

    def test_input_path_cannot_escape_to_labels(self):
        with self.assertRaises(PipelineError):input_path(self.raw,'../truth.json')

    def test_unknown_numeric_matching_settings_rejected(self):
        for key,value in [('amount_tolerance','NaN'),('amount_tolerance','-1'),('amount_relative_tolerance','Infinity'),('description_threshold',1.01),('supplier_threshold',-.1),('max_candidates',0),('max_candidates',1.5),('date_window_days',-1),('enabled','false')]:
            c=deepcopy(self.config);c['matching']={key:value}
            with self.subTest(key=key,value=value),self.assertRaises(PipelineError):validate_config(c)


if __name__=='__main__':unittest.main()
