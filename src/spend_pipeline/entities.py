"""Conservative, deterministic entity identity without company-specific dictionaries."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import re
import unicodedata

_LEGAL_ENDINGS = {"limited", "ltd", "inc", "incorporated", "corp", "corporation", "llc", "plc", "pty", "co", "company"}
_GENERIC = {"", "product", "products", "part", "parts", "item", "items", "service", "services", "material", "materials", "misc", "other", "unknown", "n a", "na"}


def normalize_text(value) -> str:
    """Normalise typography, keeping letters and all specification digits."""
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+(?:[.,][0-9]+)?", text, re.UNICODE))


def supplier_name(value) -> str:
    tokens = normalize_text(value).split()
    while tokens and tokens[-1] in _LEGAL_ENDINGS:
        tokens.pop()
    return " ".join(tokens)


def stable_key(prefix: str, *components) -> str:
    payload = "\x1f".join(str(x) for x in components)
    return prefix + ":" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def informative_description(text: str) -> bool:
    normal = normalize_text(text)
    return normal not in _GENERIC and (len(normal.split()) > 1 or len(normal) >= 6)


def resolve_entities(records: list[dict], config: dict | None = None) -> None:
    """Use namespace-scoped IDs, unambiguous exact aliases, then descriptive identity.

    Similar names alone never union ID-backed entities. Missing identifiers and
    uninformative text get singletons instead of a shared 'unknown' group.
    """
    names_to_ids = defaultdict(set)
    descriptions_to_ids = defaultdict(set)
    specification_variants = defaultdict(lambda: defaultdict(set))
    for row in records:
        if not row.get("include", True) or not str(row.get("item_id") or "").strip():
            continue
        desc = normalize_text(row.get("description"))
        numbers = tuple(re.findall(r"\d+(?:[.,]\d+)?", desc))
        if numbers:
            identity = (row.get("item_namespace", row.get("source", "")), str(row["item_id"]).strip())
            skeleton = re.sub(r"\d+(?:[.,]\d+)?", "#", desc)
            specification_variants[identity][skeleton].add(numbers)
    conflicts = {identity for identity, skeletons in specification_variants.items()
                 if any(len(numbers) > 1 for numbers in skeletons.values())}
    for row in records:
        sid = str(row.get("supplier_id") or "").strip()
        name = supplier_name(row.get("supplier_name"))
        if sid:
            key = stable_key("supplier", row.get("supplier_namespace", row.get("source", "")), sid)
            row["supplier_key"] = key
            if row.get("include", True) and name and name not in _GENERIC:
                names_to_ids[name].add(key)
        iid = str(row.get("item_id") or "").strip()
        desc = normalize_text(row.get("description"))
        uom = normalize_text(row.get("uom"))
        if iid:
            namespace = row.get("item_namespace", row.get("source", ""))
            if (namespace, iid) in conflicts:
                signature = tuple(re.findall(r"\d+(?:[.,]\d+)?", desc))
                key = stable_key("item", namespace, iid, "specification", signature)
                row.setdefault("flags", []).append("conflicting_item_specification")
            else:
                key = stable_key("item", namespace, iid)
            row["item_key"] = key
            if row.get("include", True) and informative_description(desc):
                descriptions_to_ids[(desc, uom)].add(key)
    for row in records:
        if not str(row.get("supplier_id") or "").strip():
            name = supplier_name(row.get("supplier_name"))
            anchors = names_to_ids.get(name, set())
            if len(anchors) == 1:
                row["supplier_key"] = next(iter(anchors))
            elif name and name not in _GENERIC:
                row["supplier_key"] = stable_key("supplier", "name", name)
            else:
                row["supplier_key"] = stable_key("supplier", "unresolved", row.get("source", ""), row["record_id"])
        if not str(row.get("item_id") or "").strip():
            desc = normalize_text(row.get("description"))
            uom = normalize_text(row.get("uom"))
            anchors = descriptions_to_ids.get((desc, uom), set())
            if informative_description(desc) and len(anchors) == 1:
                row["item_key"] = next(iter(anchors))
            elif informative_description(desc):
                row["item_key"] = stable_key("item", "description", desc, uom)
            else:
                row["item_key"] = stable_key("item", "unresolved", row.get("source", ""), row["record_id"])
