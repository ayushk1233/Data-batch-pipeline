"""Cold-process 25k-row test with distinct evidence, avoiding duplicate-text cache gains."""
import argparse
import csv
import json
from pathlib import Path

from evaluation.hidden import ROOT, run_case, snapshot
from evaluation.scenarios import generate_case, write_csv


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='private/scale_unique_semantic')
    p.add_argument('--rows',type=int,default=25000);p.add_argument('--python');p.add_argument('--mode',choices=['lexical','semantic'],default='semantic')
    a=p.parse_args(argv);directory=Path(a.output).resolve();directory.mkdir(parents=True,exist_ok=True)
    frozen=snapshot();case=generate_case(directory,'C',427109,a.rows)
    file=Path(case['raw'])/'invoices.csv'
    with file.open(newline='') as h:
        reader=csv.DictReader(h);rows=list(reader);fields=reader.fieldnames
    truth=json.loads(Path(case['truth']).read_text());events=json.loads((directory/'events.json').read_text())
    event_map={r['event_id']:r for r in events}
    for i,(row,gold) in enumerate(zip(rows,truth)):
        row['memo']=row['memo'].strip()+f' specification capacity {i+101} units revision {i+71}'
        row['status']='Paid';row['supplier_type']='trade'
        gold['include']=True;gold['reason']='';gold['spend']=event_map[gold['event_id']]['net']
    write_csv(file,rows,fields);Path(case['truth']).write_text(json.dumps(truth,indent=2))
    config=json.loads(Path(case['config']).read_text())
    config['classifier']={'mode':a.mode,'model':'sentence-transformers/LaBSE',
        'revision':'836121a0533e5664b21c7aacc5d22951f2b8b25b','local_files_only':True,
        'device':'cpu','batch_size':64,'max_length':128,'semantic_weight':.85}
    Path(case['config']).write_text(json.dumps(config,indent=2))
    result=run_case(case,directory/'results',a.python)
    diagnostics=directory/'results'/'diagnostics.json'
    if diagnostics.exists():
        d=json.loads(diagnostics.read_text());result['pipeline_summary']=d.get('summary',d)
    result['snapshot_before']=frozen;result['snapshot_after']=snapshot()
    result['scope']='cold subprocess including model load, local assets already installed; 25k distinct evidence strings; all rows included; synthetic throughput, not independent quality test'
    result['unique_raw_descriptions']=len({r['memo'] for r in rows})
    result['within_60_minutes']=result['returncode']==0 and result['seconds']<3600
    (directory/'report.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:result[k] for k in ['rows','seconds','returncode','unique_raw_descriptions','within_60_minutes']},indent=2))
    return 0 if result['within_60_minutes'] else 1

if __name__=='__main__':raise SystemExit(main())
