"""Immutable inverted postings used by LexicalIndex to skip chunks that cannot score.

Layout is flat (CSR style): one compact array per field plus per-term offsets, which keeps
memory overhead to roughly 12 bytes per (term, chunk) pair instead of one Python object per
term. Each BM25 weight is computed with the exact same floating-point expression the
full-scan scorer used, so summing them in the same term order reproduces identical scores.
"""
from __future__ import annotations

import math
from array import array
from dataclasses import dataclass


@dataclass(frozen=True)
class Postings:
    """Read-only after construction, so one instance can be shared by concurrent searches."""

    slot: dict[str, int]    # body term -> slot
    offsets: array          # slot -> start in docs/bm25; offsets[slot+1] is the end ('q')
    docs: array             # chunk positions ('i')
    bm25: array             # idf*tf*(k1+1)/(tf+k1*(1-b+b*len/avg)) for that posting ('d')
    tfidf: array            # the chunk's TF-IDF vector weight for the term ('d')
    meta_slot: dict[str, int]
    meta_offsets: array     # same layout for title/heading terms ('q')
    meta_docs: array        # ('i')
    k1: float
    b: float

    def body(self, term: str):
        """(chunk positions, BM25 weights, TF-IDF weights) for a body term, or None if unknown."""
        s = self.slot.get(term)
        if s is None:
            return None
        start, end = self.offsets[s], self.offsets[s+1]
        return (memoryview(self.docs)[start:end], memoryview(self.bm25)[start:end],
                memoryview(self.tfidf)[start:end])

    def metadata(self, term: str):
        """Chunk positions whose title or heading contains the term, or None."""
        s = self.meta_slot.get(term)
        if s is None:
            return None
        return memoryview(self.meta_docs)[self.meta_offsets[s]:self.meta_offsets[s+1]]


def _layout(sizes: dict[str, int]) -> tuple[dict[str, int], array]:
    slot, offsets, total = {}, array('q', [0]), 0
    for i, (term, size) in enumerate(sizes.items()):
        slot[term] = i
        total += size
        offsets.append(total)
    return slot, offsets


def build(counts: list, vectors: list[dict], meta: list[set], lengths: list[int], df, n: int,
          avg: float, k1: float, b: float) -> Postings:
    """Build postings from the features LexicalIndex already holds."""
    slot, offsets = _layout(df)
    idf = [math.log(1 + (n-df[t]+.5)/(df[t]+.5)) for t in slot]
    total = offsets[-1]
    docs = array('i', bytes(4*total))
    bm25 = array('d', bytes(8*total))
    tfidf = array('d', bytes(8*total))
    cursor = list(offsets[:-1])
    for i, (tf_row, vec, length) in enumerate(zip(counts, vectors, lengths)):
        norm_len = 1-b+b*length/avg
        for t, tf in tf_row.items():
            s = slot[t]
            p = cursor[s]
            cursor[s] = p+1
            docs[p] = i
            # Same operand order as the full-scan scorer: (idf*tf*(k1+1)) / (tf + k1*norm_len).
            bm25[p] = idf[s]*tf*(k1+1)/(tf+k1*norm_len)
            tfidf[p] = vec[t]

    meta_sizes: dict[str, int] = {}
    for terms in meta:
        for t in terms:
            meta_sizes[t] = meta_sizes.get(t, 0)+1
    meta_slot, meta_offsets = _layout(meta_sizes)
    meta_docs = array('i', bytes(4*meta_offsets[-1]))
    cursor = list(meta_offsets[:-1])
    for i, terms in enumerate(meta):
        for t in terms:
            s = meta_slot[t]
            meta_docs[cursor[s]] = i
            cursor[s] += 1
    return Postings(slot, offsets, docs, bm25, tfidf, meta_slot, meta_offsets, meta_docs, k1, b)
