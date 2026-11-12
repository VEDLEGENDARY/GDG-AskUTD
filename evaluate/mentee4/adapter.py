"""Isolated precision experiment; does not modify production retrieval."""

import math
from collections import Counter

from backend.app.retrieval_support.precision import rerank
from evaluate import evaluate_chunks as ev


def scored_candidates(index, query):
    """Return (index position, original score) pairs before admission filters."""
    s = index.s
    terms = set(ev.tokens(query))
    qv = index.vector(Counter(ev.tokens(query)))
    qnorm = math.sqrt(sum(v * v for v in qv.values())) or 1

    idfs = {
        t: math.log(1 + (index.n - index.df[t] + 0.5) /
                    (index.df[t] + 0.5))
        for t in terms
    }

    bm = [
        sum(
            idfs[t] * counts[t] * (s.bm25_k1 + 1) /
            (
                counts[t]
                + s.bm25_k1
                * (1 - s.bm25_b + s.bm25_b * length / index.avg)
            )
            for t in terms if counts[t]
        )
        for counts, length in zip(index.counts, index.lengths)
    ]
    scale = max(bm, default=0) or 1

    scores = []
    for i, vec in enumerate(index.vectors):
        cosine = sum(v * vec.get(t, 0) for t, v in qv.items())
        cosine /= qnorm * (index.norms[i] or 1)

        lexical = (
            s.lexical_weight * bm[i] / scale
            + (1 - s.lexical_weight) * cosine
        )
        metadata = len(terms & index.meta[i]) / max(1, len(terms))
        scores.append(
            (1 - s.metadata_weight) * lexical
            + s.metadata_weight * metadata
        )

    order = sorted(
        range(index.n),
        key=lambda i: (-scores[i], index.chunks[i]["chunk_id"]),
    )
    return [(i, scores[i]) for i in order]


def candidate_pool(index, query):
    """Reproduce production scoring and candidate admission."""
    return admit_candidates(index, scored_candidates(index, query))


def admit_candidates(index, scored):
    """Admit a configured prefix using unchanged original-score thresholds."""
    s = index.s

    return [
        {
            **index.chunks[i],
            "retrieval_score": score,
            "estimated_tokens": index.costs[i],
        }
        for i, score in scored[:s.candidate_pool]
        if score > 0 and score >= s.min_score
    ]


def search(index, query, top_k=5, use_precision=False, *,
           use_program=True, use_catalog=True):
    """Select passages with production constraints and optional reranking."""
    return select_candidates(index, query, candidate_pool(index, query), top_k,
                             use_precision, use_program=use_program,
                             use_catalog=use_catalog)


def select_candidates(index, query, candidates, top_k=5, use_precision=False, *,
                      use_program=True, use_catalog=True):
    """Select from an admitted pool without mutating that pool or its rows."""
    if type(top_k) is not int or not 1 <= top_k <= 8:
        raise ValueError("top_k must be an integer from 1 to 8")

    s = index.s
    pool = [dict(h) for h in candidates
            if h["retrieval_score"] > 0 and h["retrieval_score"] >= s.min_score]
    if use_precision:
        pool = rerank(query, pool, use_program=use_program,
                      use_catalog=use_catalog)

    score_key = "precision_score" if use_precision else "retrieval_score"
    positions = {
        chunk["chunk_id"]: i
        for i, chunk in enumerate(index.chunks)
    }

    selected = []
    document_counts = Counter()
    used = 0

    while pool and len(selected) < top_k:
        feasible = [
            hit for hit in pool
            if document_counts[hit["doc_id"]] < s.max_per_document
            and used + hit["estimated_tokens"] <= s.context_budget
        ]
        if not feasible:
            break

        def selection_key(hit):
            vector = index.vectors[positions[hit["chunk_id"]]]
            redundancy = max(
                (
                    ev.cosine(
                        vector,
                        index.vectors[positions[other["chunk_id"]]],
                    )
                    for other in selected
                ),
                default=0,
            )
            mmr = (
                s.diversity_lambda * hit[score_key]
                - (1 - s.diversity_lambda) * redundancy
            )
            return (-mmr, -hit[score_key], hit["chunk_id"])

        best = min(feasible, key=selection_key)
        selected.append(best)
        pool.remove(best)
        document_counts[best["doc_id"]] += 1
        used += best["estimated_tokens"]

    return selected
