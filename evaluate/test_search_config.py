"""Genetic schedule, ancestry, and accelerated/reference parity checks."""
from dataclasses import asdict, replace
import random
import unittest

from evaluate_chunks import load_settings
from search_config import SearchEvaluator, child_config, load_space, mutation_rate, tournament, ROOT


def sample(name, score, config=None):
    return dict(id=name, settings=config or {}, summary=dict(leaderboard_score=score,
                complete_evidence=1, evidence_recall=1, context_precision=1, estimated_tokens=1))


class SearchTests(unittest.TestCase):
    def test_mutation_increases_with_stagnation_and_is_capped(self):
        for stagnant, expected in ((0, .12), (1, .15), (6, .30), (11, .45), (50, .45)):
            self.assertAlmostEqual(mutation_rate(stagnant), expected)

    def test_tournament_selects_best_contestant_and_excludes_first_parent(self):
        population = [sample('low', 1), sample('middle', 2), sample('high', 3)]
        self.assertEqual(tournament(population, random.Random(12))['id'], 'high')
        self.assertEqual(tournament(population, random.Random(12), exclude='high')['id'], 'middle')

    def test_mutation_changes_values_and_is_seeded(self):
        space = dict(a=[1, 2], b=[3, 4])
        parent = sample('parent', 1, dict(a=1, b=3))
        first = child_config(space, [parent], 1, random.Random(123))
        self.assertEqual(first, child_config(space, [parent], 1, random.Random(123)))
        self.assertEqual(first[0], dict(a=2, b=4))
        self.assertEqual(first[2], ['a', 'b'])

    def test_zero_mutation_keeps_parent_values(self):
        parent = sample('parent', 1, dict(a=1, b=3))
        child, _, mutations = child_config(dict(a=[1, 2], b=[3, 4]), [parent], 0, random.Random(12))
        self.assertEqual(child, parent['settings'])
        self.assertEqual(mutations, [])

    def test_acceleration_preserves_reference_selection_and_metrics(self):
        chunks = [dict(chunk_id='c1', doc_id='d1', text='graduation deadline is tomorrow morning',
                       source_title='graduation', section_heading='deadline'),
                  dict(chunk_id='c2', doc_id='d1', text='graduation applications need approval before tomorrow'),
                  dict(chunk_id='c3', doc_id='d2', text='financial aid application funding information')]
        questions = [dict(id='a', query='graduation deadline', unanswerable=False,
                          evidence=[dict(doc_id='d1', all_of=['tomorrow morning'])]),
                     dict(id='b', query='my scholarship funding', unanswerable=True, evidence=[])]
        evaluator = SearchEvaluator(chunks, questions)
        base = replace(load_settings(), min_chunk_words=1, max_chunk_words=1200,
                       min_score=0, top_k=3, candidate_pool=10, context_budget=900)
        for config in (base, replace(base, bm25_b=1, lexical_weight=0, diversity_lambda=.3),
                       replace(base, max_per_document=1, top_k=1, metadata_weight=1),
                       replace(base, min_score=1, min_chunk_words=6)):
            evaluator.verify(config)

    def test_search_space_defines_all_json_settings(self):
        self.assertEqual(set(load_space(ROOT / 'search_space.json')), set(asdict(load_settings())))


if __name__ == '__main__':
    unittest.main()
