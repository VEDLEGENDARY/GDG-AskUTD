"""Regression checks for evaluator validation, scoring, and branch exports."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evaluate_chunks import (
    REPO_ROOT, ROOT, Retriever, Settings, export_branch, grade,
    read_chunks, read_questions,
)


class EvaluatorTests(unittest.TestCase):
    def test_boolean_numeric_settings_are_rejected(self):
        for field in ('bm25_k1', 'bm25_b', 'lexical_weight', 'metadata_weight',
                      'diversity_lambda', 'min_score'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                Settings(**{field: True}).validate()

    def test_default_benchmark_has_valid_evidence_and_both_question_types(self):
        questions = read_questions(ROOT / 'questions.json', read_chunks(REPO_ROOT / 'backend/data/chunks'))
        for split in ('dev', 'test'):
            selected = [q for q in questions if q['split'] == split]
            self.assertEqual({q['unanswerable'] for q in selected}, {True, False})

    def test_context_budget_can_force_abstention(self):
        chunk = dict(chunk_id='c1', doc_id='d1', text='graduation application deadline')
        retriever = Retriever([chunk], Settings(min_chunk_words=1, context_budget=1))
        self.assertEqual(retriever.retrieve('graduation'), [])

    def test_partial_evidence_does_not_count_as_complete(self):
        q = dict(unanswerable=False, evidence=[
            dict(doc_id='d1', any_of=['graduation']),
            dict(doc_id='d2', any_of=['deadline']),
        ])
        hits = [dict(doc_id='d1', text='graduation', estimated_tokens=3)]
        metrics = grade(q, hits)
        self.assertEqual(metrics['evidence_recall'], 0.5)
        self.assertEqual(metrics['complete_evidence'], 0)
        self.assertEqual(metrics['reciprocal_rank'], 1)

    def test_export_uses_repository_root_and_preserves_bytes(self):
        payload = json.dumps([dict(chunk_id='c1', doc_id='d1', text='example')]).encode()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'export'
            with patch('evaluate_chunks.subprocess.check_output', side_effect=[
                'backend/data/chunks/example.json\n', payload,
            ]) as command:
                export_branch('HEAD', output)
            self.assertEqual((output / 'example.json').read_bytes(), payload)
            for call in command.call_args_list:
                self.assertEqual(call.kwargs['cwd'], REPO_ROOT)


if __name__ == '__main__':
    unittest.main()
