"""Explicit source semantics; eligibility never inferred from arbitrary IDs."""
import re
from .normalize import clean
from .config import PipelineError


def eligibility(record, source, rules):
    status = clean(record.get('status')).casefold()
    policy = source['status']
    cancelled = {clean(x).casefold() for x in policy.get('cancelled', ['cancelled','canceled'])}
    approved = {clean(x).casefold() for x in policy.get('approved', ['approved','paid'])}
    if status in cancelled:
        return 'CANCELLED'
    if not status:
        missing = policy['missing']
        if missing == 'error':
            raise PipelineError('Missing status under status.missing=error')
        if missing != 'approved':
            return 'NOT_APPROVED'
    elif status not in approved:
        return 'NOT_APPROVED'
    for rule in rules:
        value = clean(record.get(rule['field'], record['raw'].get(rule['field'], '')))
        if 'values' in rule and value.casefold() in {clean(x).casefold() for x in rule['values']}:
            return 'NON_PROCUREMENT'
        if 'pattern' in rule and re.search(rule['pattern'], value, flags=re.I):
            return 'NON_PROCUREMENT'
    return ''
