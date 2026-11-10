"""Tests for the mentee 1 evaluation harness (scripts/mentee1_eval.py).

Synthetic tests run offline on a tiny in-memory corpus. The fixture test verifies
the committed regression cases against the real corpus.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from backend.app.types import Passage, RetrievalResult, Turn
from evaluate import evaluate_chunks as ev

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('mentee1_eval', ROOT / 'scripts' / 'mentee1_eval.py')
m1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m1)

CHUNKS = [
    dict(chunk_id='doc001_p1_c1', doc_id='doc001', source_title='Undergraduate registration', section_heading='Drop',
         text='Undergraduate students may drop a class online through Orion before Census Day without a W.'),
    dict(chunk_id='doc002_p1_c1', doc_id='doc002', source_title='Graduate registration', section_heading='Drop',
         text='Graduate students may drop a class with the graduate withdrawal form before Census Day without a W.'),
    dict(chunk_id='doc003_p1_c1', doc_id='doc003', source_title='Fall calendar', section_heading='Full term',
         text='Census Day for the full term session is Sept. 9 and the withdrawal period ends Nov. 9.'),
    dict(chunk_id='doc003_p1_c2', doc_id='doc003', source_title='Fall calendar', section_heading='First 8-week',
         text='Census Day for the first 8-week session is Aug. 31 and the withdrawal period ends Sept. 28.'),
    dict(chunk_id='doc004_p1_c1', doc_id='doc004', source_title='Transcripts', section_heading='Fees',
         text='Official transcripts cost ten dollars each and are ordered online through Parchment.'),
]
URLS = {'doc001': 'https://example.utdallas.edu/drop', 'doc003': 'https://example.utdallas.edu/calendar'}


def answerable(**overrides):
    case = {
        'id': 'm1-test-ug-drop', 'category': 'population_contrast',
        'query': 'How do undergraduates drop a class before Census Day?', 'unanswerable': False,
        'requirement': 'One group: the undergraduate drop procedure.',
        'evidence': [{'id': 'ug-drop', 'support': [
            {'chunk_id': 'doc001_p1_c1', 'quote': 'drop a class online through Orion'}]}],
        'distractors': [{'chunk_id': 'doc002_p1_c1', 'reason': 'graduate procedure, wrong population'}],
    }
    case.update(overrides)
    return case


def unanswerable(**overrides):
    case = {
        'id': 'm1-test-headcount', 'category': 'unanswerable',
        'query': 'How many students are enrolled in computer science?', 'unanswerable': True, 'evidence': [],
        'unanswerable_reason': 'The synthetic corpus describes procedures and dates but has no enrollment counts.',
        'absence_checks': ['searched enrolled, headcount, number of students'],
        'nearest_related': [{'chunk_id': 'doc001_p1_c1', 'reason': 'registration procedure, no counts'}],
    }
    case.update(overrides)
    return case


def two_group():
    return answerable(
        id='m1-test-census-both', category='time_contrast',
        query='Compare Census Day for the full term and the first 8-week session.',
        requirement='All groups are required: each session has its own census date.',
        evidence=[{'id': 'full', 'support': [{'chunk_id': 'doc003_p1_c1', 'quote': 'full term session is Sept. 9'}]},
                  {'id': 'first8', 'support': [{'chunk_id': 'doc003_p1_c2', 'quote': 'first 8-week session is Aug. 31'}]}],
        distractors=[])


def doc(cases):
    return {'schema_version': 1, 'cases': cases}


class Fixture(unittest.TestCase):
    def setUp(self):
        _, self.settings = m1.load_config()
        self.corpus = m1.Corpus(copy.deepcopy(CHUNKS), self.settings)

    def errors(self, case):
        return m1.validate_case(case, self.corpus)


class LabelValidationTests(Fixture):
    def test_valid_cases_pass(self):
        for case in (answerable(), unanswerable(), two_group()):
            self.assertEqual(self.errors(case), [], case['id'])

    def test_invalid_labels_are_rejected(self):
        bad = {
            'bad category': answerable(category='easy'),
            'bad id': answerable(id='Bad ID!'),
            'unknown key': answerable(label_answer='42'),
            'answerable without evidence': answerable(evidence=[]),
            'unanswerable with evidence': unanswerable(evidence=answerable()['evidence']),
            'unanswerable without reason': unanswerable(unanswerable_reason='no'),
            'unanswerable without checks': unanswerable(absence_checks=[]),
            'missing requirement': answerable(requirement=''),
            'history outside follow_up': answerable(history=[{'role': 'user', 'content': 'hi there'}]),
            'follow_up without history': answerable(category='follow_up'),
            'follow_up assistant only': answerable(category='follow_up',
                                                   history=[{'role': 'assistant', 'content': 'Use Orion.'}]),
            'non-boolean unanswerable': answerable(unanswerable='no'),
            'distractor is evidence': answerable(distractors=[{'chunk_id': 'doc001_p1_c1', 'reason': 'x'}]),
            'unanswerable category answerable': answerable(category='unanswerable'),
            'answerable with reason': answerable(unanswerable_reason='x' * 50),
        }
        for name, case in bad.items():
            with self.subTest(name):
                self.assertTrue(self.errors(case), name)
        multi = two_group()
        multi['requirement'] = 'Both dates.'
        self.assertTrue(any('all groups' in e for e in self.errors(multi)))

    def test_missing_chunk_ids_are_rejected(self):
        case = answerable(evidence=[{'id': 'g', 'support': [{'chunk_id': 'doc999_p1_c1', 'quote': 'drop a class online'}]}])
        self.assertTrue(any('missing from the corpus' in e for e in self.errors(case)))
        self.assertTrue(any('missing from the corpus' in e for e in self.errors(
            answerable(distractors=[{'chunk_id': 'doc404_p9_c9', 'reason': 'gone'}]))))
        self.assertTrue(any('missing from the corpus' in e for e in self.errors(
            unanswerable(nearest_related=[{'chunk_id': 'nope', 'reason': 'gone'}]))))

    def test_mismatched_quotes_are_rejected(self):
        changed = answerable(evidence=[{'id': 'g', 'support': [
            {'chunk_id': 'doc001_p1_c1', 'quote': 'drop a class online through Galaxy'}]}])
        self.assertTrue(any('does not occur' in e for e in self.errors(changed)))
        wrong_chunk = answerable(evidence=[{'id': 'g', 'support': [
            {'chunk_id': 'doc002_p1_c1', 'quote': 'drop a class online through Orion'}]}])
        self.assertTrue(any('does not occur' in e for e in self.errors(wrong_chunk)))
        short = answerable(evidence=[{'id': 'g', 'support': [{'chunk_id': 'doc001_p1_c1', 'quote': 'Orion'}]}])
        self.assertTrue(any('at least' in e for e in self.errors(short)))
        partial_word = answerable(evidence=[{'id': 'g', 'support': [
            {'chunk_id': 'doc001_p1_c1', 'quote': 'drop a class onl'}]}])
        self.assertTrue(any('does not occur' in e for e in self.errors(partial_word)))

    def test_same_words_in_unlisted_chunk_must_be_resolved(self):
        shared = 'before Census Day without a W'
        case = answerable(evidence=[{'id': 'g', 'support': [{'chunk_id': 'doc001_p1_c1', 'quote': shared}]}],
                          distractors=[])
        self.assertTrue(any('unlisted chunks' in e and 'doc002_p1_c1' in e for e in self.errors(case)))
        case['evidence'][0]['not_equivalent'] = [{'chunk_id': 'doc002_p1_c1', 'reason': 'graduate, not undergraduate'}]
        self.assertEqual(self.errors(case), [])

    def test_document_level_checks(self):
        cases, errors = m1.validate_cases(doc([answerable(), answerable()]), self.corpus, require_coverage=False)
        self.assertTrue(any('duplicate case id' in e for e in errors))
        _, errors = m1.validate_cases({'cases': []}, self.corpus)
        self.assertTrue(errors)
        _, errors = m1.validate_cases(doc([answerable()]), self.corpus, require_coverage=True)
        self.assertTrue(any('at least 30' in e for e in errors))
        self.assertTrue(any('unanswerable' in e for e in errors))
        follow = answerable(id='m1-test-follow', category='follow_up', query='How do undergraduates drop a class before Census Day?',
                            history=[{'role': 'user', 'content': 'I need to leave a course.'}])
        _, errors = m1.validate_cases(doc([answerable(), follow]), self.corpus, require_coverage=False)
        self.assertEqual(errors, [], 'same query with different history is a different case')

    def test_oracle_feasibility(self):
        self.assertTrue(m1.oracle_feasible(two_group(), self.corpus, self.settings, 5))
        self.assertFalse(m1.oracle_feasible(two_group(), self.corpus, self.settings, 1))
        tight = replace(self.settings, context_budget=10)
        self.assertFalse(m1.oracle_feasible(two_group(), self.corpus, tight, 5))


class GradingTests(Fixture):
    def hits(self, *ids, score=1.0):
        out = []
        for cid in ids:
            row = dict(self.corpus.by_id[cid], score=score, source_url=URLS.get(self.corpus.by_id[cid]['doc_id']))
            row['estimated_tokens'] = ev.cost(row)
            out.append(row)
        return out

    def test_metric_parity_with_evaluate_chunks_grade(self):
        rng = random.Random(7)
        case = two_group()
        phrase_q = {'unanswerable': False, 'evidence': [
            {'doc_id': 'doc003', 'all_of': ['full term session is Sept. 9']},
            {'doc_id': 'doc003', 'all_of': ['first 8-week session is Aug. 31']}]}
        ids = [c['chunk_id'] for c in CHUNKS]
        for _ in range(200):
            chosen = rng.sample(ids, rng.randint(0, len(ids)))
            hits = self.hits(*chosen)
            ours = m1.grade_case(case, hits)
            theirs = ev.grade(phrase_q, hits)
            for key, value in theirs.items():
                self.assertEqual(ours[key], value, (key, chosen))
        una = unanswerable()
        for chosen in ([], ['doc001_p1_c1']):
            hits = self.hits(*chosen)
            self.assertEqual({k: m1.grade_case(una, hits)[k] for k in ev.grade(una, hits)}, ev.grade(una, hits))

    def test_distractor_metrics(self):
        case = answerable()
        wrong_first = m1.grade_case(case, self.hits('doc002_p1_c1', 'doc001_p1_c1'))
        self.assertEqual((wrong_first['distractor_hits'], wrong_first['distractor_before_evidence']), (1, 1))
        self.assertEqual(wrong_first['reciprocal_rank'], .5)
        only_wrong = m1.grade_case(case, self.hits('doc002_p1_c1'))
        self.assertEqual((only_wrong['complete_evidence'], only_wrong['distractor_before_evidence']), (0, 1))
        right_first = m1.grade_case(case, self.hits('doc001_p1_c1', 'doc002_p1_c1'))
        self.assertEqual(right_first['distractor_before_evidence'], 0)


def make_adapter(fn, name='synthetic'):
    return m1.Adapter(name, fn)


class RunTests(Fixture):
    def setUp(self):
        super().setUp()
        self.cases = [answerable(), two_group(), unanswerable()]
        self.suites = {'mentee1': {'path': str(ROOT / 'synthetic.json'), 'sha256': 'synthetic', 'items': [
            {'suite': 'mentee1', 'id': c['id'], 'category': c['category'], 'query': c['query'],
             'history': c.get('history'), 'unanswerable': c['unanswerable'], 'label': c} for c in self.cases]}}

    def passages(self, *ids, **changes):
        return [Passage(chunk_id=cid, doc_id=self.corpus.by_id[cid]['doc_id'], text=self.corpus.by_id[cid]['text'],
                        source_title=self.corpus.by_id[cid]['source_title'],
                        section_heading=self.corpus.by_id[cid]['section_heading'], score=changes.get('score', .8),
                        source_url=changes.get('url', URLS.get(self.corpus.by_id[cid]['doc_id']))) for cid in ids]

    def run_adapter(self, fn, **kwargs):
        return m1.run(make_adapter(fn), self.suites, self.corpus, self.settings, URLS, **kwargs)

    def oracle(self, query, top_k, history):
        if 'drop' in query:
            return RetrievalResult(passages=self.passages('doc001_p1_c1'))
        if 'Census' in query:
            return RetrievalResult(passages=self.passages('doc003_p1_c1', 'doc003_p1_c2'))
        return RetrievalResult(abstain=True, reason='no evidence')

    def test_all_abstain_retriever_is_caught(self):
        report = self.run_adapter(lambda q, k, h: RetrievalResult(abstain=True, reason='nope'), repeat=1)
        s = report['suites']['mentee1']['summary']
        self.assertTrue(s['flags']['all_abstain'])
        self.assertEqual(s['answerability']['false_refusal_rate'], 1.0)
        self.assertEqual(s['answerability']['false_acceptance_rate'], 0.0)
        self.assertEqual(s['quality_answerable']['complete_evidence'], 0.0)
        self.assertTrue(any('abstained on every case' in f for f in m1.gate_failures(report)))
        good = self.run_adapter(self.oracle, repeat=1)
        self.assertEqual(m1.gate_failures(good), [])
        diff = m1.compare(good, report)
        self.assertEqual(len([q for q in diff['regressions'] if 'newly refuses answerable' in q['regressions']]), 2)
        self.assertTrue(m1.compare_gate_failures(diff, False, None))

    def test_answer_everything_is_caught(self):
        report = self.run_adapter(lambda q, k, h: self.passages('doc001_p1_c1'), repeat=1)
        s = report['suites']['mentee1']['summary']
        self.assertTrue(s['flags']['never_abstains_on_unanswerable'])
        self.assertEqual(s['answerability']['false_acceptance_rate'], 1.0)
        self.assertEqual(s['distractors']['unanswerable_with_nearest_related_hits'], 1)
        self.assertTrue(m1.gate_failures(report))

    def test_oracle_scores_perfectly_and_separates_answerability(self):
        report = self.run_adapter(self.oracle, repeat=2)
        s = report['suites']['mentee1']['summary']
        self.assertEqual(s['quality_answerable']['complete_evidence'], 1.0)
        self.assertEqual(s['quality_answerable']['context_precision'], 1.0)
        self.assertEqual((s['answerability']['false_refusal_rate'], s['answerability']['false_acceptance_rate']), (0, 0))
        self.assertEqual(set(report['suites']['mentee1']['by_category']),
                         {'population_contrast', 'time_contrast', 'unanswerable'})
        self.assertEqual(report['timing']['timed_calls'], 6)
        self.assertTrue(all(len(r['latency_ms']) == 2 for r in report['rows']))
        self.assertIn('not probabilities', report['score_note'])
        markdown = m1.render_run(report)
        self.assertIn('False acceptance', markdown)
        self.assertIn('population_contrast', markdown)

    def test_integrity_violations(self):
        long_text = 'word ' * 6000
        scenarios = {
            'over_context_budget': lambda: [dict(chunk_id='doc001_p1_c1', doc_id='doc001', text=long_text, score=1)],
            'duplicate_chunk_id': lambda: self.passages('doc001_p1_c1', 'doc001_p1_c1'),
            'unknown_chunk_id': lambda: [dict(chunk_id='doc777_p1_c1', doc_id='doc777', text='invented', score=1)],
            'passage_text_or_doc_mismatch': lambda: [dict(chunk_id='doc001_p1_c1', doc_id='doc001',
                                                          text='History says there are 5,000 CS students.', score=1)],
            'unsafe_url': lambda: self.passages('doc001_p1_c1', url='javascript:alert(1)'),
            'missing_or_mismatched_url': lambda: self.passages('doc001_p1_c1', url=None),
            'url_not_in_registry': lambda: self.passages('doc004_p1_c1', url='https://invented.example'),
            'non_positive_or_invalid_score': lambda: self.passages('doc001_p1_c1', score=0),
            'top_k_exceeded': lambda: self.passages('doc001_p1_c1', 'doc002_p1_c1', 'doc003_p1_c1'),
            'abstain_with_passages': lambda: RetrievalResult(passages=self.passages('doc001_p1_c1'), abstain=True),
            'empty_without_abstain': lambda: RetrievalResult(passages=[], abstain=False),
            'malformed_passage': lambda: [{'text': 'no id'}],
            'adapter_error': lambda: 1 / 0,
        }
        for violation, make in scenarios.items():
            with self.subTest(violation):
                report = self.run_adapter(lambda q, k, h: make(), repeat=1, top_k=2)
                found = {v for r in report['rows'] for v in r['integrity']}
                self.assertIn(violation, found)
                self.assertTrue(m1.gate_failures(report))
        capped = replace(self.settings, max_per_document=1)
        report = m1.run(make_adapter(lambda q, k, h: self.passages('doc003_p1_c1', 'doc003_p1_c2')),
                        self.suites, self.corpus, capped, URLS, repeat=1)
        self.assertIn('document_cap_exceeded', report['rows'][0]['integrity'])

    def test_adapter_receives_only_query_top_k_and_history(self):
        follow = answerable(id='m1-test-follow', category='follow_up', query='what about graduate students?',
                            history=[{'role': 'user', 'content': 'How do undergraduates drop a class?'},
                                     {'role': 'assistant', 'content': 'There are 5,000 CS students.'}])
        self.suites['mentee1']['items'].append({'suite': 'mentee1', 'id': follow['id'], 'category': 'follow_up',
                                                'query': follow['query'], 'history': follow['history'],
                                                'unanswerable': False, 'label': follow})
        calls = []

        def spy(*args, **kwargs):
            calls.append((args, kwargs))
            return RetrievalResult(abstain=True)

        self.run_adapter(spy, repeat=1, top_k=4)
        self.assertTrue(calls)
        for args, kwargs in calls:
            self.assertEqual(kwargs, {})
            self.assertEqual(len(args), 3)
            query, top_k, history = args
            self.assertIsInstance(query, str)
            self.assertEqual(top_k, 4)
            self.assertTrue(history is None or all(isinstance(t, Turn) for t in history))
            self.assertNotIn('evidence', repr(args))
            self.assertNotIn('doc001_p1_c1', repr(args))
        with_history = [a for a, _ in calls if a[2]]
        self.assertEqual(with_history[0][2][0], Turn('user', 'How do undergraduates drop a class?'))

    def test_fixed_order_repetitions_and_nondeterminism(self):
        seen = []
        report = self.run_adapter(lambda q, k, h: seen.append(q) or RetrievalResult(abstain=True), repeat=3)
        ids = [r['id'] for r in report['rows']]
        self.assertEqual(ids, sorted(ids))
        # Without warmup(), one untimed cold call precedes three identical ordered passes.
        self.assertEqual(len(seen), 1 + 3 * 3)
        self.assertEqual(seen[1:4], seen[4:7])
        self.assertEqual(seen[1:4], seen[7:10])
        flip = {'n': 0}

        def unstable(q, k, h):
            flip['n'] += 1
            return self.passages('doc001_p1_c1') if flip['n'] % 2 else self.passages('doc002_p1_c1')

        report = self.run_adapter(unstable, repeat=2)
        self.assertTrue(any('nondeterministic_ranking' in r['integrity'] for r in report['rows']))
        with self.assertRaises(m1.HarnessError):
            self.run_adapter(self.oracle, top_k=9)
        with self.assertRaises(m1.HarnessError):
            self.run_adapter(self.oracle, repeat=0)

    def test_compare_requires_identical_inputs_and_reports_deltas(self):
        base = self.run_adapter(self.oracle, repeat=1)
        cand = self.run_adapter(lambda q, k, h: self.passages('doc002_p1_c1', 'doc001_p1_c1')
                                if 'drop' in q else self.oracle(q, k, h), repeat=1)
        diff = m1.compare(base, cand)
        row = next(q for q in diff['per_query'] if q['id'] == 'm1-test-ug-drop')
        self.assertEqual(row['delta']['context_precision'], -.5)
        self.assertIn('distractor now outranks evidence', row['regressions'])
        self.assertFalse(diff['identical_rankings'])
        self.assertTrue(m1.compare_gate_failures(diff, True, None))
        self.assertIn('Regressions (1)', m1.render_compare(diff))
        same = m1.compare(base, copy.deepcopy(base))
        self.assertEqual(m1.compare_gate_failures(same, True, None), [])
        other = copy.deepcopy(cand)
        other['inputs']['corpus_sha256'] = 'different'
        with self.assertRaises(m1.HarnessError):
            m1.compare(base, other)
        self.assertIn('corpus differs', m1.compare(base, other, allow_mismatch=True)['notes'])
        relabeled = copy.deepcopy(cand)
        relabeled['inputs']['suites']['mentee1']['sha256'] = 'edited'
        with self.assertRaises(m1.HarnessError):
            m1.compare(base, relabeled)

    def test_load_adapter_from_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'candidate.py'
            path.write_text('def retrieve(query, top_k, history):\n    """Always empty."""\n    return []\n',
                            encoding='utf-8')
            adapter = m1.load_adapter(f'{path}:retrieve')
            self.assertEqual(adapter('q', 5, None), [])
            self.assertEqual(adapter.description, 'Always empty.')
        with self.assertRaises(m1.HarnessError):
            m1.load_adapter('no-colon')
        self.assertEqual(m1.load_adapter('always-abstain')('q', 5, None).abstain, True)


class PeerAndSafetyTests(unittest.TestCase):
    def test_peer_overlap_detection_is_read_only(self):
        peers = m1._peer_items([{'id': 'p1', 'query': 'How do undergraduates drop a class before Census Day?',
                                 'evidence': [{'doc_id': 'doc001', 'all_of': ['drop a class']}]},
                                {'id': 'p2', 'query': 'synthetic', 'evidence': [{'doc_id': 'doc901', 'all_of': ['x']}]},
                                {'no_query': True}], 'evaluate/mentee9/x.json')
        own = m1._peer_items(doc([answerable()]), 'evaluate/mentee1/cases.json')
        found = m1.overlaps(peers, own, {'doc001', 'doc002'})
        self.assertTrue(any('identical query' in f['kinds'] for f in found))
        self.assertTrue(any(f['own'] is None and 'doc901' in f['shared_docs'] for f in found))
        self.assertEqual(own[0]['chunks'], ['doc001_p1_c1'])
        items, sources = m1.load_peers(['refs/heads/does-not-exist-mentee1'])
        self.assertIsInstance(items, list)
        self.assertTrue(any('unavailable' in s for s in sources))

    def test_outputs_cannot_overwrite_inputs_or_corpus(self):
        for path in (m1.CASES_PATH, m1.QUESTIONS_PATH, m1.CONFIG_PATH, ROOT / 'backend/data/chunks/x.json',
                     ROOT / 'backend/app/retrieval.py'):
            with self.assertRaises(m1.HarnessError):
                m1._guard_output(path)
        m1._guard_output(ROOT / 'evaluate/runs/mentee-1/report.json')

    def test_runtime_retrieval_never_reads_benchmark_labels(self):
        for path in (ROOT / 'backend' / 'app').rglob('*.py'):
            source = path.read_text(encoding='utf-8')
            for needle in ('mentee1', 'questions.json', 'cases.json', 'evaluate/mentee'):
                self.assertNotIn(needle, source, f'{path} references {needle}')


class CommittedFixtureTests(unittest.TestCase):
    """The committed regression cases must verify against the real corpus."""

    def test_cases_verify_against_corpus(self):
        config, settings = m1.load_config()
        corpus = m1.load_corpus(config, settings)
        data = json.loads(m1.CASES_PATH.read_text(encoding='utf-8'))
        cases, errors = m1.validate_cases(data, corpus, require_coverage=True)
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(cases), 30)
        self.assertGreaterEqual(sum(c['unanswerable'] for c in cases), 8)
        self.assertTrue(any(c['category'] == 'follow_up' and c['unanswerable'] for c in cases))
        for case in cases:
            if case['category'] == 'follow_up':
                self.assertTrue(case['history'])


if __name__ == '__main__':
    unittest.main()
