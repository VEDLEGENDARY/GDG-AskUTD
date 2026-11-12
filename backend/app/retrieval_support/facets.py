"""Independent retrieval for compound requests with shared context."""
from __future__ import annotations

from collections import Counter
from itertools import zip_longest


def merge_facets(primary: list[dict], facets: list[list[dict]], *, top_k: int,
                 budget: int, document_cap: int) -> list[dict]:
    """Reserve space for the strongest passage from each question before filling."""
    selected: list[dict] = []
    seen = set()
    documents: Counter[str] = Counter()
    used = 0
    interleaved = [hit for group in zip_longest(*facets) for hit in group if hit is not None]
    for hit in [*primary[:1], *interleaved, *primary]:
        chunk = hit["chunk_id"]
        doc = hit["doc_id"]
        cost = hit["estimated_tokens"]
        if chunk in seen or documents[doc] >= document_cap or used + cost > budget:
            continue
        selected.append(hit)
        seen.add(chunk)
        documents[doc] += 1
        used += cost
        if len(selected) == top_k:
            break
    return selected
