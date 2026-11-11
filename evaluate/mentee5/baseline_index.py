"""Frozen copy of the production LexicalIndex, used only for parity tests and benchmarks.

Source: backend/app/retrieval_support/index.py at mentor commit
f763b1c75302879d25035445b12b5757746b3970. The scoring body is copied verbatim; only the
class name changed. Production code must never import this module.
"""
from __future__ import annotations

import math
from collections import Counter

from evaluate import evaluate_chunks as ev

BASELINE_COMMIT = 'f763b1c75302879d25035445b12b5757746b3970'


class BaselineLexicalIndex(ev.Retriever):
    """Reuse baseline scoring with precomputed lengths, norms and metadata."""

    def __init__(self, chunks: list[dict], settings: ev.Settings):
        super().__init__(chunks, settings)
        self.lengths = [sum(c.values()) for c in self.counts]
        self.norms = [math.sqrt(sum(v*v for v in vec.values())) for vec in self.vectors]
        self.meta = [set(ev.tokens(ev.metadata(row))) for row in self.chunks]
        self.costs = [ev.cost(row) for row in self.chunks]

    def search(self, query: str, top_k: int) -> list[dict]:
        """Score candidates, then enforce MMR, document cap and token budget."""
        s = self.s
        terms = set(ev.tokens(query))
        qv = self.vector(Counter(ev.tokens(query)))
        qnorm = math.sqrt(sum(v*v for v in qv.values())) or 1
        idfs = {t: math.log(1 + (self.n-self.df[t]+.5)/(self.df[t]+.5)) for t in terms}
        bm = [sum(idfs[t]*counts[t]*(s.bm25_k1+1) /
                  (counts[t]+s.bm25_k1*(1-s.bm25_b+s.bm25_b*length/self.avg))
                  for t in terms if counts[t])
              for counts, length in zip(self.counts, self.lengths)]
        scale = max(bm, default=0) or 1
        scores = []
        for i, vec in enumerate(self.vectors):
            cosine = sum(v*vec.get(t, 0) for t, v in qv.items()) / (qnorm*(self.norms[i] or 1))
            lexical = s.lexical_weight*bm[i]/scale + (1-s.lexical_weight)*cosine
            meta = len(terms & self.meta[i])/max(1, len(terms))
            scores.append((1-s.metadata_weight)*lexical+s.metadata_weight*meta)
        pool = sorted(range(self.n), key=lambda i: (-scores[i], self.chunks[i]['chunk_id']))[:s.candidate_pool]
        pool = [i for i in pool if scores[i] > 0 and scores[i] >= s.min_score]
        selected: list[int] = []
        counts: Counter = Counter()
        used = 0
        while pool and len(selected) < top_k:
            feasible = [i for i in pool if counts[self.chunks[i]['doc_id']] < s.max_per_document
                        and used+self.costs[i] <= s.context_budget]
            if not feasible:
                break
            def mmr(i: int) -> float:
                redundancy = max((ev.cosine(self.vectors[i], self.vectors[j]) for j in selected), default=0)
                return s.diversity_lambda*scores[i]-(1-s.diversity_lambda)*redundancy
            best = min(feasible, key=lambda i: (-mmr(i), -scores[i], self.chunks[i]['chunk_id']))
            selected.append(best)
            pool.remove(best)
            counts[self.chunks[best]['doc_id']] += 1
            used += self.costs[best]
        return [{**self.chunks[i], 'retrieval_score': scores[i], 'estimated_tokens': self.costs[i]}
                for i in selected]
