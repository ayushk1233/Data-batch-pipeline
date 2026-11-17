"""Data-only configuration, validated before any input is processed."""
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path


class PipelineError(ValueError):
    """An actionable input/configuration failure (never a fabricated spend)."""


def _keys(value, allowed, label):
    if not isinstance(value, dict):
        raise PipelineError(f'{label} must be an object')
    unknown = set(value) - set(allowed.split())
    if unknown:
        raise PipelineError(f'Unsupported {label} options: {sorted(unknown)}')


def load_config(path):
    path = Path(path)
    try:
        text = path.read_text(encoding='utf-8-sig')
        if path.suffix.lower() == '.json':
            config = json.loads(text)
        else:
            try:
                import yaml
            except ImportError as exc:
                raise PipelineError('YAML requires PyYAML; use JSON for dependency-free execution') from exc
            config = yaml.safe_load(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f'Cannot read config {path}: {exc}') from exc
    validate_config(config)
    return config


def validate_config(c):
    _keys(c, 'version reporting_currency taxonomy sources fx non_procurement matching classifier financial', 'config')
    if type(c.get('version')) is not int or c.get('version') != 1:
        raise PipelineError('config.version must equal 1')
    if not isinstance(c.get('reporting_currency'), str) or not c['reporting_currency'].strip():
        raise PipelineError('reporting_currency is required')
    tax = c.get('taxonomy', {})
    _keys(tax, 'file columns', 'taxonomy')
    if not tax.get('file') or not isinstance(tax.get('columns'), list) or not 1 <= len(tax['columns']) <= 4 or not all(isinstance(x,str) and x.strip() for x in tax['columns']) or len(set(tax['columns'])) != len(tax['columns']):
        raise PipelineError('taxonomy needs file and 1-4 unique ordered columns')
    if not isinstance(c.get('sources'), list) or not c['sources']:
        raise PipelineError('sources must be a nonempty list')
    names = set()
    for s in c['sources']:
        _keys(s, 'name file prefix priority columns currency amount_semantics default_vat decimal_separator thousands_separator date_formats supplier_namespace item_namespace namespace_column status reexports overrides reference_patterns', 'source')
        if not isinstance(s.get('name'),str) or not s['name'].strip() or s['name'] in names or not isinstance(s.get('file'),str) or not s['file'].strip():
            raise PipelineError('Each source needs a unique name and file')
        names.add(s['name'])
        _keys(s.get('columns', {}), 'record_id amount description context supplier_id supplier_name item_id po po_item invoice invoice_line receipt receipt_item quantity uom currency fx_rate date posting_date status vat_rate unit_amount non_procurement', 'source.columns')
        if not all(s['columns'].get(k) for k in ['record_id', 'amount']):
            raise PipelineError('Each source must map record_id and amount')
        for key, value in s['columns'].items():
            if (isinstance(value,str) and not value.strip()) or (not isinstance(value, str) and not (key in ('description','context') and isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value))):
                raise PipelineError(f'Invalid column mapping for {key}')
        if s.get('amount_semantics', 'net') not in ('net', 'gross'):
            raise PipelineError('amount_semantics must be net or gross')
        if s.get('decimal_separator', '.') not in ('.', ','):
            raise PipelineError('decimal_separator must be . or ,')
        if s.get('decimal_separator', '.') == s.get('thousands_separator', ','):
            raise PipelineError('Decimal and thousands separators must differ')
        if type(s.get('priority', 0)) is not int or not isinstance(s.get('reexports', False), bool):
            raise PipelineError('priority must be integer; reexports must be boolean')
        status = s.get('status', {})
        _keys(status, 'missing approved cancelled', 'source.status')
        if status.get('missing') not in ('approved', 'not_approved', 'error'):
            raise PipelineError('Every source must explicitly set status.missing: approved, not_approved or error')
        for k in ('approved', 'cancelled'):
            if not isinstance(status.get(k, []), list) or not all(isinstance(x,str) and x.strip() for x in status.get(k,[])):
                raise PipelineError(f'status.{k} must be a list')
        if not isinstance(s.get('date_formats',['%Y-%m-%d']),list) or not all(isinstance(x,str) and x for x in s.get('date_formats',['%Y-%m-%d'])):
            raise PipelineError('date_formats must be a list of format strings')
        if not isinstance(s.get('overrides',{}),dict) or not isinstance(s.get('reference_patterns',{}),dict):
            raise PipelineError('overrides and reference_patterns must be objects')
        for name, override in s.get('overrides', {}).items():
            _keys(override, 'decimal_separator thousands_separator date_formats', 'source override')
        for field, pattern in s.get('reference_patterns', {}).items():
            if field not in ('po', 'po_item', 'invoice') or not isinstance(pattern, str):
                raise PipelineError('reference_patterns supports po, po_item, invoice regexes only')
            import re
            try:
                re.compile(pattern)
            except re.error as exc:
                raise PipelineError(f'Invalid reference pattern: {exc}') from exc
    if 'fx' in c:
        _keys(c['fx'], 'file currency_column month_column rate_column direction', 'fx')
        if c['fx'].get('direction', 'units_per_reporting') not in ('units_per_reporting', 'reporting_per_unit'):
            raise PipelineError('Unsupported FX direction')
        if not all(c['fx'].get(k) for k in ('file', 'currency_column', 'month_column', 'rate_column')):
            raise PipelineError('fx requires file/currency_column/month_column/rate_column')
    if not isinstance(c.get('non_procurement',[]),list):
        raise PipelineError('non_procurement must be a list of rules')
    for rule in c.get('non_procurement', []):
        _keys(rule, 'field values pattern', 'non_procurement rule')
        if not rule.get('field') or ('values' in rule) == ('pattern' in rule):
            raise PipelineError('Each non_procurement rule needs field and exactly one of values/pattern')
        if 'values' in rule and not isinstance(rule['values'], list):
            raise PipelineError('non_procurement.values must be list')
        if 'pattern' in rule:
            import re
            try:
                re.compile(rule['pattern'])
            except (re.error, TypeError) as exc:
                raise PipelineError(f'Invalid non_procurement pattern: {exc}') from exc
    _keys(c.get('matching', {}), 'enabled amount_tolerance amount_relative_tolerance date_window_days description_threshold supplier_threshold max_candidates', 'matching')
    _keys(c.get('classifier', {}), 'mode model revision local_files_only batch_size device max_length semantic_weight', 'classifier')
    if c.get('classifier', {}).get('mode', 'lexical') not in ('lexical', 'semantic', 'auto'):
        raise PipelineError('classifier.mode must be lexical, semantic, or auto')
    _keys(c.get('financial', {}), 'missing_amount missing_fx max_fx_gap_months', 'financial')
    if c.get('financial', {}).get('missing_amount', 'error') not in ('error', 'estimate_unit_median'):
        raise PipelineError('Unsupported missing_amount policy')
    if c.get('financial', {}).get('missing_fx', 'error') not in ('error','nearest_month'):
        raise PipelineError('Unsupported missing_fx policy')
    _integer(c.get('financial', {}).get('max_fx_gap_months',24), 'max_fx_gap_months', 0, 120)
    options = c.get('matching',{})
    if not isinstance(options.get('enabled',True),bool):
        raise PipelineError('matching.enabled must be boolean')
    for key in ('amount_tolerance','amount_relative_tolerance'):
        _number(options.get(key, '0'), 'matching.'+key, 0)
    for key in ('description_threshold','supplier_threshold'):
        _number(options.get(key,0.8), 'matching.'+key, 0, 1)
    _integer(options.get('max_candidates',100),'matching.max_candidates',1,100000)
    _integer(options.get('date_window_days',120),'matching.date_window_days',0,36500)
    classifier = c.get('classifier',{})
    _integer(classifier.get('batch_size',32),'classifier.batch_size',1,1024)
    _integer(classifier.get('max_length',128),'classifier.max_length',8,512)
    _number(classifier.get('semantic_weight',.85),'classifier.semantic_weight',0,1)
    if not isinstance(classifier.get('local_files_only',True),bool):
        raise PipelineError('classifier.local_files_only must be boolean')


def _number(value, name, low, high=None):
    try:
        number = Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise PipelineError(f'{name} must be numeric') from exc
    if isinstance(value,bool) or not number.is_finite() or number < low or (high is not None and number > high):
        raise PipelineError(f'{name} is outside its supported range')
    return number


def _integer(value,name,low,high):
    number = _number(value,name,low,high)
    if number != number.to_integral_value():
        raise PipelineError(f'{name} must be an integer')


def input_path(root, filename):
    """Config paths stay within the supplied input root (no evaluator truth access)."""
    root = Path(root).resolve()
    candidate = (root / filename).resolve()
    if not candidate.is_relative_to(root):
        raise PipelineError(f'Input path escapes input root: {filename}')
    if not candidate.is_file():
        raise PipelineError(f'Required input file not found: {filename}')
    return candidate
