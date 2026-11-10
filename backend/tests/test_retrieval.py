"""Offline synthetic retrieval checks and production-corpus integration smoke tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from backend.app import retrieval as service
from backend.app.retrieval_support.index import LexicalIndex
from backend.app.retrieval_support.query import reject, rewrite
from backend.app.types import Turn
from evaluate import evaluate_chunks as ev

class RetrievalTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.chunks = [
            dict(chunk_id='doc001_p1_c1', doc_id='doc001', text='Undergraduate students drop a class through Orion before Census Day.',
                 source_title='Registration', section_heading='Drop a class'),
            dict(chunk_id='doc002_p1_c1', doc_id='doc002', text='Graduate students drop a class using the graduate withdrawal form.',
                 source_title='Graduate registration', section_heading='Drop a class'),
        ]
        (self.root / 'chunks').mkdir()
        (self.root / 'chunks/docs.json').write_text(json.dumps(self.chunks), encoding='utf-8')
        (self.root / 'documents.json').write_text(json.dumps([
            {'doc_id': 'doc001', 'source_url': 'https://utdallas.edu/drop'}, None]), encoding='utf-8')
        self.config = {**asdict(ev.load_settings()), 'chunks_path': 'chunks',
                       'registry_path': 'documents.json', 'min_term_coverage': .25, 'min_top_score': .3}
        self.path = self.root / 'config.json'
        self.path.write_text(json.dumps(self.config), encoding='utf-8')
        self.root_patch = patch.object(service, 'ROOT', self.root)
        self.config_patch = patch.object(service, 'CONFIG', self.path)
        self.root_patch.start()
        self.config_patch.start()
        service._load.cache_clear()

    def tearDown(self):
        service._load.cache_clear()
        self.config_patch.stop()
        self.root_patch.stop()
        self.temp.cleanup()

    def test_bad_queries_and_top_k(self):
        for query in ('', '   ', None, [], 3, '?!'):
            self.assertEqual(service.retrieve(query).reason, 'empty query')
        for value in (None, True, 0, -1, 9, '5'):
            self.assertTrue(service.retrieve('drop a class', top_k=value).abstain)

    def test_gibberish_and_weather(self):
        for query in ('xyzzyflarg blorptastic', 'what is the weather in Paris'):
            self.assertTrue(service.retrieve(query).abstain)
            self.assertEqual(service.retrieve(query).passages, [])

    def test_drop_and_source_url(self):
        result = service.retrieve('How do I drop a class?')
        self.assertFalse(result.abstain)
        self.assertEqual(next(p.source_url for p in result.passages if p.doc_id == 'doc001'),
                         'https://utdallas.edu/drop')

    def test_registry_absent_malformed_and_unsafe(self):
        self.assertEqual(service.load_urls(self.root / 'missing'), {})
        for value in ('invalid JSON', '{}', '[null, {"doc_id":"x","source_url":"javascript:alert(1)"}]'):
            self.path.write_text(value, encoding='utf-8')
            self.assertEqual(service.load_urls(self.path), {})

    def test_load_is_cached(self):
        with patch.object(ev, 'read_chunks', wraps=ev.read_chunks) as read:
            service.retrieve('drop a class')
            service.retrieve('graduate drop a class')
            stats = service.corpus_stats()
            stats['chunks'] = 999
            self.assertEqual(service.corpus_stats()['chunks'], 2)
            self.assertEqual(read.call_count, 1)

    def test_follow_up(self):
        history = [Turn('user', 'How do I drop a class?'), Turn('assistant', 'Use Orion.')]
        query = rewrite('what about graduate students?', history)
        self.assertIn('drop a class', query)
        self.assertFalse(service.retrieve('what about graduate students?', history=history).abstain)
        self.assertEqual(rewrite('what about graduate students?', [None, {'role': 'user'}]),
                         'what about graduate students?')
        self.assertEqual(rewrite('Where is the library?', history), 'Where is the library?')

    def test_budget_cap_top_k_and_baseline_parity(self):
        settings = ev.load_settings()
        index = LexicalIndex(self.chunks, settings)
        query = 'graduate students drop a class'
        expected = ev.Retriever(self.chunks, settings).retrieve(query)
        actual = index.search(query, 5)
        self.assertEqual([h['chunk_id'] for h in expected], [h['chunk_id'] for h in actual])
        for left, right in zip(expected, actual):
            self.assertAlmostEqual(left['retrieval_score'], right['retrieval_score'])
        limited = LexicalIndex(self.chunks, replace(settings, context_budget=1))
        self.assertEqual(limited.search(query, 8), [])
        self.assertLessEqual(len(service.retrieve(query, top_k=1).passages), 1)
        repeated = [dict(self.chunks[0], chunk_id=f'copy{i}') for i in range(5)]
        capped = LexicalIndex(repeated, replace(settings, max_per_document=1))
        self.assertEqual(len(capped.search('drop a class', 8)), 1)

    def test_evidence_checks_and_public_procedure(self):
        hits = LexicalIndex(self.chunks, ev.load_settings()).search('drop a class', 5)
        for query in ('Has my withdrawal been processed?', 'What is my cumulative GPA now?',
                      'What is the 2035 registration deadline?'):
            self.assertIsNotNone(reject(query, hits, self.config))
        self.assertIsNone(reject('I have a hold. How do I drop a class?', hits, self.config))


class RealCorpusSmokeTests(unittest.TestCase):
    def test_real_corpus(self):
        service._load.cache_clear()
        try:
            result = service.retrieve('How do I drop a class?')
            self.assertFalse(result.abstain)
            self.assertTrue(result.passages)
            self.assertLessEqual(sum(ev.cost(asdict(p)) for p in result.passages), 1200)
            self.assertGreater(service.corpus_stats()['documents'], 100)
        finally:
            service._load.cache_clear()

    def test_api_uses_real_retrieval_and_generation(self):
        from fastapi.testclient import TestClient
        from backend.app import generation
        from backend.app.config import Settings
        from backend.app.llm.extractive import ExtractiveLLM
        from backend.app.main import create_app

        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Settings(use_stubs=False, log_level='CRITICAL',
                                      database_path=Path(directory) / 'api.db'))
            self.assertIs(app.state.retrieval, service)
            generation.set_provider(ExtractiveLLM())
            try:
                with TestClient(app) as client:
                    self.assertEqual(client.get('/api/health').json()['retriever'], 'lexical')
                    body = client.post('/api/chat', json={'question': 'How do I drop a class?'}).json()
                    self.assertFalse(body['abstained'])
                    self.assertTrue(body['citations'])
                    self.assertEqual(client.post('/api/feedback', json={
                        'request_id': body['request_id'], 'rating': 'up'}).status_code, 204)
                    stream = client.post('/api/chat/stream', json={
                        'question': 'How do I drop a class?'}).text
                    self.assertIn('event: citations', stream)
                    self.assertIn('event: token', stream)
                    self.assertIn('event: done', stream)
                    self.assertNotIn('event: error', stream)
                    refusal = client.post('/api/chat', json={
                        'question': 'what is the weather in Paris'}).json()
                    self.assertTrue(refusal['abstained'])
                    self.assertEqual(refusal['citations'], [])
            finally:
                generation.set_provider(None)
                service._load.cache_clear()


if __name__ == '__main__':
    unittest.main()
