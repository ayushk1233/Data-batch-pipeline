"""CSV ingestion retaining a private source trace and stable canonical schema."""
import csv
import hashlib
import re
from .config import PipelineError, input_path
from .normalize import clean, parse_decimal, parse_date
from .eligibility import eligibility


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        if not columns or len(set(columns)) != len(columns):
            raise PipelineError(f'CSV needs unique column headers: {path.name}')
        rows = []
        for n, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise PipelineError(f'Malformed CSV field count: {path.name}, line {n}')
            rows.append(row)
    return columns, rows


def ingest(config, root):
    records, seen, manifests = [], set(), []
    for source in config['sources']:
        path = input_path(root, source['file'])
        columns, rows = read_csv(path)
        mapped = source['columns']
        required = [mapped['record_id'], mapped['amount']]
        required += [source['namespace_column']] if source.get('namespace_column') else []
        missing = set(required) - set(columns)
        if missing:
            raise PipelineError(f'Source {source["name"]} missing required columns: {sorted(missing)}')
        manifests.append({'source': source['name'], 'file':source['file'], 'rows':len(rows), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'schema_sha256':hashlib.sha256('\n'.join(columns).encode()).hexdigest()})
        for raw in rows:
            record = {'raw':raw, 'source':source['name'], 'priority':source.get('priority', 0), 'reexports':source.get('reexports',False), 'flags':[], '_source_config':source}
            for key, col in mapped.items():
                if isinstance(col, list):
                    record[key] = ' '.join(clean(raw.get(x,'')) for x in col if clean(raw.get(x,'')))
                    if any(x not in raw for x in col):
                        record['flags'].append('optional_column_missing:'+key)
                else:
                    record[key] = clean(raw.get(col,''))
                    if col not in raw:
                        record['flags'].append('optional_column_missing:'+key)
            rid = record.get('record_id','')
            if not rid:
                raise PipelineError(f'Missing record ID in source {source["name"]}')
            record['record_id'] = source.get('prefix','') + rid
            if record['record_id'] in seen:
                raise PipelineError(f'Duplicate input record ID in source {source["name"]}')
            seen.add(record['record_id'])
            namespace = clean(raw.get(source.get('namespace_column',''),''))
            for kind in ('supplier','item'):
                base = source.get(kind+'_namespace',source['name'])
                record[kind+'_namespace'] = base + (':'+namespace if namespace else '')
            settings = dict(source)
            settings.update(source.get('overrides',{}).get(namespace,{}))
            record['_settings'] = settings
            for field in ('supplier_id','supplier_name','item_id','description','context','po','po_item','invoice','invoice_line','receipt','receipt_item','uom'):
                record.setdefault(field,'')
            for field, pattern in source.get('reference_patterns',{}).items():
                original = record[field]
                match = re.search(pattern, original, flags=re.I)
                record[field] = match.group(1) if match and match.lastindex else (match.group(0) if match else '')
                if original and not record[field]:
                    record['flags'].append('reference_parse:'+field)
            formats = settings.get('date_formats',['%Y-%m-%d'])
            date_raw = record.get('date','')
            record['date'] = parse_date(date_raw, formats)
            record['date_raw'] = date_raw
            if date_raw and record['date'] is None:
                record['flags'].append('invalid_date')
            if not date_raw:
                record['flags'].append('missing_date')
            quantity = record.get('quantity','')
            try:
                record['quantity'] = parse_decimal(quantity, settings.get('decimal_separator','.'),settings.get('thousands_separator',','))
            except PipelineError:
                record['quantity'] = None
                record['flags'].append('invalid_quantity')
            reason = eligibility(record, source, config.get('non_procurement',[]))
            record.update(include=not bool(reason),exclusion_reason=reason)
            records.append(record)
    return records, manifests
