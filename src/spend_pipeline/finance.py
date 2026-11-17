"""Net tax and reporting-currency arithmetic. Unknown money never becomes zero."""
import re
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from .config import PipelineError, input_path
from .ingest import read_csv
from .normalize import clean, parse_decimal, parse_vat

CENT = Decimal('0.01')


def load_fx(config, root):
    if 'fx' not in config:
        return {}
    spec = config['fx']
    columns, rows = read_csv(input_path(root, spec['file']))
    if not all(spec[x] in columns for x in ('currency_column','month_column','rate_column')):
        raise PipelineError('FX table missing configured column')
    rates = {}
    for raw in rows:
        currency = clean(raw[spec['currency_column']]).upper()
        month = clean(raw[spec['month_column']])
        if not currency or not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',month):
            raise PipelineError('Invalid FX currency/month')
        rate = parse_decimal(raw[spec['rate_column']])
        if rate is None or rate <= 0:
            raise PipelineError('FX table rates must be positive')
        key = (currency,month)
        if key in rates and rates[key] != rate:
            raise PipelineError('Conflicting FX rates for currency/month')
        rates[key] = rate
    return rates


def _conversion(r, config, rates):
    reporting = config['reporting_currency'].upper()
    currency = clean(r.get('currency') or r['_settings'].get('currency','')).upper()
    r['_currency'] = currency
    if not currency:
        raise PipelineError(f'Missing currency in source {r["source"]}')
    if currency == reporting:
        r['fx_provenance'] = 'reporting_currency'
        return Decimal(1)
    source = r['_settings']
    rate, provenance = None, 'line'
    rate_text = clean(r.get('fx_rate',''))
    if rate_text:
        try:
            rate = parse_decimal(rate_text,source.get('decimal_separator','.'),source.get('thousands_separator',','))
        except PipelineError:
            r['flags'].append('invalid_line_fx')
        if rate is not None and rate <= 0:
            r['flags'].append('invalid_line_fx')
            rate = None
    if rate is None:
        month = r['date'].strftime('%Y-%m') if r['date'] else ''
        rate, provenance = rates.get((currency,month)), 'invoice_month'
    if rate is None and config.get('financial',{}).get('missing_fx','error') == 'nearest_month' and r['date']:
        target = r['date'].year*12+r['date'].month
        candidates = []
        for (cur,month),value in rates.items():
            if cur != currency:
                continue
            year,number = map(int,month.split('-'))
            index = year*12+number
            candidates.append((abs(index-target),index,month,value))
        if candidates:
            gap,_,month,value = min(candidates)
            if gap <= config.get('financial',{}).get('max_fx_gap_months',24):
                rate,provenance = value,'estimated_nearest_month'
                r['fx_estimate_month'] = month
                r['fx_estimate_gap_months'] = gap
                r['flags'].append('estimated_fx:nearest_month')
    if rate is None:
        raise PipelineError(f'Missing usable FX in source {r["source"]}; supply a line rate or invoice-month rate')
    r['fx_rate_used'],r['fx_provenance'] = str(rate),provenance
    return Decimal(1)/rate if config.get('fx',{}).get('direction','units_per_reporting') == 'units_per_reporting' else rate


def calculate_financials(records, config, root):
    rates = load_fx(config, root)
    unit_prices, missing = defaultdict(list), []
    policy = config.get('financial',{}).get('missing_amount','error')
    for r in records:
        r['spend'] = Decimal(0)
        if not r['include']:
            continue
        source = r['_settings']
        try:
            amount = parse_decimal(r.get('amount',''),source.get('decimal_separator','.'),source.get('thousands_separator',','))
        except PipelineError as exc:
            raise PipelineError(f'Invalid amount in source {r["source"]}; inspect private diagnostics') from exc
        # Even missing-amount rows need valid currency/rate provenance.
        conversion = _conversion(r,config,rates)
        vat = Decimal(0)
        if source.get('amount_semantics','net') == 'gross':
            vat = parse_vat(r.get('vat_rate',''),source.get('default_vat'))
            r['vat_fraction'] = str(vat)
            if not clean(r.get('vat_rate','')):
                r['flags'].append('default_vat')
        if amount is None:
            missing.append(r)
            continue
        net = amount / (1+vat) * conversion
        r['spend_unrounded'] = net
        r['spend'] = net.quantize(CENT,rounding=ROUND_HALF_UP)
        if r['item_id'] and r.get('quantity'):
            # Material identity is source-scoped; peers may have different
            # invoice currencies, so compare net reporting-currency unit prices.
            key = (r['source'],r['item_namespace'],r['item_id'])
            unit_prices[key].append(net/r['quantity'])
    for r in missing:
        key = (r['source'],r['item_namespace'],r['item_id'])
        samples = unit_prices.get(key,[])
        if policy != 'estimate_unit_median' or not r['item_id'] or not r.get('quantity') or len(samples) < 2:
            raise PipelineError(f'Missing amount in source {r["source"]}; no authorised, supported estimate. See financial.missing_amount')
        net = median(samples)*r['quantity']
        r['spend_unrounded'] = net
        r['spend'] = net.quantize(CENT,rounding=ROUND_HALF_UP)
        r['flags'].append('estimated_amount:group_unit_median')
        r['amount_estimate_support'] = len(samples)
        r['amount_estimate_unit_range'] = [str(min(samples)),str(max(samples))]
