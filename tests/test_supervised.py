import csv
import importlib.util
import json
from pathlib import Path
import pickle
import tempfile
import unittest

from spend_pipeline.classify import classify_records
from spend_pipeline.supervised import apply_model, train_model

SKLEARN_AVAILABLE = importlib.util.find_spec('sklearn') is not None


class OptionalFallbackTests(unittest.TestCase):
    def test_missing_artifact_preserves_zero_label_output(self):
        rows = [dict(include=True, description='oven')]
        paths = [('Kitchen', 'Ovens', '', '')]
        classify_records(rows, paths)
        before = dict(rows[0])
        self.assertEqual(apply_model(rows, paths, None)['reason'], 'not_configured')
        self.assertEqual(rows[0], before)
        with self.assertRaises(ValueError):
            apply_model(rows, paths, None, {'required': True})
        with self.assertRaises(ValueError):
            apply_model(rows, paths, 'submission/bad.pkl')
        with self.assertRaises(ValueError):
            apply_model(rows, paths, None, {'min_confidence': float('nan')})


@unittest.skipUnless(SKLEARN_AVAILABLE, 'Optional supervised tests require scikit-learn; install requirements-models.txt')
class SupervisedFlowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / 'private'
        self.directory.mkdir()
        self.artifact = self.directory / 'model.pkl'
        self.paths = [('Catering', 'Ovens', '', ''), ('Transport', 'Tyres', '', '')]
        self.records = []
        self.labels = []
        self.assignments = {}
        for i in range(24):
            rid = f'ERP:{i}'
            first = i % 2 == 0
            self.records.append(dict(record_id=rid, include=True,
                                     description='kitchen oven baking' if first else 'vehicle tyre rubber',
                                     context='', supplier_id='neverfeature', item_key='neverfeature'))
            self.labels.append([rid, *self.paths[0 if first else 1][:2]])
            self.assignments[str(i)] = {'split': 'development', 'group_hash': str(i)}
        self.records.append(dict(record_id='ERP:heldout', include=True,
                                 description='heldoutmarker only', context=''))
        self.labels.append(['ERP:heldout', 'Transport', 'Tyres'])
        self.assignments['heldout'] = {'split': 'test', 'group_hash': 'sealed'}
        self.label_path = self.directory / 'labels.csv'
        with self.label_path.open('w', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['record_id', 'cat1', 'cat2'])
            writer.writerows(self.labels)
        self.manifest = self.directory / 'split.json'
        self.manifest.write_text(json.dumps({'assignments': self.assignments}))

    def train(self, **kwargs):
        return train_model(self.records, self.label_path, self.artifact,
                           label_columns=['cat1', 'cat2'], partitions_path=self.manifest,
                           partition_id_prefix='ERP:', valid_paths=self.paths, **kwargs)

    def test_grouped_training_excludes_heldout_before_vectorizer_fit_and_predicts(self):
        metadata = self.train()
        self.assertEqual(metadata['trained_records'], 24)
        self.assertEqual(metadata['skipped']['partition'], 1)
        with self.artifact.open('rb') as handle:
            artifact = pickle.load(handle)
        word = artifact['model'].named_steps['features'].transformer_list[0][1]
        self.assertNotIn('heldoutmarker', word.vocabulary_)
        self.assertNotIn('neverfeature', word.vocabulary_)
        rows = [dict(record_id='new-id', include=True, description='kitchen oven baking',
                     context='', l1='wrong', l2='wrong', l3='', l4='', confidence=0)]
        result = apply_model(rows, self.paths, self.artifact)
        self.assertEqual(result['replaced'], 1)
        self.assertEqual((rows[0]['l1'], rows[0]['l2']), ('Catering', 'Ovens'))
        self.assertGreaterEqual(rows[0]['confidence'], .55)

    def test_unseen_taxonomy_excluded_and_empty_oov_keep_fallback(self):
        self.train()
        new_paths = [('Health', 'Medicines', '', '')]
        rows = [dict(include=True, description='kitchen oven baking')]
        classify_records(rows, new_paths)
        before = dict(rows[0])
        self.assertEqual(apply_model(rows, new_paths, self.artifact)['reason'], 'unseen_taxonomy')
        self.assertEqual(rows[0], before)
        rows = [dict(include=False, description='kitchen oven baking', l1=''),
                dict(include=True, description='', context='', l1='fallback'),
                dict(include=True, description='漢字漢字漢字', context='', l1='fallback')]
        self.assertEqual(apply_model(rows, self.paths, self.artifact)['replaced'], 0)
        self.assertEqual([r['l1'] for r in rows], ['', 'fallback', 'fallback'])

    def test_training_requires_explicit_partitions_or_all_labels(self):
        with self.assertRaisesRegex(ValueError, 'partition manifest'):
            train_model(self.records, self.label_path, self.artifact, label_columns=['cat1', 'cat2'])
        with self.assertRaises(ValueError):
            self.train(train_splits=('all',))
        metadata = train_model(self.records, self.label_path, self.artifact,
                               label_columns=['cat1', 'cat2'], train_splits=('all',),
                               valid_paths=self.paths)
        self.assertEqual(metadata['trained_records'], 25)
        self.assertFalse(metadata['partitioned'])

    def test_keys_and_ids_are_not_predictive_features(self):
        self.train()
        base = dict(include=True, description='vehicle tyre rubber', context='', l1='', l2='', l3='', l4='')
        rows = [dict(base, record_id='1000', supplier_id='different1', item_key='different1'),
                dict(base, record_id='9999', supplier_id='different2', item_key='different2')]
        apply_model(rows, self.paths, self.artifact)
        self.assertEqual([(r['l1'], r['l2'], r['confidence']) for r in rows],
                         [('Transport', 'Tyres', rows[0]['confidence'])] * 2)


if __name__ == '__main__':
    unittest.main()
