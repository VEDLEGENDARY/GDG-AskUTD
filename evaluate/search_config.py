#!/usr/bin/env python3
"""Adaptive genetic search with elitism and random immigrants on dev; standard library only."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, fields
from functools import lru_cache
import hashlib
import heapq
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time
import uuid

from evaluate_chunks import (
    ROOT, REPO_ROOT, Settings, Retriever, cosine, cost, grade, load_settings,
    metadata, read_chunks, read_json, read_questions, summarize, supports, tokens,
)

SAMPLES_PER_GENERATION = 10


def mutation_rate(stagnant_generations):
    return min(.45, .12 + .03 * stagnant_generations)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def rank(sample):
    summary = sample['summary']
    return (-summary['leaderboard_score'], -summary['complete_evidence'],
            -summary['evidence_recall'], -summary['context_precision'],
            summary['estimated_tokens'], sample['id'])


def tournament(population, rng, exclude=None):
    candidates = [sample for sample in population if sample['id'] != exclude]
    if not candidates:
        candidates = population
    return min(rng.sample(candidates, min(3, len(candidates))), key=rank)


def random_config(space, rng):
    return {key: rng.choice(values) for key, values in space.items()}


def child_config(space, parents, rate, rng):
    first = tournament(parents, rng)
    chosen = [first, tournament(parents, rng, exclude=first['id'])]
    config = {key: rng.choice(chosen)['settings'][key] for key in space}
    mutated = []
    for key, values in space.items():
        alternatives = [value for value in values if value != config[key]]
        if alternatives and rng.random() < rate:
            # Most mutations move one step; occasional jumps restore exploration.
            index = values.index(config[key])
            neighbors = [values[i] for i in (index-1, index+1) if 0 <= i < len(values)]
            config[key] = rng.choice(neighbors if neighbors and rng.random() < .7 else alternatives)
            mutated.append(key)
    return config, [p['id'] for p in chosen], mutated


class PreparedCorpus(Retriever):
    """Reuse the reference index with cached query features and chunk similarities."""
    def __init__(self, chunks, settings):
        super().__init__(chunks, settings)
        self.lengths = [sum(counts.values()) for counts in self.counts]
        self.costs = [cost(chunk) for chunk in self.chunks]
        self.meta_terms = [set(tokens(metadata(chunk))) for chunk in self.chunks]
        self.postings = {}
        for index, counts in enumerate(self.counts):
            for term, frequency in counts.items():
                self.postings.setdefault(term, []).append((index, frequency))
        self.features = {}
        self.similarities = {}

    def retrieve_with(self, query, settings):
        if query not in self.features:
            terms = set(tokens(query))
            vector = self.vector(Counter(tokens(query)))
            self.features[query] = (
                sorted(terms), [cosine(vector, v) for v in self.vectors],
                [len(terms & meta) / max(1, len(terms)) for meta in self.meta_terms],
            )
        terms, cosines, overlaps = self.features[query]
        s = settings
        bm = [0.0] * self.n
        for term in terms:
            idf = math.log(1 + (self.n - self.df[term] + .5)/(self.df[term] + .5))
            for index, frequency in self.postings.get(term, []):
                bm[index] += idf * frequency / (
                    frequency/(s.bm25_k1+1) + (s.bm25_k1/(s.bm25_k1+1)) *
                    (1-s.bm25_b+s.bm25_b*self.lengths[index]/self.avg))
        scale = max(bm, default=0) or 1
        scores = [(1-s.metadata_weight)*(s.lexical_weight*bm[i]/scale +
                  (1-s.lexical_weight)*cosines[i]) + s.metadata_weight*overlaps[i]
                  for i in range(self.n)]
        pool = heapq.nsmallest(s.candidate_pool, range(self.n),
                              key=lambda i: (-scores[i], self.chunks[i]['chunk_id']))
        pool = [i for i in pool if scores[i] > 0 and scores[i] >= s.min_score]
        selected, counts, used = [], Counter(), 0

        def similarity(i, j):
            key = (i, j)
            if key not in self.similarities:
                self.similarities[key] = cosine(self.vectors[i], self.vectors[j])
            return self.similarities[key]

        while pool and len(selected) < s.top_k:
            feasible = [i for i in pool if counts[self.chunks[i]['doc_id']] < s.max_per_document
                        and used + self.costs[i] <= s.context_budget]
            if not feasible:
                break

            def selection_key(i):
                redundancy = max((similarity(i, j) for j in selected), default=0)
                mmr = s.diversity_lambda*scores[i] - (1-s.diversity_lambda)*redundancy
                return -mmr, -scores[i], self.chunks[i]['chunk_id']

            best = min(feasible, key=selection_key)
            selected.append(best)
            pool.remove(best)
            counts[self.chunks[best]['doc_id']] += 1
            used += self.costs[best]
        return [{**self.chunks[i], 'retrieval_score': scores[i], 'estimated_tokens': self.costs[i]}
                for i in selected]


class SearchEvaluator:
    def __init__(self, chunks, questions):
        self.chunks = chunks
        self.questions = questions
        self.masks = [{chunk['chunk_id']: sum(1 << i for i, group in enumerate(q['evidence'])
                                           if supports(chunk, group)) for chunk in chunks}
                      for q in questions]
        self.prepared = lru_cache(maxsize=6)(self._prepare)

    def _prepare(self, minimum, maximum):
        # Only the two length filters affect index construction.
        config = asdict(self.template)
        config.update(min_chunk_words=minimum, max_chunk_words=maximum)
        return PreparedCorpus(self.chunks, Settings(**config))

    def score(self, settings):
        self.template = settings
        prepared = self.prepared(settings.min_chunk_words, settings.max_chunk_words)
        rows = []
        for q, masks in zip(self.questions, self.masks):
            hits = prepared.retrieve_with(q['query'], settings)
            relevant = [bool(masks[c['chunk_id']]) for c in hits]
            covered = 0
            for hit in hits:
                covered |= masks[hit['chunk_id']]
            groups = len(q['evidence'])
            rows.append({'metrics': {
                'evidence_recall': covered.bit_count()/groups if groups else None,
                'complete_evidence': int(covered == (1 << groups)-1) if groups else None,
                'reciprocal_rank': next((1/(i+1) for i, ok in enumerate(relevant) if ok), 0) if groups else None,
                'context_precision': sum(relevant)/len(hits) if hits and groups else (0 if groups else None),
                'abstention_correct': int(not hits) if q['unanswerable'] else None,
                'estimated_tokens': sum(c['estimated_tokens'] for c in hits),
            }})
        return summarize(rows)

    def verify(self, settings):
        """Check cached selection and metrics against the unchanged reference evaluator."""
        reference = Retriever(self.chunks, settings)
        prepared = PreparedCorpus(self.chunks, settings)
        rows = []
        for q in self.questions:
            expected = reference.retrieve(q['query'])
            actual = prepared.retrieve_with(q['query'], settings)
            if [c['chunk_id'] for c in actual] != [c['chunk_id'] for c in expected]:
                raise ValueError(f"Cached retrieval differs from reference for {q['id']}")
            if any(not math.isclose(a['retrieval_score'], b['retrieval_score'], abs_tol=1e-12)
                   for a, b in zip(actual, expected)):
                raise ValueError('Cached relevance scores differ from reference')
            rows.append({'metrics': grade(q, expected)})
        expected = summarize(rows)
        actual = self.score(settings)
        for key in expected:
            if expected[key] != actual[key]:
                raise ValueError(f'Cached metric {key} differs from reference')
        return actual


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def load_space(path):
    space = read_json(path)
    if not isinstance(space, dict) or set(space) != {f.name for f in fields(Settings)}:
        raise ValueError('Search space must define an array for every Settings field')
    if any(not isinstance(values, list) or not values for values in space.values()):
        raise ValueError('Search-space arrays must be nonempty')
    # Validate each gene without assuming the user config is a usable baseline.
    base = {key: values[0] for key, values in space.items()}
    for key, values in space.items():
        for value in values:
            Settings(**{**base, key: value}).validate()
    if min(space['candidate_pool']) < max(space['top_k']):
        raise ValueError('Every candidate_pool choice must be >= every top_k choice')
    if min(space['max_chunk_words']) < max(space['min_chunk_words']):
        raise ValueError('Every maximum chunk length must be >= every minimum')
    return space


def run_search(args):
    space = load_space(args.space)
    chunks = read_chunks(args.chunks)
    questions = read_questions(args.questions, chunks, split='dev')
    if {q['unanswerable'] for q in questions} != {False, True}:
        raise ValueError('Dev search requires both answerable and unanswerable questions')
    if args.output_dir.exists():
        raise ValueError(f'Refusing to overwrite {args.output_dir}; select a new directory')
    args.output_dir.mkdir(parents=True)
    seed = args.seed if args.seed is not None else random.SystemRandom().getrandbits(64)
    rng = random.Random(seed)
    started = time.perf_counter()
    evaluator = SearchEvaluator(chunks, questions)
    baseline = load_settings(args.config)
    baseline_score = evaluator.verify(baseline)
    # Check a random point as well, using a separate RNG so search sampling is unaffected.
    evaluator.verify(Settings(**random_config(space, random.Random(seed ^ 0xA5A5))))
    archive = [dict(id='baseline', settings=asdict(baseline), summary=baseline_score)]
    seen = {fingerprint(asdict(baseline))}
    warm_count = 0
    if args.warm_start:
        source_manifest = read_json(args.warm_start / 'manifest.json')
        for key, expected in (('corpus_sha256', fingerprint(chunks)),
                              ('questions_sha256', fingerprint(questions)), ('space', space)):
            if source_manifest.get(key) != expected:
                raise ValueError(f'Warm-start {key} does not match this run')
        with (args.warm_start / 'samples.jsonl').open(encoding='utf-8') as source:
            warm_samples = [json.loads(line) for line in source if line.strip()]
        # A prior warm-start winner may exist only in its archive, not its new-sample log.
        warm_samples.extend(read_json(args.warm_start / 'top10.json'))
        for sample in warm_samples:
            Settings(**sample['settings']).validate()
            if any(value not in space[key] for key, value in sample['settings'].items()):
                raise ValueError('Warm-start sample is outside the selected search space')
            signature = fingerprint(sample['settings'])
            if signature not in seen:
                seen.add(signature)
                warm_count += 1
                sample['id'] = 'warm:' + sample['id']
                archive = sorted(archive + [sample], key=rank)[:10]
        verified = evaluator.verify(Settings(**archive[0]['settings']))
        if verified != archive[0]['summary']:
            raise ValueError('Warm-start winner differs from the reference evaluator')
    manifest = {
        'algorithm': 'adaptive-ga-v2', 'seed': seed, 'max_generations': args.generations,
        'early_stop_patience': args.patience, 'minimum_generations_before_early_stop': min(20, args.generations),
        'samples_per_generation': SAMPLES_PER_GENERATION, 'optimization_split': 'dev',
        'mutation_unit': 'per setting after uniform crossover',
        'mutation_rule': 'min(0.45, 0.12 + 0.03 * stagnant_generations)',
        'mutation_step': '70% adjacent search-space value, 30% random different value',
        'parent_selection': 'tournaments of 3 from last population plus top 2 overall elites',
        'random_immigrants': '2 per generation; 4 after 6 stagnant generations',
        'archive_size': 10, 'space': space,
        'warm_start': str(args.warm_start) if args.warm_start else None, 'warm_samples': warm_count,
        'corpus_sha256': fingerprint(chunks), 'questions_sha256': fingerprint(questions),
        'baseline_settings': asdict(baseline), 'baseline_summary': baseline_score,
    }
    write_json(args.output_dir / 'manifest.json', manifest)
    population = archive[:]
    history, stagnant, new_count, stop_reason = [], 0, 0, 'maximum_generations'
    print(f'Seed {seed}; baseline {baseline_score["leaderboard_score"]:.4f}; '
          f'warm samples {warm_count}; initial best {archive[0]["summary"]["leaderboard_score"]:.4f}', flush=True)
    with (args.output_dir / 'samples.jsonl').open('w', encoding='utf-8') as log:
        for generation in range(1, args.generations + 1):
            if (args.output_dir / 'STOP').exists():
                stop_reason = 'stop_file'
                break
            rate = mutation_rate(stagnant)
            immigrants = 4 if stagnant >= 6 else 2
            initial_random = not args.warm_start and generation == 1
            before = archive[0]['summary']['leaderboard_score']
            elites = [sample['id'] for sample in archive[:2]]
            pool_ids = [sample['id'] for sample in population]
            current = []
            for sample_number in range(1, SAMPLES_PER_GENERATION + 1):
                for attempt in range(10000):
                    if initial_random or sample_number > SAMPLES_PER_GENERATION - immigrants or attempt >= 200:
                        config, ancestry, mutations = random_config(space, rng), [], []
                        origin = 'random'
                    else:
                        config, ancestry, mutations = child_config(space, population, rate, rng)
                        origin = 'genetic'
                    signature = fingerprint(config)
                    if signature not in seen:
                        break
                else:
                    raise ValueError('Unable to create a new unique sample; expand the search space')
                seen.add(signature)
                config_settings = Settings(**config)
                config_settings.validate()
                summary = evaluator.score(config_settings)
                sample = {'id': f'g{generation:03d}-s{sample_number:02d}', 'generation': generation,
                          'settings': config, 'summary': summary, 'parents': ancestry, 'origin': origin,
                          'mutated_fields': mutations, 'mutation_rate': rate}
                current.append(sample)
                new_count += 1
                log.write(json.dumps(sample, ensure_ascii=False) + '\n')
                log.flush()
            archive = sorted(archive + current, key=rank)[:10]
            population = list({s['id']: s for s in archive[:2] + current}.values())
            improved = archive[0]['summary']['leaderboard_score'] > before + 1e-9
            stagnant = 0 if improved else stagnant + 1
            record = {'generation': generation, 'mutation_rate': rate,
                      'elite_ids': elites, 'parent_pool': pool_ids, 'random_immigrants': immigrants,
                      'stagnant_generations': stagnant,
                      'sample_ids': [s['id'] for s in current],
                      'generation_best': sorted(current, key=rank)[0]['summary']['leaderboard_score'],
                      'overall_best': archive[0]['summary']['leaderboard_score']}
            history.append(record)
            write_json(args.output_dir / 'generations.json', history)
            write_json(args.output_dir / 'top10.json', archive)
            write_json(args.output_dir / 'best-config.json', archive[0]['settings'])
            write_json(args.output_dir / 'progress.json', {'completed_generations': generation,
                       'new_samples': new_count, 'warm_samples': warm_count,
                       'unique_configs_considered': len(seen), 'elapsed_seconds': time.perf_counter()-started})
            print(f'Generation {generation:02d}/{args.generations}: '
                  f'best={record["generation_best"]:.4f} overall={record["overall_best"]:.4f} '
                  f'mutation={rate:.2f} stagnant={stagnant}', flush=True)
            if generation >= min(20, args.generations) and stagnant >= args.patience:
                stop_reason = 'stagnation'
                break
    # Also save a valid winner if STOP was requested before the first generation.
    write_json(args.output_dir / 'best-config.json', archive[0]['settings'])
    best = Settings(**archive[0]['settings'])
    evaluator.verify(best)
    # Reference reports: test is read only after dev search and selection are finished.
    for split in ('dev', 'test'):
        command = [sys.executable, str(ROOT / 'evaluate_chunks.py'), '--config',
                   str((args.output_dir / 'best-config.json').resolve()), '--chunks', str(args.chunks.resolve()),
                   '--questions', str(args.questions.resolve()), '--split', split,
                   '--output', str((args.output_dir / f'best-{split}.json').resolve())]
        result = subprocess.run(command, text=True, encoding='utf-8', capture_output=True)
        if result.returncode:
            raise ValueError(f'Final reference {split} evaluation failed: {result.stderr}')
    write_json(args.output_dir / 'complete.json', {'best_sample': archive[0]['id'],
               'dev_score': archive[0]['summary']['leaderboard_score'],
               'test_score': read_json(args.output_dir / 'best-test.json')['summary']['leaderboard_score'],
               'elapsed_seconds': time.perf_counter()-started, 'new_samples': new_count,
               'warm_samples': warm_count, 'unique_configs_considered': len(seen),
               'completed_generations': len(history), 'stop_reason': stop_reason})
    print(f'Completed. Best config and reference dev/test reports: {args.output_dir}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generations', type=int, default=60)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--patience', type=int, default=12)
    parser.add_argument('--warm-start', type=Path, help='Reuse compatible dev samples from an earlier search directory')
    parser.add_argument('--space', type=Path, default=ROOT / 'search_space.json')
    parser.add_argument('--config', type=Path, default=ROOT / 'config.example.json')
    parser.add_argument('--chunks', type=Path, default=REPO_ROOT / 'backend/data/chunks')
    parser.add_argument('--questions', type=Path, default=ROOT / 'questions.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'runs' / f'ga-search-{uuid.uuid4().hex[:8]}')
    args = parser.parse_args()
    if args.generations < 1 or args.patience < 1:
        parser.error('--generations and --patience must be positive')
    try:
        run_search(args)
        return 0
    except (ValueError, TypeError, OSError) as exc:
        print(f'search_config: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
