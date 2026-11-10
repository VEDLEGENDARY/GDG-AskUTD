"""Example candidate adapters for scripts/mentee1_eval.py.

An adapter is any callable ``fn(query, top_k, history) -> RetrievalResult | list``.
It receives only the question text, the requested passage count and the
conversation history (``list[Turn]`` or ``None``). It never sees labels, case IDs
or evidence. Attach an optional ``warmup()`` attribute to time cold loading.

Usage:
    python scripts/mentee1_eval.py run --adapter evaluate/mentee1/example_adapters.py:ignore_history ...
"""
from __future__ import annotations

from backend.app import retrieval


def ignore_history(query, top_k, history):
    """Ablation: production retrieval with conversation history dropped."""
    return retrieval.retrieve(query, top_k=top_k, history=None)


def _warmup():
    retrieval._load.cache_clear()
    retrieval.corpus_stats()


ignore_history.warmup = _warmup
