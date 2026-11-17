"""Strict signed decimal and date parsing with explicit locale semantics."""
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from .config import PipelineError


def clean(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).split())


def parse_decimal(value, decimal_separator='.', thousands_separator=','):
    text = clean(value).replace('\u2212', '-')
    if not text:
        return None
    negative = text.startswith('(') and text.endswith(')')
    if negative:
        text = text[1:-1].strip()
        if text.startswith(('+','-')):
            raise PipelineError('Parenthesised amount must not contain a second sign')
    if thousands_separator in (' ', '\u00a0'):
        text = text.replace(' ', '')
    elif thousands_separator:
        # Do not accept malformed grouping such as 1,2,3 as 123.
        integer = text.lstrip('+-').split(decimal_separator)[0]
        if thousands_separator in integer:
            groups = integer.split(thousands_separator)
            if not (1 <= len(groups[0]) <= 3 and all(len(g) == 3 and g.isdigit() for g in groups[1:])):
                raise PipelineError('Malformed thousands grouping')
        text = text.replace(thousands_separator, '')
    if decimal_separator != '.':
        text = text.replace(decimal_separator, '.')
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', text):
        raise PipelineError('Invalid numeric value')
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise PipelineError('Invalid decimal') from exc
    if not value.is_finite():
        raise PipelineError('Non-finite numeric value')
    return -value if negative else value


def parse_vat(value, default=None):
    text = clean(value)
    if not text:
        if default is None:
            raise PipelineError('Gross amount requires VAT or an explicit default_vat')
        text = clean(default)
    percent = text.endswith('%')
    number = parse_decimal(text.rstrip('%'), decimal_separator=',' if ',' in text else '.', thousands_separator='')
    if number is None or number < 0:
        raise PipelineError('Invalid VAT rate')
    if percent or number > 1:
        number /= 100
    if number > 1:
        raise PipelineError('VAT fraction exceeds 1')
    return number


def parse_date(value, formats):
    text = clean(value)
    if not text:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
