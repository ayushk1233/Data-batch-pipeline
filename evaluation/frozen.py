"""Synthetic A2/B2 schema replay using unchanged supplied company configs.

Unlike generic hidden.py fixtures, these render exactly the public A/B mappings
and source semantics. No real rows or task labels are used in the generator.
"""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import random

from evaluation.hidden import ROOT, run_case, snapshot, digest
from evaluation.scenarios import CATALOG, write_csv


def generate_frozen(directory,kind,seed,size):
    directory=Path(directory).resolve();raw=directory/'raw';raw.mkdir(parents=True,exist_ok=True)
    config_path=directory/'config.json';config_path.write_bytes((ROOT/'configs'/f'{kind}.json').read_bytes())
    config=json.loads(config_path.read_text());rng=random.Random(seed)
    paths=sorted(set(tuple(p[:3])+('',) for p,*_ in CATALOG))
    columns=config['taxonomy']['columns']
    shuffled=paths.copy();rng.shuffle(shuffled)
    write_csv(raw/config['taxonomy']['file'],[dict(zip(columns,p[:len(columns)])) for p in shuffled],columns)
    tables={s['name']:[] for s in config['sources']};truth=[]
    for i in range(size):
        topic=rng.randrange(len(CATALOG));path,direct,paraphrase,translated=CATALOG[topic]
        path=tuple(path[:3])+('',)
        description=rng.choices([direct,paraphrase,translated,' '],[.66,.18,.12,.04])[0]
        nonproc=rng.random()<.04
        if nonproc:description='corporate income tax'
        net=Decimal(rng.randrange(1,1600)*20)*(Decimal(-1) if i%31==0 else Decimal(1))
        vendor=f'VS-{rng.randrange(20):03}';name=f'Fictional Wholesale {vendor[-3:]}'
        item=f'M-{topic:03}';po=str(950000000+i);invoice=f'INVOICE-{seed}-{i}'
        def expected(source,rid,why='',ns='shared'):
            truth.append({'record_id':source.get('prefix','')+rid,'include':not bool(why),'reason':why,
                          'spend':'0' if why else str(net),'path':list(path),
                          'supplier':f'{ns}:{vendor}','item':f'{ns}:{item}','informative':bool(description.strip()),'event_id':f'{seed}:{i}'})
        if kind=='A':
            erp,tool=config['sources'];has_erp=rng.random()<.8;has_tool=rng.random()<.78 if has_erp else True
            why='NON_PROCUREMENT' if nonproc else ''
            if has_erp:
                rid=f'E{i:07}'
                tables[erp['name']].append({'line_id':rid,'value_zar':str(net),'material_short_text':description,
                    'service_short_text':'','vendor_id':vendor,'supplier_name':name+' Ltd','material_number':item,
                    'po_number':po,'po_item':'10','receipt_document':f'RECEIPT-{seed}-{i}','receipt_item':'1',
                    'quantity':'1','uom':'EA','posting_date':'2024-02-29'})
                expected(erp,rid,why)
            if has_tool:
                rid=f'T{i:07}';status='Cancelled' if i%29==0 else 'On Hold' if i%41==0 else 'Paid'
                reason='CANCELLED' if status=='Cancelled' else 'NOT_APPROVED' if status=='On Hold' else why or ('DUPLICATE' if has_erp else '')
                vat=rng.choice(['0.15','15','15%','','0']);factor=Decimal(1) if vat=='0' else Decimal('1.15')
                row={'tool_record_id':rid,'gross_amount':str(net*factor),'line_text':description,
                     'supplier_name_as_captured':name,'po_reference':f'PO: {po} / 10','invoice_number':invoice,
                     'quantity':'1','invoice_date':'2024-02-29','vat_rate':vat,'currency':'ZAR','status':status}
                tables[tool['name']].append(row);expected(tool,rid,reason)
                if i%17==0:
                    repeated=dict(row,tool_record_id=f'Z{i:07}');tables[tool['name']].append(repeated)
                    expected(tool,repeated['tool_record_id'],reason or 'DUPLICATE')
        else:
            src=config['sources'][0];namespace=f'ERP-{i%4}'
            currency=rng.choice(['USD','EUR','ZAR']);rate={'USD':Decimal(1),'EUR':Decimal('.8'),'ZAR':Decimal(20)}[currency]
            rid=f'B{i:07}';why='NON_PROCUREMENT' if nonproc else ''
            tables[src['name']].append({'line_id':rid,'line_amount':str(net*rate),'line_description':description,
                'gl_account_description':'Intercompany' if nonproc else '', 'vendor_id':vendor,'material_number':item,
                'po_number':po,'po_line':'10','invoice_number':invoice,'invoice_line':'1','quantity':'1',
                'currency':currency,'currency_rate':str(rate) if i%2 and currency!='USD' else '',
                'invoice_date':'2024-02-29','source_system':namespace})
            expected(src,rid,why,namespace)
    for src in config['sources']:
        table=tables[src['name']]
        # Fixtures are nonempty by construction; schema follows rendered source.
        fields=list(table[0]) if table else [v for k,v in src['columns'].items() if isinstance(v,str)]
        write_csv(raw/src['file'],table,fields)
    if kind=='B':
        fx=config['fx'];write_csv(raw/fx['file'],[
            {'currency':'EUR','month':'2024-02','units_per_usd':'.8'},
            {'currency':'ZAR','month':'2024-02','units_per_usd':'20'}],['currency','month','units_per_usd'])
    truth_path=directory/'truth.json';truth_path.write_text(json.dumps(truth,indent=2))
    return {'kind':kind,'seed':seed,'events':size,'rows':len(truth),'raw':str(raw),'config':str(config_path),'truth':str(truth_path),'paths':[list(p) for p in paths]}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='private/frozen_schema_review')
    p.add_argument('--seed',type=int,default=260741);p.add_argument('--python');a=p.parse_args(argv)
    out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True);frozen=snapshot();runs=[]
    for kind,size in [('A',400),('B',600)]:
        case=generate_frozen(out/kind,kind,a.seed,size)
        result=run_case(case,out/kind/'results',a.python)
        result['unchanged_company_config']=digest(case['config'])==digest(ROOT/'configs'/f'{kind}.json')
        runs.append(result)
        print(json.dumps({'kind':kind,'rows':result['rows'],'returncode':result['returncode'],'metrics':result.get('metrics')}),flush=True)
    report={'snapshot_before':frozen,'snapshot_after':snapshot(),'runs':runs,'scope':'synthetic fresh events rendered into actual A/B schemas; configs copied byte-for-byte; no task rows or labels'}
    (out/'report.json').write_text(json.dumps(report,indent=2))
    return 0 if all(r['returncode']==0 for r in runs) else 1

if __name__=='__main__':raise SystemExit(main())
