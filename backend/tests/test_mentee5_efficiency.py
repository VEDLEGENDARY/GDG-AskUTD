"""Mentee 5: the optimized LexicalIndex must return exactly what the frozen baseline returns."""
from __future__ import annotations

import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from pathlib import Path

from backend.app.retrieval_support.index import LexicalIndex
from evaluate import evaluate_chunks as ev
from evaluate.mentee5.baseline_index import BaselineLexicalIndex
from evaluate.mentee5.synthetic import make_corpus, make_queries, stress_queries

ROOT = Path(__file__).resolve().parents[2]
TOLERANCE = 1e-9  # Documented absolute score tolerance; observed difference is 0.0.


def production_settings() -> ev.Settings:
    config = ev.read_json(ROOT / 'backend/retrieval_config.json')
    settings = ev.Settings(**{f.name: config[f.name] for f in fields(ev.Settings)})
    settings.validate()
    return settings


class ParityMixin:
    def assert_parity(self, base, new, queries, top_ks=(8,)):
        for query in queries:
            for k in top_ks:
                expected, actual = base.search(query, k), new.search(query, k)
                label = f'{query[:60]!r} top_k={k}'
                self.assertEqual([h['chunk_id'] for h in expected], [h['chunk_id'] for h in actual], label)
                for left, right in zip(expected, actual):
                    self.assertLessEqual(abs(left['retrieval_score']-right['retrieval_score']), TOLERANCE, label)
                    self.assertEqual(left['estimated_tokens'], right['estimated_tokens'], label)
                    self.assertEqual({k: v for k, v in left.items() if k != 'retrieval_score'},
                                     {k: v for k, v in right.items() if k != 'retrieval_score'}, label)

    def assert_invariants(self, index, hits, top_k):
        s = index.s
        self.assertLessEqual(len(hits), top_k)
        self.assertLessEqual(sum(h['estimated_tokens'] for h in hits), s.context_budget)
        per_doc = {}
        for h in hits:
            per_doc[h['doc_id']] = per_doc.get(h['doc_id'], 0)+1
            self.assertGreater(h['retrieval_score'], 0)
            self.assertGreaterEqual(h['retrieval_score'], s.min_score)
            self.assertEqual(h['estimated_tokens'], ev.cost(h))
        self.assertTrue(all(v <= s.max_per_document for v in per_doc.values()))
        self.assertEqual(len({h['chunk_id'] for h in hits}), len(hits))


