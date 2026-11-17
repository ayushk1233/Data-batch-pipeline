"""Optional local text classifier trained only from explicitly allowed partitions.

Artifacts contain confidential vocabulary and coefficients and must remain private.
Only load artifacts generated locally by this command: pickle is not a safe format
for untrusted files. The runtime taxonomy classifier remains the default/fallback.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import pickle
import re
import tempfile
import time
import unicodedata
import warnings

LEVELS = ('l1', 'l2', 'l3', 'l4')


def _features(record):
    # IDs, keys, supplier names and row positions are deliberately not features.
    context = record.get('context', '')
    if isinstance(context, (list, tuple)):
        context = ' '.join(str(x) for x in context)
    text = str(record.get('description', '') or '') + ' ' + str(context or '')
    text = unicodedata.normalize('NFKC', text).casefold()
    text = re.sub(r'\b\d{5,}\b', ' ', text)
    return ' '.join(text.split())[:4000]


def _private_path(path):
    path = Path(path).resolve()
    if not any(p in {'private', 'artifacts', 'models', 'runs', 'diagnostics'} for p in path.parts) or 'submission' in path.parts:
        raise ValueError('Model artifact must stay under an ignored private/artifacts/models/runs/diagnostics directory')
    return path


def _path(values):
    values = tuple(str(x or '').strip() for x in values)
    if not 1 <= len(values) <= 4:
        raise ValueError('Label paths need 1 to 4 levels')
    seen_blank = False
    for value in values:
        if not value:
            seen_blank = True
        elif seen_blank:
            raise ValueError('Label path has a level gap')
    return values + ('',) * (4 - len(values))


def train_model(records, labels_path, artifact_path, *, label_id_column='record_id',
                label_columns=('category_l1', 'category_l2', 'category_l3'),
                partitions_path=None, train_splits=('development',),
                partition_id_prefix='', valid_paths=None):
    """Fit word/character TF-IDF and logistic regression on allowed labels only.

    Split filtering happens before text extraction/vectorizer fitting. Calling
    without a reservation manifest requires explicit ``train_splits=('all',)``.
    Label IDs join records; they never enter model features.
    """
    from sklearn import __version__ as sklearn_version
    from sklearn.dummy import DummyClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    started = time.perf_counter()
    destination = _private_path(artifact_path)
    if not 1 <= len(label_columns) <= 4:
        raise ValueError('label_columns needs 1 to 4 levels')
    if partitions_path is None and tuple(train_splits) != ('all',):
        raise ValueError('Training needs a partition manifest or explicit train_splits=("all",)')
    if partitions_path is not None and ('all' in train_splits or not train_splits):
        raise ValueError('Partitioned training must name explicit allowed splits')
    assignments = json.loads(Path(partitions_path).read_text())['assignments'] if partitions_path else None
    by_id = {}
    for record in records:
        rid = str(record['record_id'])
        if rid in by_id:
            raise ValueError('Training records have duplicate record IDs')
        by_id[rid] = record
    allowed = set(_path(p) for p in valid_paths) if valid_paths is not None else None
    examples = []
    seen_ids = set()
    skipped = {'unmatched': 0, 'partition': 0, 'excluded': 0, 'empty_evidence': 0, 'invalid_path': 0}
    with Path(labels_path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or set((label_id_column, *label_columns)) - set(reader.fieldnames):
            raise ValueError('Label file is missing configured ID/category columns')
        for label in reader:
            rid = label[label_id_column]
            if rid in seen_ids:
                raise ValueError('Label file has duplicate record IDs')
            seen_ids.add(rid)
            record = by_id.get(rid)
            if record is None:
                skipped['unmatched'] += 1
                continue
            if assignments is not None:
                partition_id = rid[len(partition_id_prefix):] if partition_id_prefix and rid.startswith(partition_id_prefix) else rid
                if assignments.get(partition_id, {}).get('split') not in train_splits:
                    skipped['partition'] += 1
                    continue
            if record.get('include', True) not in (True, 1, '1') or str(label.get('include', '1')) != '1':
                skipped['excluded'] += 1
                continue
            try:
                category = _path(label[c] for c in label_columns)
            except ValueError:
                skipped['invalid_path'] += 1
                continue
            if not any(category) or (allowed is not None and category not in allowed):
                skipped['invalid_path'] += 1
                continue
            text = _features(record)
            if not re.search(r'\w', text, re.UNICODE):
                skipped['empty_evidence'] += 1
                continue
            examples.append((rid, text, category))
    if not examples:
        raise ValueError('No usable labelled records in allowed training partitions')
    examples.sort(key=lambda x: x[0])
    paths = sorted({category for _, _, category in examples})
    category_index = {path: i for i, path in enumerate(paths)}
    features = FeatureUnion([
        ('word', TfidfVectorizer(ngram_range=(1, 2), token_pattern=r'(?u)\b\w+\b',
                                sublinear_tf=True, max_features=50000, strip_accents='unicode')),
        ('char', TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5),
                                sublinear_tf=True, max_features=80000, strip_accents='unicode')),
    ], transformer_weights={'word': .6, 'char': .4})
    estimator = LogisticRegression(C=4.0, max_iter=300, random_state=0) if len(paths) > 1 else DummyClassifier(strategy='most_frequent')
    model = Pipeline([('features', features), ('classifier', estimator)])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        model.fit([text for _, text, _ in examples], [category_index[category] for _, _, category in examples])
    metadata = {
        'format_version': 1, 'trained_records': len(examples), 'classes': len(paths),
        'training_splits': list(train_splits), 'partitioned': assignments is not None,
        'partition_sha256': hashlib.sha256(Path(partitions_path).read_bytes()).hexdigest() if partitions_path else None,
        'labels_sha256': hashlib.sha256(Path(labels_path).read_bytes()).hexdigest(),
        'training_id_sha256': hashlib.sha256('\x1f'.join(rid for rid, _, _ in examples).encode()).hexdigest(),
        'sklearn_version': sklearn_version, 'skipped': skipped,
        'features': 'description and semantic context only; fitted word/character TF-IDF',
        'confidence_calibration': 'uncalibrated model probability; no calibration fit',
        'warnings': sorted({type(w.message).__name__ for w in caught}),
        'training_seconds': time.perf_counter() - started,
    }
    artifact = {'format_version': 1, 'paths': paths, 'model': model, 'metadata': metadata}
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.model-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            pickle.dump(artifact, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    metadata_path = destination.with_suffix(destination.suffix + '.json')
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
    return metadata


def apply_model(records, paths, artifact_path, config=None):
    """Replace confident known-class predictions, retaining the zero-label fallback.

    No artifact, optional dependency failure, or an unseen runtime tree leaves
    predictions unchanged unless ``required=True`` explicitly requests failure.
    """
    config = config or {}
    unknown = set(config) - {'min_confidence', 'required', 'batch_size'}
    if unknown:
        raise ValueError(f'Unsupported supervised options: {sorted(unknown)}')
    threshold = float(config.get('min_confidence', .55))
    batch_size = int(config.get('batch_size', 1024))
    if not math.isfinite(threshold) or not 0 <= threshold <= 1 or batch_size < 1:
        raise ValueError('Supervised threshold must be in [0,1] and batch_size positive')
    if artifact_path is None:
        if config.get('required', False):
            raise ValueError('Required supervised artifact was not configured')
        return {'mode': 'fallback', 'reason': 'not_configured', 'replaced': 0}
    source = _private_path(artifact_path)
    try:
        with source.open('rb') as handle:
            artifact = pickle.load(handle)
    except (OSError, ImportError, pickle.UnpicklingError, EOFError) as exc:
        if config.get('required', False):
            raise RuntimeError('Required local supervised artifact unavailable') from exc
        return {'mode': 'fallback', 'reason': type(exc).__name__, 'replaced': 0}
    if artifact.get('format_version') != 1:
        raise ValueError('Unsupported supervised artifact format')
    allowed = set(_path(p) for p in paths)
    learned = artifact['paths']
    if not any(tuple(path) in allowed for path in learned):
        return {'mode': 'fallback', 'reason': 'unseen_taxonomy', 'replaced': 0}
    model = artifact['model']
    eligible = [r for r in records if r.get('include', True) in (True, 1, '1') and _features(r)]
    replaced = 0
    for start in range(0, len(eligible), batch_size):
        batch = eligible[start:start + batch_size]
        features = model.named_steps['features'].transform([_features(r) for r in batch])
        probabilities = model.named_steps['classifier'].predict_proba(features)
        class_ids = model.named_steps['classifier'].classes_
        for row, vector, feature in zip(batch, probabilities, features):
            # An out-of-vocabulary row must not be assigned the training prior.
            if feature.nnz == 0:
                continue
            index = max(range(len(vector)), key=lambda i: (float(vector[i]), -int(class_ids[i])))
            confidence = float(vector[index])
            category = tuple(learned[int(class_ids[index])])
            if confidence < threshold or not math.isfinite(confidence) or category not in allowed:
                continue
            for level, value in zip(LEVELS, category):
                row[level] = value
            row['confidence'] = round(confidence, 6)
            replaced += 1
    return {'mode': 'supervised_with_taxonomy_fallback', 'replaced': replaced,
            'eligible': len(eligible), 'threshold': threshold,
            'artifact_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'confidence_calibration': 'uncalibrated model probability'}
