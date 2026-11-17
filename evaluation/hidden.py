"""Reproducible self-authored holdout runner.

Run: PYTHONPATH=src:. python -m evaluation.hidden --output private/hidden_baseline
This is a synthetic review, not the organisers' hidden test. Truth is outside the
raw input directory and is loaded only after prediction has been saved/hashed.
The subprocess shares the user's filesystem permissions: this is process/input
separation, not an OS security sandbox. No claim of stronger isolation is made.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from evaluation.metrics import score_predictions, COLUMNS
from evaluation.scenarios import generate_case

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot():
    files=sorted((ROOT/'src').rglob('*.py'))+sorted((ROOT/'configs').glob('*'))
    files += sorted((ROOT/'evaluation').glob('*.py'))
    files += sorted(ROOT.glob('requirements*.txt'))
    files += [ROOT/'pyproject.toml'] if (ROOT/'pyproject.toml').exists() else []
    hashes={str(p.relative_to(ROOT)):digest(p) for p in files if p.is_file()}
    return {'files':hashes,'sha256':hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()}


def run_case(case,output,python_executable=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    prediction=output/'prediction.csv'
    env=dict(os.environ, PYTHONPATH=str(ROOT/'src'))
    # Invocation cwd contains only raw files, and package path only production.
    command=[python_executable or sys.executable,'-m','spend_pipeline','run','--config',case['config'],
             '--input-root',case['raw'],'--output',str(prediction),'--diagnostics',str(output/'diagnostics.json')]
    start=time.perf_counter()
    proc=subprocess.run(command,cwd=case['raw'],env=env,capture_output=True,text=True,timeout=3600)
    elapsed=time.perf_counter()-start
    result={'kind':case['kind'],'seed':case['seed'],'events':case['events'],'rows':case['rows'],
            'seconds':round(elapsed,4),'returncode':proc.returncode,'config_sha256':digest(case['config']),
            'input_sha256':{p.name:digest(p) for p in sorted(Path(case['raw']).glob('*')) if p.is_file()},
            'command':command,'stdout':proc.stdout[-2000:],'stderr':proc.stderr[-2000:]}
    if proc.returncode:
        return result
    # Persist prediction hash before opening any reference-answer file.
    result['prediction_sha256']=digest(prediction)
    (output/'prediction_hash.json').write_text(json.dumps({'prediction_sha256':result['prediction_sha256']}))
    with prediction.open(newline='',encoding='utf-8-sig') as h:
        reader=csv.DictReader(h);predictions=list(reader)
        result['columns']=reader.fieldnames
    truth=json.loads(Path(case['truth']).read_text())
    result['metrics']=score_predictions(truth,predictions,case['paths'])
    result['output_column_order_valid']=result['columns']==COLUMNS
    if not result['output_column_order_valid']:
        result['metrics']['contract_errors']['column_order']=1
    result['truth_sha256']=digest(case['truth'])
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='private/hidden_review')
    parser.add_argument('--seeds',nargs='+',type=int,default=[61027,80413,91909])
    parser.add_argument('--kinds',nargs='+',choices=['A','B','C'],default=['A','B','C'])
    parser.add_argument('--size',type=int)
    parser.add_argument('--classifier-mode',choices=['lexical','semantic','auto'],default='lexical')
    parser.add_argument('--python',dest='python_executable')
    args=parser.parse_args(argv)
    output=(ROOT/args.output).resolve(); output.mkdir(parents=True,exist_ok=True)
    frozen=snapshot()
    report={'protocol':'self-authored synthetic review; not an independent external blind test',
            'isolation':'truth excluded from raw directory; saved prediction hashed before truth load; same-user filesystem permissions, not OS sandbox',
            'snapshot_before_generation':frozen,'classifier_mode':args.classifier_mode,
            'environment':{'python':platform.python_version(),'platform':platform.platform(),'processor':platform.processor()},'runs':[]}
    (output/'freeze.json').write_text(json.dumps(frozen,indent=2))
    for seed in args.seeds:
        for kind in args.kinds:
            directory=output/f'{kind}_{seed}'
            case=generate_case(directory,kind,seed,args.size)
            if args.classifier_mode!='lexical':
                config=json.loads(Path(case['config']).read_text())
                config['classifier']={'mode':args.classifier_mode,'model':'sentence-transformers/LaBSE',
                    'revision':'836121a0533e5664b21c7aacc5d22951f2b8b25b','local_files_only':True,
                    'device':'cpu','batch_size':64,'max_length':128,'semantic_weight':.85}
                Path(case['config']).write_text(json.dumps(config,indent=2))
            result=run_case(case,directory/'results',args.python_executable)
            report['runs'].append(result)
            print(json.dumps({'kind':kind,'seed':seed,'rows':result['rows'],'seconds':result['seconds'],
                              'returncode':result['returncode'],
                              'exact_path_accuracy':result.get('metrics',{}).get('classification',{}).get('exact_path_accuracy'),
                              'spend_error':result.get('metrics',{}).get('financial',{}).get('signed_error')}),flush=True)
            (output/'report.json').write_text(json.dumps(report,indent=2))
    report['snapshot_after_scoring']=snapshot()
    report['implementation_unchanged_during_evaluation']=frozen==report['snapshot_after_scoring']
    (output/'report.json').write_text(json.dumps(report,indent=2))
    return 0 if all(r['returncode']==0 for r in report['runs']) else 1

if __name__=='__main__':
    raise SystemExit(main())