class SyntheticParityTests(ParityMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = production_settings()
        cls.chunks = make_corpus(700)
        cls.queries = make_queries(700, count=40) + stress_queries()

    def test_parity_production_settings_all_top_k(self):
        base, new = BaselineLexicalIndex(self.chunks, self.settings), LexicalIndex(self.chunks, self.settings)
        self.assert_parity(base, new, self.queries, top_ks=range(1, 9))
        for q in self.queries:
            self.assert_invariants(new, new.search(q, 8), 8)

    def test_parity_across_setting_extremes(self):
        variants = [
            dict(min_score=0.0), dict(min_score=1.0), dict(candidate_pool=8), dict(max_per_document=1),
            dict(context_budget=150), dict(lexical_weight=0.0), dict(lexical_weight=1.0),
            dict(metadata_weight=0.0), dict(metadata_weight=1.0), dict(diversity_lambda=0.0),
            dict(diversity_lambda=1.0), dict(bm25_b=0.0, bm25_k1=0.1), dict(candidate_pool=3000),
        ]
        for change in variants:
            with self.subTest(**change):
                settings = replace(self.settings, **change)
                self.assert_parity(BaselineLexicalIndex(self.chunks, settings),
                                   LexicalIndex(self.chunks, settings), self.queries[:25])

    def test_metadata_only_match_is_kept(self):
        settings = replace(self.settings, min_score=0.0)
        new = LexicalIndex(self.chunks, settings)
        hits = new.search('metaonly', 8)
        self.assertTrue(hits)
        self.assertTrue(all('metaonly' in h['source_title'] and 'metaonly' not in h['text'] for h in hits))
        self.assert_parity(BaselineLexicalIndex(self.chunks, settings), new, ['metaonly', 'metaonly guide'])

    def test_unknown_empty_and_zero_score_queries(self):
        new = LexicalIndex(self.chunks, self.settings)
        for q in ('', '   ', '?!', 'the of and', 'zzunknown qqunknown'):
            self.assertEqual(new.search(q, 5), [])
        self.assertEqual(new.search('registration', 0), [])

    def test_mutating_results_or_inputs_does_not_change_future_queries(self):
        chunks = copy.deepcopy(self.chunks)
        chunks[0]['tags'] = ['a', 'b']
        new = LexicalIndex(chunks, self.settings)
        query = chunks[0]['text']
        first = new.search(query, 8)
        snapshot = copy.deepcopy(first)
        for row in first:
            row['chunk_id'] = 'corrupted'
            row['retrieval_score'] = -1
            row.get('tags', []).append('corrupted')
        self.assertEqual(new.search(query, 8), snapshot)
        self.assertEqual(chunks[0]['tags'], ['a', 'b'])

    def test_settings_mutation_after_build_rebuilds_weights(self):
        settings = replace(self.settings)
        new = LexicalIndex(self.chunks, settings)
        new.search('registration tuition', 5)
        settings.bm25_k1, settings.bm25_b = 0.9, 0.3
        fresh = BaselineLexicalIndex(self.chunks, replace(settings))
        self.assert_parity(fresh, new, self.queries[:10])

    def test_concurrent_searches_on_one_instance(self):
        new = LexicalIndex(self.chunks, self.settings)
        queries = self.queries*4
        serial = [new.search(q, 5) for q in queries]
        with ThreadPoolExecutor(max_workers=8) as pool:
            parallel = list(pool.map(lambda q: new.search(q, 5), queries))
        self.assertEqual(serial, parallel)

    def test_duplicate_ids_and_tied_scores_break_ties_like_baseline(self):
        row = dict(chunk_id='same', doc_id='d', text='identical tuition refund text here',
                   source_title='T', section_heading='')
        chunks = [dict(row, doc_id=f'd{i}') for i in range(6)] + [dict(row, chunk_id=f'c{i}') for i in range(6)]
        settings = replace(self.settings, max_per_document=2)
        self.assert_parity(BaselineLexicalIndex(chunks, settings), LexicalIndex(chunks, settings),
                           ['tuition refund', 'identical text'], top_ks=range(1, 9))

    def test_production_never_imports_baseline(self):
        for path in (ROOT / 'backend/app').rglob('*.py'):
            self.assertNotIn('mentee5', path.read_text(encoding='utf-8'), path)


class RealCorpusParityTests(ParityMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = production_settings()
        cls.chunks = ev.read_chunks(ROOT / 'backend/data/chunks')
        questions = ev.read_questions(ROOT / 'evaluate/questions.json', cls.chunks, 'dev')
        cls.queries = [q['query'] for q in questions]
        cls.base = BaselineLexicalIndex(cls.chunks, cls.settings)
        cls.new = LexicalIndex(cls.chunks, cls.settings)

    def test_dev_split_exact_parity(self):
        # top_k=8 covers every smaller top_k: greedy selection for k is a prefix of selection for 8.
        self.assertGreaterEqual(len(self.queries), 50)
        self.assert_parity(self.base, self.new, self.queries)
        for q in self.queries:
            self.assert_invariants(self.new, self.new.search(q, 8), 8)

    def test_stress_fixture_parity(self):
        self.assert_parity(self.base, self.new, stress_queries(), top_ks=(1, 5, 8))

    def test_prefix_property_holds(self):
        for q in self.queries[:20]:
            full = [h['chunk_id'] for h in self.new.search(q, 8)]
            for k in range(1, 8):
                self.assertEqual([h['chunk_id'] for h in self.new.search(q, k)], full[:k])


if __name__ == '__main__':
    unittest.main()
