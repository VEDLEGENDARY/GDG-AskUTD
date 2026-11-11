"""Cached lexical features and budgeted passage selection.

Scores are identical to the original full-corpus scan, but only chunks that share a
query term with their body or metadata are visited. A chunk with no shared term has
BM25 = 0, cosine = 0 and metadata overlap = 0, so its score is exactly 0 and it can never
pass the positive score threshold; skipping it cannot change the result.
"""
from __future__ import annotations

import copy
import heapq
import math
from collections import Counter

from evaluate import evaluate_chunks as ev

from . import postings as postings_module

_IMMUTABLE = (str, int, float, bool, type(None))


class LexicalIndex(ev.Retriever):
    """Reuse baseline scoring with precomputed postings, lengths, norms and metadata."""

    def __init__(self, chunks: list[dict], settings: ev.Settings):
        super().__init__(chunks, settings)
        self.lengths = [sum(c.values()) for c in self.counts]
        self.sumsq = [sum(v*v for v in vec.values()) for vec in self.vectors]
        self.norms = [math.sqrt(x) for x in self.sumsq]
        self.meta = [set(ev.tokens(ev.metadata(row))) for row in self.chunks]
        self.costs = [ev.cost(row) for row in self.chunks]
        # Snapshot identifiers so later mutation of caller-owned chunk dicts cannot change ranking.
        self.chunk_ids = tuple(row['chunk_id'] for row in self.chunks)
        self.doc_ids = tuple(row['doc_id'] for row in self.chunks)
        self.postings = self._build_postings()

    def _build_postings(self) -> postings_module.Postings:
        return postings_module.build(self.counts, self.vectors, self.meta, self.lengths,
                                     self.df, self.n, self.avg, self.s.bm25_k1, self.s.bm25_b)

    def _cosine(self, i: int, j: int) -> float:
        """ev.cosine(vectors[i], vectors[j]) with the same summation order and cached sums of squares."""
        a, b = self.vectors[i], self.vectors[j]
        denom = math.sqrt(self.sumsq[i] * self.sumsq[j])
        return sum(v*b[k] for k, v in a.items() if k in b) / denom if denom else 0.0

    def search(self, query: str, top_k: int) -> list[dict]:
        """Score candidates, then enforce MMR, document cap and token budget."""
        s = self.s
        post = self.postings
        if (post.k1, post.b) != (s.bm25_k1, s.bm25_b):
            # Settings object was mutated after construction; rebuild instead of serving stale weights.
            post = self.postings = self._build_postings()
        terms = set(ev.tokens(query))
        if not terms:
            return []
        qv = self.vector(Counter(ev.tokens(query)))
        qnorm = math.sqrt(sum(v*v for v in qv.values())) or 1

        # Request-local accumulators. Iterating `terms` (BM25) and `qv` (cosine) in the same
        # order as the full scan collects the same nonzero values in the same sequence. They
        # are then added with builtin sum(), like the full scan (Python 3.12+ sum() uses
        # compensated float summation, so a running `+=` would differ in the last bit). The
        # full scan's extra zero terms leave sum() unchanged, so results are bit-identical.
        bm_parts: dict[int, list[float]] = {}
        for t in terms:
            hit = post.body(t)
            if hit is not None:
                for i, w in zip(hit[0], hit[1]):
                    parts = bm_parts.get(i)
                    if parts is None:
                        bm_parts[i] = [w]
                    else:
                        parts.append(w)
        dot_parts: dict[int, list[float]] = {}
        for t, v in qv.items():
            hit = post.body(t)
            if hit is not None:
                for i, x in zip(hit[0], hit[2]):
                    w = v*x
                    parts = dot_parts.get(i)
                    if parts is None:
                        dot_parts[i] = [w]
                    else:
                        parts.append(w)
        bm = {i: sum(parts) for i, parts in bm_parts.items()}
        dot = {i: sum(parts) for i, parts in dot_parts.items()}
        meta_hits: Counter = Counter()
        for t in terms:
            docs = post.metadata(t)
            if docs is not None:
                meta_hits.update(docs)

        # BM25 normalization uses the max over the whole corpus; unvisited chunks have BM25 0.
        scale = max(bm.values(), default=0) or 1
        lw, mw, nterms = s.lexical_weight, s.metadata_weight, max(1, len(terms))
        norms = self.norms
        threshold_ok = []
        scores: dict[int, float] = {}
        for i in bm.keys() | meta_hits.keys():
            cosine = dot.get(i, 0) / (qnorm*(norms[i] or 1))
            lexical = lw*bm.get(i, 0)/scale + (1-lw)*cosine
            meta = meta_hits[i]/nterms
            score = (1-mw)*lexical+mw*meta
            if score > 0 and score >= s.min_score:
                scores[i] = score
                threshold_ok.append(i)
        # Equivalent to sorted(all, key)[:pool] followed by the threshold filter, because the
        # threshold keeps a prefix of that order. The index breaks exact ties like a stable sort.
        ids = self.chunk_ids
        pool = heapq.nsmallest(s.candidate_pool, threshold_ok, key=lambda i: (-scores[i], ids[i], i))

        selected: list[int] = []
        doc_counts: Counter = Counter()
        redundancy = {i: 0 for i in pool}
        used = 0
        lam = s.diversity_lambda
        while pool and len(selected) < top_k:
            feasible = [i for i in pool if doc_counts[self.doc_ids[i]] < s.max_per_document
                        and used+self.costs[i] <= s.context_budget]
            if not feasible:
                break
            best = min(feasible, key=lambda i: (-(lam*scores[i]-(1-lam)*redundancy[i]), -scores[i], ids[i]))
            selected.append(best)
            pool.remove(best)
            doc_counts[self.doc_ids[best]] += 1
            used += self.costs[best]
            # Max redundancy against the selected set, updated incrementally (max is order-free).
            for i in pool:
                sim = self._cosine(i, best)
                if sim > redundancy[i]:
                    redundancy[i] = sim
        return [self._row(i, scores[i]) for i in selected]

    def _row(self, i: int, score: float) -> dict:
        """Fresh result dict; nested mutable values are copied so callers cannot alter the index."""
        row = {k: v if isinstance(v, _IMMUTABLE) else copy.deepcopy(v) for k, v in self.chunks[i].items()}
        row['retrieval_score'] = score
        row['estimated_tokens'] = self.costs[i]
        return row
