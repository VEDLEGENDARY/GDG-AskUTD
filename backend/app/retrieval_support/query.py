"""Deterministic follow-up resolution and evidence checks."""
from __future__ import annotations

import re

from evaluate import evaluate_chunks as ev

from ..types import Turn

PERSONAL = re.compile(
    r"^\s*(?:has|have|did)\b.*\b(?:my|me|i uploaded)\b|\bmy (?:own|assigned|corrected)\b"
    r"|^\s*what is my cumulative\b"
    r"|\b(?:my|me)\b.*\b(?:already|currently|next week|last week|yesterday|now|owe)\b"
    r"|\b(?:my|me)\b.*\b(?:appointment|offered|offer|processed|accepted|assigned)\b"
    r"|\bthis class\b|\bcourse i am taking this semester\b", re.I)
OUTSIDE = re.compile(r"\b(?:weather|joke|write (?:me )?(?:code|a program)|harvard|stanford)\b", re.I)
STOP = set('ut utd dallas texas university student students please tell explain about would could should will must many much when where who why get'.split())


def rewrite(query: str, history: list[Turn] | None) -> str:
    """Anchor a short elliptical follow-up to the most recent user question."""
    if len(query.split()) > 12 or not re.search(
            r"^(?:what about|how about|and\b|what if|does (?:that|it)|can (?:they|i)|is (?:that|it))|\b(?:that|those|it)\b", query, re.I):
        return query
    if isinstance(history, list):
        for turn in reversed(history[-6:]):
            if isinstance(turn, Turn) and turn.role == 'user' and isinstance(turn.content, str) and turn.content.strip():
                return turn.content[:500] + ' ' + query
    return query


def reject(query: str, hits: list[dict], config: dict) -> str | None:
    """Reject private records, missing time scope, and low-overlap evidence."""
    if OUTSIDE.search(query):
        return 'out of scope'
    if PERSONAL.search(query):
        return 'private record or missing course context'
    if not hits:
        return 'no evidence above score threshold'
    evidence = ' '.join(ev.context_text(h) for h in hits)
    years = re.findall(r'\b20\d{2}\b', query)
    if any(year not in evidence for year in years):
        return 'requested year absent from evidence'
    terms = set(ev.tokens(query))-STOP
    coverage = max((len(terms & set(ev.tokens(ev.context_text(h))))/max(1, len(terms)) for h in hits), default=0)
    if coverage < config['min_term_coverage']:
        return 'weak query term coverage'
    if max(h['retrieval_score'] for h in hits) < config['min_top_score']:
        return 'weak top evidence score'
    return None
