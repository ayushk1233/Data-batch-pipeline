"""Bounded candidate matching with eligibility and one-to-one capacity constraints."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from difflib import SequenceMatcher
import re

from .entities import informative_description, normalize_text, supplier_name


def _reference(value):
    text = str(value or "").strip().casefold()
    text = re.sub(r"^(?:purchase\s*order|po|invoice|inv)(?=[\s:#\-/0-9])\s*[:#\-/ ]*", "", text)
    return re.sub(r"[^\w]", "", text)


def _component(value):
    """CSV exports often render integer line numbers as '10.0'."""
    text = str(value or "").strip()
    if re.fullmatch(r"[0-9]+(?:\.0+)?", text):
        return text.split(".")[0].lstrip("0") or "0"
    return _reference(text)


def _po(row):
    raw = str(row.get("po") or "").strip()
    if not raw:
        return "", ""
    numbers = re.findall(r"\d+(?:\.0+)?", raw)
    explicit_item = _component(row.get("po_item"))
    # A separate short numeric component may identify the PO line. Integral
    # decimal serialization belongs to that component, never an extra line 0.
    if len(numbers) >= 2 and max(len(x.split(".")[0]) for x in numbers) >= 5:
        main_index = max(range(len(numbers)), key=lambda i: len(numbers[i].split(".")[0]))
        main = numbers[main_index]
        rest = [x for i, x in enumerate(numbers) if i != main_index]
        item = explicit_item or (_component(rest[-1]) if rest else "")
        return _component(main), item
    main = _reference(raw)
    if re.fullmatch(r"[0-9]+(?:\.0+)?", raw):
        main = _component(raw)
    return main, explicit_item


def _similar(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _supplier_similarity(left, right):
    """A long shared name prefix cannot hide a different informative token.

    Permit close OCR edits only where *each* residual word supports the alias.
    In particular numeric identities and short abbreviations cannot be guessed.
    """
    left, right = supplier_name(left), supplier_name(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if set(re.findall(r"\d+", left)) != set(re.findall(r"\d+", right)):
        return 0.0
    lt, rt = left.split(), right.split()
    for token in tuple(lt):
        if token in rt:
            lt.remove(token)
            rt.remove(token)
    if len(lt) != len(rt):
        return 0.0
    for token in lt:
        if len(token) <= 3:
            return 0.0
        best = max(rt, key=lambda candidate: _similar(token, candidate))
        if len(best) <= 3 or _similar(token, best) < 0.8:
            return 0.0
        rt.remove(best)
    return max(_similar(left, right), _similar(" ".join(sorted(left.split())), " ".join(sorted(right.split()))))


def _fingerprint(row):
    """An invoice alone is never a repeat-export fingerprint."""
    return (
        row.get("source"), _reference(row.get("invoice")),
        _reference(row.get("invoice_line")), row.get("supplier_key"),
        normalize_text(row.get("description")), row.get("item_key"),
        _po(row), row.get("spend"), row.get("quantity"),
        normalize_text(row.get("uom")), str(row.get("date") or ""),
        _reference(row.get("receipt")), _reference(row.get("receipt_item")),
    )


def _exclude(row, target):
    row["include"] = False
    row["exclusion_reason"] = "DUPLICATE"
    row["duplicate_of"] = target["record_id"]
    row["spend"] = Decimal("0")
    for level in ("l1", "l2", "l3", "l4"):
        row[level] = ""
    row["confidence"] = 0.0


def match_records(records: list[dict], config: dict | None = None) -> dict:
    """Match eligible rows, preserving uncertain pairs and unmatched capacity.

    The higher-priority source wins. Split or partial invoices are deliberately
    retained unless a unique full-line match is justified; there is no subset
    guessing. A private ``duplicate_of`` link supports auditing.
    """
    options = (config or {}).get("matching", config or {})
    absolute = Decimal(str(options.get("amount_tolerance", "0.02")))
    relative = Decimal(str(options.get("amount_relative_tolerance", "0")))
    day_window = int(options.get("date_window_days", 120))
    desc_threshold = float(options.get("description_threshold", 0.78))
    supplier_threshold = float(options.get("supplier_threshold", 0.88))
    max_candidates = int(options.get("max_candidates", 100))
    stats = {"reexports": 0, "cross_source_matches": 0, "ambiguous": 0,
             "candidate_limit": 0, "candidate_comparisons": 0}
    ordered = sorted(records, key=lambda x: (int(x.get("priority", 0)), str(x.get("source", "")), str(x["record_id"])))
    seen = {}
    for row in ordered:
        if not row.get("include") or not row.get("reexports") or not _reference(row.get("invoice")):
            continue
        # Without a line or meaningful item/description this is insufficient
        # evidence: identical generic invoice rows may be distinct real lines.
        if not (row.get("invoice_line") or row.get("item_id") or informative_description(row.get("description", ""))):
            continue
        fp = _fingerprint(row)
        if fp in seen:
            _exclude(row, seen[fp])
            stats["reexports"] += 1
        else:
            seen[fp] = row

    # Index only active, preferred source records. Different sources of equal
    # priority are not declared authoritative over one another.
    active = [r for r in ordered if r.get("include")]
    by_po = defaultdict(lambda: defaultdict(list))
    by_invoice = defaultdict(lambda: defaultdict(list))
    by_supplier = defaultdict(lambda: defaultdict(list))
    for row in active:
        priority = int(row.get("priority", 0))
        po, _ = _po(row)
        if po:
            by_po[po][priority].append(row)
        inv = _reference(row.get("invoice"))
        if inv:
            by_invoice[inv][priority].append(row)
        if row.get("supplier_key"):
            by_supplier[(row["supplier_key"], normalize_text(row.get("description")))][priority].append(row)

    edges = []
    min_priority = min((int(r.get("priority", 0)) for r in active), default=0)
    for row in active:
        if int(row.get("priority", 0)) <= min_priority:
            continue
        po, poi = _po(row)
        invoice = _reference(row.get("invoice"))
        pools = []
        if po:
            pools.extend(rows for priority, rows in by_po.get(po, {}).items() if priority < int(row.get("priority", 0)))
        if invoice:
            pools.extend(rows for priority, rows in by_invoice.get(invoice, {}).items() if priority < int(row.get("priority", 0)))
        pools.extend(rows for priority, rows in by_supplier.get((row.get("supplier_key"), normalize_text(row.get("description"))), {}).items() if priority < int(row.get("priority", 0)))
        # Bounded retrieval: skip overlarge blocks; do not truncate by CSV order.
        candidates = {}
        for pool in pools:
            if len(pool) > max_candidates:
                stats["candidate_limit"] += 1
                continue
            candidates.update((x["record_id"], x) for x in pool)
        if len(candidates) > max_candidates:
            stats["candidate_limit"] += 1
            continue
        for other in candidates.values():
            stats["candidate_comparisons"] += 1
            value, other_value = row["spend"], other["spend"]
            if (value < 0) != (other_value < 0) or abs(value - other_value) > max(absolute, relative * max(abs(value), abs(other_value))):
                continue
            # Reliable structured identity defeats a merely similar name or
            # equal-value line. These fields identify purchase granularity.
            sid, osid = str(row.get("supplier_id") or "").strip(), str(other.get("supplier_id") or "").strip()
            if sid and osid and row.get("supplier_namespace") == other.get("supplier_namespace") and sid != osid:
                continue
            receipt, oreceipt = _reference(row.get("receipt")), _reference(other.get("receipt"))
            if receipt and oreceipt and receipt != oreceipt:
                continue
            ri, ori = _component(row.get("receipt_item")), _component(other.get("receipt_item"))
            if receipt and oreceipt and ri and ori and ri != ori:
                continue
            line, oline = _component(row.get("invoice_line")), _component(other.get("invoice_line"))
            same_invoice_identity = _reference(row.get("invoice")) == _reference(other.get("invoice"))
            if row.get("invoice") and other.get("invoice") and same_invoice_identity and line and oline and line != oline:
                continue
            qty, oqty = row.get("quantity"), other.get("quantity")
            if qty is not None and oqty is not None and abs(qty - oqty) > Decimal("0.0001"):
                continue
            opo, opoi = _po(other)
            if po and opo and po != opo:
                continue
            if poi and opoi and poi != opoi:
                continue
            days = None
            if row.get("date") and other.get("date"):
                days = abs((row["date"] - other["date"]).days)
                if days > day_window:
                    continue
            same_supplier = bool(row.get("supplier_key")) and row.get("supplier_key") == other.get("supplier_key")
            sn = 1.0 if same_supplier else _supplier_similarity(row.get("supplier_name"), other.get("supplier_name"))
            ds = _similar(normalize_text(row.get("description")), normalize_text(other.get("description")))
            item_equal = bool(row.get("item_key")) and row.get("item_key") == other.get("item_key")
            if item_equal and (row.get("item_id") or other.get("item_id") or informative_description(row.get("description", ""))):
                ds = 1.0
            # Different visible technical numbers are not an OCR-compatible item.
            nums = tuple(re.findall(r"\d+(?:[.,]\d+)?", normalize_text(row.get("description"))))
            onums = tuple(re.findall(r"\d+(?:[.,]\d+)?", normalize_text(other.get("description"))))
            if nums and onums and nums != onums and not item_equal:
                continue
            same_po = bool(po and po == opo)
            same_invoice = bool(invoice and invoice == _reference(other.get("invoice")))
            strong = sn >= supplier_threshold and ds >= desc_threshold
            reference_match = (same_po or same_invoice) and strong
            reference_free = not po and not opo and sn >= 0.98 and ds >= 0.96 and days is not None and days <= 7
            if not (reference_match or reference_free):
                continue
            score = 0.35 * sn + 0.35 * ds + 0.18 * same_po + 0.08 * same_invoice + 0.04 * (days is not None and days <= 7)
            edges.append((score, row, other))

    # Reject equal-strength competing assignments. Matching a random receipt
    # would assert knowledge the input does not contain.
    choices = defaultdict(list)
    for score, row, other in edges:
        choices[row["record_id"]].append(score)
        choices[other["record_id"]].append(score)
    ambiguous = {rid for rid, scores in choices.items() if len(scores) > 1 and sorted(scores, reverse=True)[0] - sorted(scores, reverse=True)[1] < 0.025}
    stats["ambiguous"] = len(ambiguous)
    consumed = set()
    unions = {"supplier_key": {}, "item_key": {}}

    def root(mapping, key):
        trail = []
        while key in mapping:
            trail.append(key)
            key = mapping[key]
        for old in trail:
            mapping[old] = key
        return key

    for score, row, other in sorted(edges, key=lambda e: (-e[0], e[1]["record_id"], e[2]["record_id"])):
        rid, oid = row["record_id"], other["record_id"]
        if rid in ambiguous or oid in ambiguous or rid in consumed or oid in consumed:
            continue
        if not row.get("include") or not other.get("include"):
            continue
        _exclude(row, other)
        consumed.update((rid, oid))
        stats["cross_source_matches"] += 1
        for field, mapping in unions.items():
            left, right = root(mapping, row[field]), root(mapping, other[field])
            if left != right:
                mapping[max(left, right)] = min(left, right)
    for row in records:
        for field, mapping in unions.items():
            row[field] = root(mapping, row[field])
    return stats
