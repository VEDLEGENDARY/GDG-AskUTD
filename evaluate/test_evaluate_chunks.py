"""Regression checks for evaluator validation, scoring, and branch exports."""
import json
import io
import math
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from evaluate_chunks import (
    REPO_ROOT, ROOT, Retriever, load_settings, export_branch, grade,
    read_chunks, read_questions,
    supports, benchmark_audit, evidence_feasible, check_output_path, read_json, main,
)


def settings(**overrides):
    return replace(load_settings(), **overrides)


class EvaluatorTests(unittest.TestCase):
    def test_large_and_small_finite_bm25_parameters_produce_finite_scores(self):
        chunk = dict(chunk_id='a', doc_id='d1', text='graduation graduation deadline')
        for value in (1e308, 1e-308):
            with self.subTest(value=value):
                hits = Retriever([chunk], settings(bm25_k1=value, min_chunk_words=1)).retrieve('graduation')
                self.assertTrue(hits)
                self.assertTrue(math.isfinite(hits[0]['retrieval_score']))

    def test_evidence_requires_complete_words(self):
        group = dict(doc_id='d1', all_of=['six'])
        self.assertFalse(supports(dict(doc_id='d1', text='sixteen hours'), group))
        self.assertTrue(supports(dict(doc_id='d1', text='Six, hours'), group))

    def test_duplicate_json_keys_and_nonfinite_literals_are_rejected(self):
        for text in ('{"top_k": 1, "top_k": 2}', '[NaN]', '[Infinity]', '[-Infinity]'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                read_json(Mock(read_text=Mock(return_value=text)))

    def test_extreme_or_nonfinite_numeric_settings_raise_validation_error(self):
        for value in (10**400, float('nan'), float('inf'), -1, 0, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings(bm25_k1=value).validate()

    def test_retrieval_ties_are_independent_of_corpus_order(self):
        chunks = [dict(chunk_id='b', doc_id='b', text='graduation deadline application guide'),
                  dict(chunk_id='a', doc_id='a', text='graduation deadline application guide')]
        for rows in (chunks, list(reversed(chunks))):
            hits = Retriever(rows, settings(min_chunk_words=1, top_k=1)).retrieve('graduation')
            self.assertEqual(hits[0]['chunk_id'], 'a')

    def test_reports_cannot_overwrite_inputs_or_enter_chunk_directories(self):
        config, questions, chunks = ROOT / 'config.example.json', ROOT / 'questions.json', REPO_ROOT / 'backend/data/chunks'
        for output in (config, questions, chunks / 'report.json', ROOT / 'evaluate_chunks.py'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                check_output_path(output, config, questions, chunks)
        check_output_path(ROOT / 'runs/example.json', config, questions, chunks)

    def test_cli_reports_missing_inputs_and_empty_queries_without_tracebacks(self):
        cases = [(['--config', str(ROOT / 'does-not-exist.json')], 'evaluate_chunks:'),
                 (['--query', ''], 'searchable words'),
                 (['--output', str(ROOT / 'questions.json')], 'overwrite')]
        for arguments, message in cases:
            output = io.StringIO()
            with self.subTest(arguments=arguments), patch('sys.argv', ['evaluate_chunks.py', *arguments]), redirect_stderr(output):
                self.assertEqual(main(), 1)
                self.assertIn(message, output.getvalue())
                self.assertNotIn('Traceback', output.getvalue())

    def test_conflicting_cli_modes_are_rejected(self):
        with patch('sys.argv', ['evaluate_chunks.py', '--query', 'FERPA', '--validate-only']), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)

    def test_validate_only_returns_failure_for_impossible_evidence(self):
        chunk = dict(chunk_id='a', doc_id='d1', text='the deadline is tomorrow morning')
        question = dict(id='a', query='When is the deadline?', split='dev', category='policy',
                        unanswerable=False, evidence=[dict(doc_id='d1', all_of=['deadline'])])
        with patch('sys.argv', ['evaluate_chunks.py', '--validate-only']), \
                patch('evaluate_chunks.load_settings', return_value=settings(context_budget=1)), \
                patch('evaluate_chunks.read_chunks', return_value=[chunk]), \
                patch('evaluate_chunks.read_questions', return_value=[question]), redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 1)

    def test_selected_split_ignores_other_splits_evidence(self):
        dev = dict(id='dev-a', query='Which required policy applies?', split='dev',
                   category='policy', unanswerable=False,
                   evidence=[dict(doc_id='missing', all_of=['unavailable evidence'])])
        test = dict(id='test-a', query='What is my current balance?', split='test',
                    category='private_data', unanswerable=True, evidence=[])
        for rows in ([dev, test], [test, dev]):
            path = Mock(read_text=Mock(return_value=json.dumps(rows)))
            self.assertEqual(read_questions(path, [], split='test'), [test])
            with self.assertRaisesRegex(ValueError, 'evidence missing'):
                read_questions(path, [], split='dev')

    def test_identity_category_and_order_do_not_change_grading(self):
        first = dict(id='lokesh-question', category='lokesh', query='What is the deadline?',
                     split='dev', unanswerable=False,
                     evidence=[dict(doc_id='d1', all_of=['deadline is tomorrow'])])
        second = dict(first, id='shaju-question', category='another-category')
        retriever = Retriever([dict(chunk_id='c1', doc_id='d1',
                                    text='The application deadline is tomorrow morning.')], settings())
        expected = grade(first, retriever.retrieve(first['query']))
        self.assertEqual(expected['complete_evidence'], 1)
        for questions in ([first, second], [second, first]):
            for question in questions:
                self.assertEqual(grade(question, retriever.retrieve(question['query'])), expected)

    def test_question_section_comments_preserve_question_strings(self):
        rows = [dict(id='url-example', query='What is at https://example.com/a//b?',
                     split='dev', category='example', unanswerable=True, evidence=[])]
        text = json.dumps(rows)
        commented = text.replace('[', '[\n  // Lokesh questions:\n\n\n\n'
                                 '  // Shaju questions:\n\n\n\n'
                                 '  // Already have these questions:\n\n\n\n', 1)
        self.assertEqual(read_questions(Mock(read_text=Mock(return_value=commented)), []), rows)

    def test_comments_do_not_allow_malformed_question_json(self):
        with self.assertRaises(json.JSONDecodeError):
            read_questions(Mock(read_text=Mock(return_value='[\n// heading\n{broken}]')), [])

    def test_settings_come_from_selected_json(self):
        config = asdict(load_settings())
        config['top_k'] = 1
        path = Mock(read_text=Mock(return_value=json.dumps(config)))
        self.assertEqual(load_settings(path).top_k, 1)

    def test_incomplete_unknown_and_nonobject_configs_are_rejected(self):
        config = asdict(load_settings())
        missing = {key: value for key, value in config.items() if key != 'top_k'}
        for invalid in (missing, {**config, 'top_kk': 1}, [], None):
            with self.subTest(config=invalid), self.assertRaises(ValueError):
                load_settings(Mock(read_text=Mock(return_value=json.dumps(invalid))))

    def test_boolean_numeric_settings_are_rejected(self):
        for field in ('bm25_k1', 'bm25_b', 'lexical_weight', 'metadata_weight',
                      'diversity_lambda', 'min_score'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                settings(**{field: True}).validate()

    def test_default_benchmark_has_valid_evidence_and_both_question_types(self):
        chunks = read_chunks(REPO_ROOT / 'backend/data/chunks')
        questions = read_questions(ROOT / 'questions.json', chunks)
        eligible = Retriever(chunks, settings()).chunks
        for split in ('dev', 'test'):
            selected = [q for q in questions if q['split'] == split]
            self.assertEqual({q['unanswerable'] for q in selected}, {True, False})
            self.assertGreaterEqual(len(selected), 32)
            audit = benchmark_audit(selected, eligible, settings())
            self.assertEqual(audit['infeasible_question_ids'], [])
            self.assertGreaterEqual(audit['multi_evidence'], 20)
            self.assertGreaterEqual(audit['evidence_documents'], 15)
            self.assertTrue(all(q.get('unanswerable_reason') for q in selected if q['unanswerable']))

    def test_all_required_phrases_must_be_in_supporting_chunk(self):
        group = dict(doc_id='d1', all_of=['minimum grade', 'C or better'])
        self.assertFalse(supports(dict(doc_id='d1', text='minimum grade is D'), group))
        self.assertTrue(supports(dict(doc_id='d1', text='Minimum grade: C or better'), group))

    def test_equivalent_sources_are_allowed_but_wrong_catalog_is_not(self):
        chunk = dict(doc_id='d2', text='twelve technical elective hours')
        self.assertTrue(supports(chunk, dict(doc_ids=['d1', 'd2'], all_of=['technical elective hours'])))
        self.assertFalse(supports(chunk, dict(doc_id='d1', all_of=['technical elective hours'])))

    def test_legacy_any_of_labels_remain_supported(self):
        self.assertTrue(supports(dict(doc_id='d1', text='first wording'),
                                 dict(doc_id='d1', any_of=['first wording', 'second wording'])))

    def test_oracle_checks_document_caps_and_budget(self):
        chunks = [dict(chunk_id='a', doc_id='d1', text='first fact'),
                  dict(chunk_id='b', doc_id='d1', text='second fact')]
        question = dict(evidence=[dict(doc_id='d1', all_of=['first fact']),
                                  dict(doc_id='d1', all_of=['second fact'])])
        self.assertTrue(evidence_feasible(question, chunks, settings()))
        self.assertFalse(evidence_feasible(question, chunks, settings(max_per_document=1)))
        self.assertFalse(evidence_feasible(question, chunks, settings(top_k=1)))
        self.assertFalse(evidence_feasible(question, chunks, settings(context_budget=1)))

    def test_oracle_can_cover_multiple_groups_with_one_chunk(self):
        chunk = dict(chunk_id='a', doc_id='d1', text='first fact and second fact')
        question = dict(evidence=[dict(doc_id='d1', all_of=['first fact']),
                                  dict(doc_id='d1', all_of=['second fact'])])
        self.assertTrue(evidence_feasible(question, [chunk], settings(top_k=1)))

    def test_duplicate_queries_across_splits_are_rejected(self):
        base = dict(query='My appointment?', category='private_data', unanswerable=True, evidence=[])
        rows = [dict(base, id='a', split='dev'), dict(base, id='b', split='test', query='MY appointment!')]
        with self.assertRaisesRegex(ValueError, 'duplicate normalized query'):
            read_questions(Mock(read_text=Mock(return_value=json.dumps(rows))), [])

    def test_invalid_and_duplicate_evidence_is_rejected(self):
        chunk = dict(doc_id='d1', text='supporting phrase')
        valid = dict(doc_id='d1', all_of=['supporting phrase'])
        cases = [
            [dict(doc_id='d1', all_of=[])],
            [dict(doc_id='d1', all_of=['!!!'])],
            [dict(doc_id='d1', doc_ids=['d1'], all_of=['supporting phrase'])],
            [dict(doc_ids=['d1', 'd1'], all_of=['supporting phrase'])],
            [valid, valid],
            [dict(doc_id='d1', all_of=['missing fact'])],
            [dict(doc_id='d1', all_of=['supporting phrase'], any_off=['ignored typo'])],
        ]
        for evidence in cases:
            rows = [dict(id='a', query='Where is the supporting evidence?', split='dev',
                         category='example', unanswerable=False, evidence=evidence)]
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                read_questions(Mock(read_text=Mock(return_value=json.dumps(rows))), [chunk])

    def test_returning_context_for_unanswerable_question_is_incorrect(self):
        question = dict(unanswerable=True, evidence=[])
        hit = dict(doc_id='d1', text='related policy', estimated_tokens=4)
        self.assertEqual(grade(question, [hit])['abstention_correct'], 0)
        self.assertEqual(grade(question, [])['abstention_correct'], 1)

    def test_context_budget_can_force_abstention(self):
        chunk = dict(chunk_id='c1', doc_id='d1', text='graduation application deadline')
        retriever = Retriever([chunk], settings(min_chunk_words=1, context_budget=1))
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
