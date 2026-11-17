"""Output contract checked in memory and again on CSV readback."""
import csv
import os
import tempfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .config import PipelineError

COLUMNS = ['record_id','include','exclusion_reason','supplier_key','item_key','spend','l1','l2','l3','l4','confidence']
REASONS = {'CANCELLED','NOT_APPROVED','NON_PROCUREMENT','DUPLICATE'}


def output_rows(records):
    rows = []
    for r in records:
        included = bool(r['include'])
        row = {k:r.get(k,'') for k in COLUMNS}
        row['include'] = '1' if included else '0'
        row['spend'] = format(r['spend'] if included else Decimal(0),'.2f')
        row['exclusion_reason'] = '' if included else r['exclusion_reason']
        if not included:
            for k in ('l1','l2','l3','l4'):
                row[k] = ''
            row['confidence'] = 0
        row['confidence'] = format(float(row.get('confidence') or 0),'.6f')
        rows.append({k:str(row[k]) for k in COLUMNS})
    return rows


def validate_rows(rows, expected_ids, paths):
    expected_ids = list(expected_ids)
    if len(set(expected_ids)) != len(expected_ids):
        raise PipelineError('Input record IDs must be unique')
    if Counter(r.get('record_id') for r in rows) != Counter(expected_ids):
        raise PipelineError('Output record coverage mismatch')
    allowed_paths = set(tuple(p) for p in paths)
    for r in rows:
        if list(r) != COLUMNS:
            raise PipelineError('Output schema/order mismatch')
        if not r['supplier_key'] or not r['item_key']:
            raise PipelineError('Empty supplier/item key')
        try:
            spend, confidence = Decimal(str(r['spend'])), Decimal(str(r['confidence']))
        except InvalidOperation as exc:
            raise PipelineError('Invalid output numeric value') from exc
        if not spend.is_finite() or not confidence.is_finite() or not 0 <= confidence <= 1:
            raise PipelineError('Non-finite spend or confidence outside [0,1]')
        path = tuple(r[f'l{i}'] for i in range(1,5))
        if r['include'] == '1':
            if r['exclusion_reason'] or path not in allowed_paths:
                raise PipelineError('Included output needs blank reason and valid taxonomy leaf')
        elif r['include'] == '0':
            if r['exclusion_reason'] not in REASONS or spend != 0 or any(path):
                raise PipelineError('Excluded output reason/spend/category inconsistency')
        else:
            raise PipelineError('include must be exactly 0 or 1')
    return {'rows':len(rows),'included':sum(r['include']=='1' for r in rows),'total_spend':str(sum((Decimal(r['spend']) for r in rows),Decimal(0)))}


def write_output(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name,dir=path.parent,text=True)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_file(path, expected_ids, paths):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != COLUMNS:
            raise PipelineError('Output CSV schema/order mismatch')
        rows = list(reader)
    return validate_rows(rows,expected_ids,paths)
