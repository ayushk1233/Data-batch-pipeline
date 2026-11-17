"""Unattended, data-only-config ingestion through validated atomic export."""
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from .config import PipelineError, load_config, input_path
from .ingest import ingest
from .finance import calculate_financials
from .entities import resolve_entities
from .matching import match_records
from .classify import load_taxonomy, classify_records
from decimal import Decimal
import csv
from .export import output_rows, validate_rows, validate_file, write_output
from .diagnostics import summarize, write_diagnostics, check_private_path


def code_fingerprint():
    h = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def run_pipeline(config_path, input_root, output_path, diagnostics_path=None, artifact_path=None):
    start = time.perf_counter()
    if diagnostics_path:
        check_private_path(diagnostics_path)
    config = load_config(config_path)
    protected = {Path(config_path).resolve()}
    protected.update(input_path(input_root,s['file']) for s in config['sources'])
    protected.add(input_path(input_root,config['taxonomy']['file']))
    if 'fx' in config:
        protected.add(input_path(input_root,config['fx']['file']))
    output_resolved = Path(output_path).resolve()
    if output_resolved in protected:
        raise PipelineError('Output path would overwrite an input or config file')
    if diagnostics_path:
        diagnostic = Path(diagnostics_path).resolve()
        if diagnostic in protected or diagnostic.with_suffix('.records.jsonl') in protected or output_resolved in (diagnostic,diagnostic.with_suffix('.records.jsonl')):
            raise PipelineError('Diagnostics/output paths collide with protected files')
    tax = config['taxonomy']
    paths = load_taxonomy(input_path(input_root,tax['file']),tax['columns'])
    timings = {}
    tick = time.perf_counter()
    records, manifests = ingest(config,input_root)
    timings['ingest'] = time.perf_counter()-tick
    expected_ids = [r['record_id'] for r in records]
    tick = time.perf_counter()
    calculate_financials(records,config,input_root)
    timings['finance_eligibility'] = time.perf_counter()-tick
    tick = time.perf_counter()
    resolve_entities(records,config)
    matching = match_records(records,config) if config.get('matching',{}).get('enabled',True) else {'disabled':True}
    timings['entities_matching'] = time.perf_counter()-tick
    tick = time.perf_counter()
    classification = classify_records(records,paths,config.get('classifier',{}))
    supervised = {'mode':'fallback','reason':'not_configured','replaced':0}
    if artifact_path is not None:
        from .supervised import apply_model
        supervised = apply_model(records,paths,artifact_path,{'required':True})
    timings['classification'] = time.perf_counter()-tick
    tick = time.perf_counter()
    rows = output_rows(records)
    validation = validate_rows(rows,expected_ids,paths)
    write_output(output_path,rows)
    validate_file(output_path,expected_ids,paths)
    timings['validation_export'] = time.perf_counter()-tick
    timings['total'] = time.perf_counter()-start
    summary = {**validation,**summarize(records),'timings_seconds':timings,'matching':matching,'classification':classification,'supervised':supervised,
               'code_sha256':code_fingerprint(),'config_sha256':hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
               'taxonomy_sha256':hashlib.sha256(input_path(input_root,tax['file']).read_bytes()).hexdigest(),
               'output_sha256':hashlib.sha256(Path(output_path).read_bytes()).hexdigest(),
               'inputs':manifests,'python':sys.version.split()[0],'platform':platform.platform(),'machine':platform.machine()}
    if diagnostics_path:
        write_diagnostics(diagnostics_path,records,summary)
    return summary


def validate_pipeline_output(config_path,input_root,output_path):
    config = load_config(config_path)
    records,_ = ingest(config,input_root)
    paths = load_taxonomy(input_path(input_root,config['taxonomy']['file']),config['taxonomy']['columns'])
    result = validate_file(output_path,[r['record_id'] for r in records],paths)
    calculate_financials(records,config,input_root)
    resolve_entities(records,config)
    if config.get('matching',{}).get('enabled',True):
        match_records(records,config)
    expected = {r['record_id']:r for r in records}
    with Path(output_path).open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            r = expected[row['record_id']]
            if row['include'] != str(int(r['include'])) or row['exclusion_reason'] != r['exclusion_reason']:
                raise PipelineError('Output inclusion/reason differs from replayed rules')
            if Decimal(row['spend']) != r['spend']:
                raise PipelineError('Output spend differs from replayed financial rules')
            if row['supplier_key'] != r['supplier_key'] or row['item_key'] != r['item_key']:
                raise PipelineError('Output entity keys differ from replayed grouping rules')
    result['financial_and_matching_replay'] = 'passed'
    return result
