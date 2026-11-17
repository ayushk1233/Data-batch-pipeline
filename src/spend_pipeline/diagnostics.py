"""Private, auditable run evidence; never placed inside submission/."""
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from .config import PipelineError


def check_private_path(path):
    p = Path(path).resolve()
    if not any(part in {'private','diagnostics','runs'} for part in p.parts):
        raise PipelineError('Diagnostics must be stored below private/, diagnostics/, or runs/')
    if 'submission' in p.parts:
        raise PipelineError('Diagnostics cannot be written into submission/')
    return p


def write_diagnostics(path, records, summary):
    path = check_private_path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(summary,indent=2,default=str)+'\n',encoding='utf-8')
    detail = path.with_suffix('.records.jsonl')
    with detail.open('w',encoding='utf-8') as stream:
        for r in records:
            private = {k:v for k,v in r.items() if k not in ('_source_config','_settings')}
            stream.write(json.dumps(private,default=str,ensure_ascii=False)+'\n')


def summarize(records):
    sources = defaultdict(lambda:{'rows':0,'included':0,'spend':Decimal(0)})
    flags, reasons, fx = Counter(), Counter(), Counter()
    for r in records:
        s = sources[r['source']]
        s['rows'] += 1
        s['included'] += int(r['include'])
        s['spend'] += r['spend'] if r['include'] else 0
        flags.update(r['flags'])
        reasons[r['exclusion_reason'] or 'INCLUDED'] += 1
        fx[r.get('fx_provenance','excluded')] += 1
    return {'sources':dict(sources),'quality_flags':dict(flags),'reasons':dict(reasons),'fx_provenance':dict(fx),'estimated_included_spend':str(sum((r['spend'] for r in records if r['include'] and any(f.startswith('estimated_amount:') for f in r['flags'])),Decimal(0)))}
