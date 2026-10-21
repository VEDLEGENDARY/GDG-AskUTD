#!/usr/bin/env python3
"""Offline retrieval lab for AskUTD chunk JSON. Python 3.10+, no dependencies."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent


@dataclass
class Settings:
    # MENTEES: change these, or pass a JSON file containing overrides via --config.
    top_k: int = 4
    candidate_pool: int = 30
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    lexical_weight: float = 0.7  # BM25 vs TF-IDF cosine; neither uses neural embeddings.
    metadata_weight: float = 0.2
    diversity_lambda: float = 0.8  # 1 = relevance only; 0 = favor diversity.
    min_score: float = 0.12  # Abstain if no candidate passes this normalized score.
    max_per_document: int = 3
    min_chunk_words: int = 5
    max_chunk_words: int = 1200
    context_budget: int = 900  # Estimated tokens, ceil(characters / 4), including metadata.

    def validate(self):
        integer_fields = ('top_k', 'candidate_pool', 'max_per_document',
                          'min_chunk_words', 'max_chunk_words', 'context_budget')
        for key in integer_fields:
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f'{key} must be a positive integer')
        if self.candidate_pool < self.top_k or self.max_chunk_words < self.min_chunk_words:
            raise ValueError('candidate_pool >= top_k and max_chunk_words >= min_chunk_words required')
        for key in ('bm25_b', 'lexical_weight', 'metadata_weight', 'diversity_lambda', 'min_score'):
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f'{key} must be between 0 and 1')
        if type(self.bm25_k1) not in (int, float) or not math.isfinite(self.bm25_k1) or self.bm25_k1 <= 0:
            raise ValueError('bm25_k1 must be positive and finite')


def normalize(text):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


STOP = set('a an the is are was were be to of in on for and or with by at i my do does how what which can'.split())


def tokens(text):
    return [t for t in normalize(text).split() if t not in STOP]


def read_chunks(directory):
    paths = sorted(directory.rglob('*.json'))
    if not paths:
        raise ValueError(f'No chunk JSON found in {directory}. See evaluate/README.md for the export command.')
    chunks, seen = [], set()
    for path in paths:
        rows = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(rows, list):
            raise ValueError(f'{path}: expected a JSON array of chunks')
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip()
                                              for k in ('chunk_id', 'doc_id', 'text')):
                raise ValueError(f'{path}: every chunk needs nonempty chunk_id, doc_id, text strings')
            if row['chunk_id'] in seen:
                raise ValueError(f"Duplicate chunk ID {row['chunk_id']}; do not mix branch directories")
            if any(not isinstance(row.get(k, ''), str) for k in ('source_title', 'section_heading')):
                raise ValueError(f'{path}: metadata must be text')
            seen.add(row['chunk_id'])
            chunks.append(row)
    return chunks


def metadata(row):
    return row.get('source_title', '') + ' ' + row.get('section_heading', '')


def context_text(row):
    return metadata(row).strip() + '\n' + row['text']


def cost(row):
    return math.ceil(len(context_text(row)) / 4)


def cosine(a, b):
    denom = math.sqrt(sum(v*v for v in a.values()) * sum(v*v for v in b.values()))
    return sum(v*b.get(k, 0) for k, v in a.items()) / denom if denom else 0.0


class Retriever:
    def __init__(self, chunks, settings):
        self.s = settings
        self.chunks = [c for c in chunks if settings.min_chunk_words <= len(c['text'].split()) <= settings.max_chunk_words]
        if not self.chunks:
            raise ValueError('Chunk length filters removed the entire corpus')
        self.counts = [Counter(tokens(c['text'])) for c in self.chunks]
        self.df = Counter(t for counts in self.counts for t in counts)
        self.n = len(self.chunks)
        self.avg = sum(sum(c.values()) for c in self.counts) / self.n or 1
        self.vectors = [self.vector(c) for c in self.counts]

    def vector(self, counts):
        return {t: (1 + math.log(n)) * (1 + math.log((self.n + 1)/(self.df[t] + 1)))
                for t, n in counts.items()}

    def retrieve(self, query):
        s, terms = self.s, set(tokens(query))
        qv = self.vector(Counter(tokens(query)))
        bm = []
        for counts in self.counts:
            length = sum(counts.values())
            bm.append(sum(math.log(1 + (self.n - self.df[t] + .5)/(self.df[t] + .5)) *
                          counts[t]*(s.bm25_k1+1)/(counts[t]+s.bm25_k1*(1-s.bm25_b+s.bm25_b*length/self.avg))
                          for t in terms if counts[t]))
        scale = max(bm, default=0) or 1
        scores = []
        for i, row in enumerate(self.chunks):
            lexical = s.lexical_weight*bm[i]/scale + (1-s.lexical_weight)*cosine(qv, self.vectors[i])
            meta = len(terms & set(tokens(metadata(row)))) / max(1, len(terms))
            scores.append((1-s.metadata_weight)*lexical + s.metadata_weight*meta)
        pool = sorted(range(self.n), key=lambda i: (-scores[i], self.chunks[i]['chunk_id']))[:s.candidate_pool]
        pool = [i for i in pool if scores[i] > 0 and scores[i] >= s.min_score]
        selected, doc_counts, used = [], Counter(), 0
        while pool and len(selected) < s.top_k:
            feasible = [i for i in pool if doc_counts[self.chunks[i]['doc_id']] < s.max_per_document
                        and used + cost(self.chunks[i]) <= s.context_budget]
            if not feasible:
                break
            def mmr(i):
                redundancy = max((cosine(self.vectors[i], self.vectors[j]) for j in selected), default=0)
                return s.diversity_lambda*scores[i] - (1-s.diversity_lambda)*redundancy
            best = max(feasible, key=lambda i: (mmr(i), scores[i], -i))
            selected.append(best)
            pool.remove(best)
            doc_counts[self.chunks[best]['doc_id']] += 1
            used += cost(self.chunks[best])
        return [{**self.chunks[i], 'retrieval_score': scores[i], 'estimated_tokens': cost(self.chunks[i])}
                for i in selected]


def supports(chunk, evidence):
    documents = evidence.get('doc_ids', [evidence.get('doc_id')])
    text = normalize(chunk['text'])
    return (chunk['doc_id'] in documents
            and all(normalize(phrase) in text for phrase in evidence.get('all_of', []))
            and (not evidence.get('any_of') or any(
                normalize(phrase) in text for phrase in evidence['any_of'])))


def read_questions(path, chunks):
    questions = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(questions, list) or not questions:
        raise ValueError('Questions must be a nonempty array')
    seen, seen_queries = set(), set()
    for q in questions:
        if not isinstance(q, dict) or any(not isinstance(q.get(k), str) or not q[k].strip()
                                          for k in ('id', 'query', 'split', 'category')):
            raise ValueError('Question needs id, query, split, category strings')
        if q['id'] in seen or q['split'] not in ('dev', 'test'):
            raise ValueError('Question IDs must be unique; split must be dev or test')
        seen.add(q['id'])
        query = normalize(q['query'])
        if not tokens(q['query']) or query in seen_queries:
            raise ValueError(f"{q['id']}: empty or duplicate normalized query (including across splits)")
        seen_queries.add(query)
        if type(q.get('unanswerable')) is not bool or not isinstance(q.get('evidence'), list):
            raise ValueError('Question needs boolean unanswerable and evidence array')
        if q['unanswerable'] == bool(q['evidence']):
            raise ValueError(f"{q['id']}: answerable questions require evidence; unanswerable require none")
        groups = set()
        for e in q['evidence']:
            if not isinstance(e, dict):
                raise ValueError(f"{q['id']}: invalid evidence group")
            documents = e.get('doc_ids', [e.get('doc_id')])
            if (('doc_id' in e) == ('doc_ids' in e) or not isinstance(documents, list)
                    or not documents or any(not isinstance(d, str) or not d.strip() for d in documents)
                    or len(set(documents)) != len(documents)):
                raise ValueError(f"{q['id']}: evidence requires doc_id or a unique nonempty doc_ids list")
            if not e.get('any_of') and not e.get('all_of'):
                raise ValueError(f"{q['id']}: evidence requires any_of or all_of phrases")
            for key in ('any_of', 'all_of'):
                if key in e and (not isinstance(e[key], list) or not e[key]
                                 or any(not isinstance(p, str) or not normalize(p) for p in e[key])):
                    raise ValueError(f"{q['id']}: invalid {key} phrases")
            signature = (tuple(sorted(documents)),
                         tuple(sorted(set(map(normalize, e.get('any_of', []))))),
                         tuple(sorted(set(map(normalize, e.get('all_of', []))))))
            if signature in groups:
                raise ValueError(f"{q['id']}: duplicate evidence group")
            groups.add(signature)
            if not any(supports(c, e) for c in chunks):
                raise ValueError(f"{q['id']}: evidence missing in corpus: {e}. Review labels before scoring this corpus.")
    return questions


def evidence_feasible(question, chunks, settings):
    """Can an oracle cover all groups within the configured context constraints?"""
    evidence = question['evidence']
    if not evidence:
        return True
    goal = (1 << len(evidence)) - 1
    candidates = []
    for chunk in chunks:
        mask = sum(1 << i for i, group in enumerate(evidence) if supports(chunk, group))
        if mask and cost(chunk) <= settings.context_budget:
            candidates.append((mask, chunk['doc_id'], cost(chunk)))
    # Equivalent chunks need only their cheapest representative for oracle coverage.
    cheapest = {}
    for mask, document, size in candidates:
        key = (mask, document)
        cheapest[key] = min(size, cheapest.get(key, size))
    candidates = [(mask, doc, size) for (mask, doc), size in cheapest.items()]

    def search(covered, remaining, budget, counts):
        if covered == goal:
            return True
        if not remaining:
            return False
        missing = next(1 << i for i in range(len(evidence)) if not covered & (1 << i))
        for mask, document, size in candidates:
            if mask & missing and size <= budget and counts[document] < settings.max_per_document:
                counts[document] += 1
                found = search(covered | mask, remaining - 1, budget - size, counts)
                counts[document] -= 1
                if found:
                    return True
        return False

    return search(0, settings.top_k, settings.context_budget, Counter())


def benchmark_audit(questions, chunks, settings):
    return {
        'questions': len(questions),
        'answerable': sum(not q['unanswerable'] for q in questions),
        'unanswerable': sum(q['unanswerable'] for q in questions),
        'multi_evidence': sum(len(q['evidence']) > 1 for q in questions),
        'evidence_documents': len({d for q in questions for e in q['evidence']
                                   for d in e.get('doc_ids', [e.get('doc_id')])}),
        'infeasible_question_ids': [q['id'] for q in questions
                                    if not evidence_feasible(q, chunks, settings)],
    }


def grade(q, hits):
    evidence = q['evidence']
    covered = [any(supports(c, e) for c in hits) for e in evidence]
    relevant = [any(supports(c, e) for e in evidence) for c in hits]
    return {
        'evidence_recall': sum(covered)/len(evidence) if evidence else None,
        'complete_evidence': int(all(covered)) if evidence else None,
        'reciprocal_rank': next((1/(i+1) for i, ok in enumerate(relevant) if ok), 0) if evidence else None,
        'context_precision': sum(relevant)/len(hits) if hits and evidence else (0 if evidence else None),
        'abstention_correct': int(not hits) if q['unanswerable'] else None,
        'estimated_tokens': sum(c['estimated_tokens'] for c in hits),
    }


def summarize(rows):
    keys = ('evidence_recall', 'complete_evidence', 'reciprocal_rank', 'context_precision',
            'abstention_correct', 'estimated_tokens')
    result = {k: sum(vals)/len(vals) if (vals := [r['metrics'][k] for r in rows if r['metrics'][k] is not None]) else None
              for k in keys}
    weights = dict(complete_evidence=.50, evidence_recall=.20, context_precision=.15, abstention_correct=.15)
    result['leaderboard_score'] = (100 * sum(result[k]*w for k, w in weights.items())
                                   if all(result[k] is not None for k in weights) else None)
    return result


def export_branch(ref, output):
    # Read git objects without switching branches or overwriting existing files.
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', ref, '--', 'backend/data/chunks'], text=True, cwd=REPO_ROOT).splitlines()
    paths = [p for p in paths if p.endswith('.json')]
    if not paths:
        raise ValueError(f'No chunk JSON on {ref}')
    if output.exists():
        raise ValueError(f'Refusing to overwrite {output}; choose a new export directory')
    output.mkdir(parents=True)
    for path in paths:
        target = output / Path(path).relative_to('backend/data/chunks')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(['git', 'show', f'{ref}:{path}'], cwd=REPO_ROOT))
    print(f'Exported {len(paths)} JSON files from {ref} to {output}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--chunks', type=Path, default=ROOT.parent/'backend/data/chunks')
    p.add_argument('--questions', type=Path, default=ROOT/'questions.json')
    p.add_argument('--match-documents', type=Path, help='Restrict corpus to document IDs also present in this chunk directory')
    p.add_argument('--config', type=Path)
    p.add_argument('--split', choices=('dev', 'test'), default='dev')
    p.add_argument('--output', type=Path, default=ROOT/'runs/latest.json')
    p.add_argument('--export-branch', help='Export backend/data/chunks from this local git ref and exit')
    p.add_argument('--query', help='Inspect a single query without benchmark scoring')
    p.add_argument('--validate-only', action='store_true', help='Validate labels and oracle context feasibility, then exit')
    args = p.parse_args()
    try:
        if args.export_branch:
            export_branch(args.export_branch, args.chunks)
            return 0
        config = json.loads(args.config.read_text(encoding='utf-8-sig')) if args.config else {}
        s = Settings(**config)
        s.validate()
        chunks = read_chunks(args.chunks)
        if args.match_documents:
            shared = {c['doc_id'] for c in read_chunks(args.match_documents)}
            chunks = [c for c in chunks if c['doc_id'] in shared]
            if not chunks:
                raise ValueError('No document IDs shared by these corpora')
        started = time.perf_counter()
        retriever = Retriever(chunks, s)
        if args.query:
            print(json.dumps(retriever.retrieve(args.query), indent=2, ensure_ascii=False))
            return 0
        questions = [q for q in read_questions(args.questions, chunks) if q['split'] == args.split]
        if not questions:
            raise ValueError('No questions in selected split')
        validation = benchmark_audit(questions, retriever.chunks, s)
        if args.validate_only:
            print(json.dumps({'settings': asdict(s), 'benchmark': validation}, indent=2))
            return int(bool(validation['infeasible_question_ids']))
        rows = []
        for q in questions:
            hits = retriever.retrieve(q['query'])
            rows.append({'question': q, 'metrics': grade(q, hits),
                         'evidence_covered': [any(supports(c, e) for c in hits) for e in q['evidence']],
                         'retrieved': hits})
        fingerprint = lambda obj: hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        texts = Counter(normalize(c['text']) for c in chunks)
        report = {'settings': asdict(s), 'split': args.split, 'benchmark': validation,
                  'corpus_sha256': fingerprint(chunks), 'questions_sha256': fingerprint(questions),
                  'audit': {'total_chunks': len(chunks), 'eligible_chunks': len(retriever.chunks),
                            'documents': len(set(c['doc_id'] for c in chunks)),
                            'duplicate_text_copies': sum(n-1 for n in texts.values()),
                            'missing_metadata': sum(not c.get('source_title') or not c.get('section_heading') for c in chunks)},
                  'summary': summarize(rows),
                  'by_category': {cat: summarize([r for r in rows if r['question']['category'] == cat])
                                  for cat in sorted(set(q['category'] for q in questions))},
                  'elapsed_seconds': time.perf_counter()-started, 'results': rows}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
        print(json.dumps({'settings': report['settings'], 'benchmark': validation,
                          'audit': report['audit'], 'summary': report['summary']}, indent=2))
        print(f'Per-question evidence and retrieved text: {args.output}')
        return 0
    except (ValueError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'evaluate_chunks: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
