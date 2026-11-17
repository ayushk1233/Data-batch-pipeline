"""Runtime leaf retrieval. Labels and company-specific category rules are never read.

The stdlib lexical route is always available. The optional semantic route loads
an explicitly selected, locally cached sentence encoder without remote code or
network access. Confidence is a ranking heuristic, not a calibrated probability.
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
import warnings
from collections import Counter
from pathlib import Path

LEVELS = ('l1', 'l2', 'l3', 'l4')
DEFAULT_MODEL = 'sentence-transformers/LaBSE'
DEFAULT_REVISION = '836121a0533e5664b21c7aacc5d22951f2b8b25b'


def _text(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).split())


def _tokens(value):
    # Accent-insensitive comparison, retaining non-Latin letters and specifications.
    value = ''.join(c for c in unicodedata.normalize('NFKD', _text(value).casefold())
                    if not unicodedata.combining(c))
    words = re.findall(r'[^\W_]+', value, re.UNICODE)
    return [w[:-1] if len(w) > 4 and w.endswith('s') and not w.endswith('ss') else w
            for w in words]


def _trigrams(value):
    value = ' '.join(_tokens(value))
    return set(value[i:i + 3] for i in range(max(0, len(value) - 2)))


def _included(record):
    return record.get('include', True) in (True, 1, '1')


def load_taxonomy(path: Path, columns: list[str]) -> list[tuple[str, str, str, str]]:
    """Read exact leaf spellings; reject gaps and malformed taxonomy schemas.

    A prefix row with descendants denotes an internal node, not another leaf.
    Leaves with fewer than four levels are right-padded with empty strings.
    """
    if (not isinstance(columns, (list, tuple)) or not 1 <= len(columns) <= 4
            or not all(isinstance(c, str) and c.strip() for c in columns)
            or len(set(columns)) != len(columns)):
        raise ValueError('Taxonomy needs 1 to 4 distinct level columns')
    paths = set()
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError('Taxonomy is missing configured level columns')
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('Taxonomy CSV contains duplicate column headers')
        if any(not header.strip() for header in reader.fieldnames):
            raise ValueError('Taxonomy CSV contains an empty column header')
        if set(columns) - set(reader.fieldnames):
            raise ValueError('Taxonomy is missing configured level columns')
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'Taxonomy row {number} does not match the header field count')
            values = tuple(_text(row[c]) for c in columns)
            if not any(values):
                raise ValueError(f'Taxonomy contains an empty path at row {number}')
            seen_blank = False
            for value in values:
                if not value:
                    seen_blank = True
                elif seen_blank:
                    raise ValueError(f'Taxonomy has a level gap at row {number}')
            full = values + ('',) * (4 - len(values))
            if full in paths:
                raise ValueError(f'Taxonomy contains a duplicate path at row {number}')
            paths.add(full)
    if not paths:
        raise ValueError('Taxonomy has no categories')
    trimmed = {tuple(x for x in path if x) for path in paths}
    leaves = [path for path in trimmed if not any(
        len(other) > len(path) and other[:len(path)] == path for other in trimmed)]
    return sorted(path + ('',) * (4 - len(path)) for path in leaves)


class LexicalClassifier:
    """Weighted token and character retrieval against full ancestor-to-leaf paths."""
    def __init__(self, paths):
        self.paths = sorted(set(tuple(p) for p in paths))
        if not self.paths:
            raise ValueError('Cannot classify without taxonomy leaves')
        counts = Counter(t for p in self.paths for t in set(_tokens(' '.join(p))))
        self.idf = {t: math.log((len(self.paths) + 1) / (n + 1)) + 1
                    for t, n in counts.items()}
        self.features = []
        for path in self.paths:
            levels = [p for p in path if p]
            weights = Counter()
            for index, level in enumerate(levels):
                weight = 1 if index == len(levels) - 1 else .55
                for token in _tokens(level):
                    weights[token] += weight * self.idf[token]
            self.features.append((weights, _trigrams(' '.join(levels))))

    def scores(self, description, context):
        query = Counter(_tokens(description))
        for token in _tokens(context):
            query[token] += .4
        query = {k: min(v, 2) * self.idf.get(k, 1) for k, v in query.items()}
        grams = _trigrams(description + ' ' + context)
        result = []
        for weights, leafgrams in self.features:
            numerator = sum(weights.get(k, 0) * v for k, v in query.items())
            denominator = math.sqrt(sum(v * v for v in query.values()) *
                                    sum(v * v for v in weights.values()))
            cosine = numerator / denominator if denominator else 0
            char = len(grams & leafgrams) / math.sqrt(len(grams) * len(leafgrams)) if grams and leafgrams else 0
            result.append(.83 * cosine + .17 * char)
        return result

    def predict(self, description, context):
        return self.scores(description, context)


def _load_encoder(config):
    from sentence_transformers import SentenceTransformer
    # Deliberately no implicit download. Setup is a separate explicit operation.
    model = SentenceTransformer(config.get('model', DEFAULT_MODEL),
                                revision=config.get('revision', DEFAULT_REVISION),
                                device=config.get('device', 'cpu'),
                                local_files_only=config.get('local_files_only', True), trust_remote_code=False)
    model.max_seq_length = int(config.get('max_length', 128))
    return model


def _evidence(record):
    description = _text(record.get('description', ''))
    context = record.get('context', '')
    if isinstance(context, (list, tuple)):
        context = ' '.join(_text(x) for x in context)
    return description, _text(context)


def classify_records(records: list[dict], paths, config: dict | None = None):
    """Mutate output categories and confidence using only allowed record evidence.

    ``mode`` is lexical, semantic, or auto. Explicit semantic mode fails rather
    than silently changing methods; auto warns and falls back if unavailable.
    An invocation-scoped cache includes both description and context and is
    rebuilt for each taxonomy/model. It cannot return paths from an earlier run.
    """
    config = config or {}
    supported = {'mode', 'model', 'revision', 'device', 'batch_size', 'max_length', 'semantic_weight', 'local_files_only'}
    unknown = set(config) - supported
    if unknown:
        raise ValueError(f'Unsupported classification options: {sorted(unknown)}')
    mode = config.get('mode', 'lexical')
    if mode not in {'lexical', 'semantic', 'auto'}:
        raise ValueError('Classification mode must be lexical, semantic, or auto')
    batch_size = int(config.get('batch_size', 32))
    if batch_size < 1 or batch_size > 1024:
        raise ValueError('Classification batch_size must be between 1 and 1024')
    weight = float(config.get('semantic_weight', .85))
    if not 0 <= weight <= 1:
        raise ValueError('semantic_weight must be between 0 and 1')
    if not 8 <= int(config.get('max_length', 128)) <= 512:
        raise ValueError('max_length must be between 8 and 512')
    if not isinstance(config.get('local_files_only', True), bool):
        raise ValueError('local_files_only must be a boolean')
    lexical = LexicalClassifier(paths)
    evidence = {}
    for record in records:
        if not _included(record):
            for name in LEVELS:
                record[name] = ''
            record['confidence'] = 0.0
        else:
            evidence[id(record)] = _evidence(record)
    unique = sorted(set(evidence.values()))
    scores = {key: lexical.scores(*key) for key in unique}
    used_mode = 'lexical'
    if mode != 'lexical' and unique:
        try:
            model = _load_encoder(config)
            semantic_scores = dict(scores)
            category_text = ['; '.join(p for p in path if p) for path in lexical.paths]
            categories = model.encode(category_text, batch_size=batch_size,
                                      normalize_embeddings=True, show_progress_bar=False)
            # Bound query embedding memory; no all-record square similarity matrix.
            for start in range(0, len(unique), batch_size):
                keys = unique[start:start + batch_size]
                texts = [(d + ('. ' if d and c else '') + c)[:4000] for d, c in keys]
                embeddings = model.encode(texts, batch_size=batch_size,
                                          normalize_embeddings=True, show_progress_bar=False)
                similarity = embeddings @ categories.T
                for key, similarities in zip(keys, similarity):
                    if any(key):
                        semantic_scores[key] = [(1 - weight) * a + weight * max(0.0, float(b))
                                       for a, b in zip(scores[key], similarities)]
            scores = semantic_scores
            used_mode = 'semantic'
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            if mode == 'semantic':
                raise RuntimeError(f'Local semantic classification unavailable: {exc}') from exc
            warnings.warn(f'Local semantic encoder unavailable; using lexical retrieval ({type(exc).__name__})', RuntimeWarning)
    for record in records:
        if not _included(record):
            continue
        key = evidence[id(record)]
        row_scores = scores[key]
        ranked = sorted(range(len(row_scores)), key=lambda i: (-row_scores[i], lexical.paths[i]))
        best = ranked[0]
        first = row_scores[best]
        second = row_scores[ranked[1]] if len(ranked) > 1 else 0
        # Ties and absent evidence must remain visibly uncertain.
        confidence = 0.0 if not any(key) or first <= 0 else min(.95, max(0.01, .55 * first + 1.8 * (first - second)))
        for name, value in zip(LEVELS, lexical.paths[best]):
            record[name] = value
        record['confidence'] = round(confidence, 6)
    return {'mode': used_mode, 'unique_evidence': len(unique), 'records': len(evidence),
            'confidence_calibration': 'uncalibrated ranking heuristic',
            'model': config.get('model', DEFAULT_MODEL) if used_mode == 'semantic' else None,
            'revision': config.get('revision', DEFAULT_REVISION) if used_mode == 'semantic' else None}
