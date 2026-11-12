"""Lazy, offline retrieval service implementing the shared backend contract."""
from __future__ import annotations

import json
import logging
from dataclasses import fields
from functools import lru_cache
from pathlib import Path

from evaluate import evaluate_chunks as ev

from .retrieval_support.facets import merge_facets
from .retrieval_support.focus import ap_requests, ap_row_supports, focus_for, scope_matches
from .retrieval_support.index import LexicalIndex
from .retrieval_support.precision import (catalog_elective_fact, catalog_elective_types,
                                          catalog_scopes, catalog_title_matches, evidence_reason, rerank)
from .retrieval_support.query import OUTSIDE, private_reason, reject, rewrite
from .types import Passage, RetrievalResult, Turn

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'backend' / 'retrieval_config.json'
log = logging.getLogger(__name__)


def load_urls(path: Path) -> dict[str, str]:
    """Read optional registry URLs without making registry failures fatal."""
    try:
        rows = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(rows, list):
            return {}
        return {r['doc_id']: r['source_url'] for r in rows if isinstance(r, dict)
                and isinstance(r.get('doc_id'), str) and isinstance(r.get('source_url'), str)
                and r['source_url'].startswith(('https://', 'http://'))}
    except (OSError, ValueError, TypeError):
        log.warning('Source registry unavailable: %s', path)
        return {}


@lru_cache(maxsize=1)
def _load() -> tuple[LexicalIndex, dict, dict[str, str], dict]:
    """Build the full index once, using repository-relative configured paths."""
    config = ev.read_json(CONFIG)
    settings = ev.Settings(**{f.name: config[f.name] for f in fields(ev.Settings)})
    settings.validate()
    chunks = ev.read_chunks(ROOT / config['chunks_path'])
    index = LexicalIndex(chunks, settings)
    stats = {'documents': len({c['doc_id'] for c in chunks}), 'chunks': len(chunks), 'retriever': 'lexical-reranked'}
    return index, config, load_urls(ROOT / config['registry_path']), stats


def retrieve(query: str, top_k: int = 5, history: list[Turn] | None = None) -> RetrievalResult:
    """Return budgeted passages, or an empty abstention for unsupported questions."""
    try:
        index, config, urls, _ = _load()
        return retrieve_from_index(index, config, urls, query, top_k, history)
    except (OSError, ValueError, KeyError, TypeError):
        log.exception('Retrieval failed')
        return RetrievalResult(abstain=True, reason='retrieval unavailable')


def retrieve_from_index(index: LexicalIndex, config: dict, urls: dict[str, str],
                        query: str, top_k: int = 5, history: list[Turn] | None = None) -> RetrievalResult:
    """Run production retrieval over a supplied index, including staged corpora."""
    if not isinstance(query, str) or not query.strip() or not ev.tokens(query):
        return RetrievalResult(abstain=True, reason='empty query')
    if type(top_k) is not int or not 1 <= top_k <= 8:
        return RetrievalResult(abstain=True, reason='invalid top_k')
    query = rewrite(query.strip()[:2000], history)
    if OUTSIDE.search(query):
        return RetrievalResult(abstain=True, reason='out of scope')
    if reason := private_reason(query):
        return RetrievalResult(abstain=True, reason=reason)
    focus = focus_for(query)
    exams = ap_requests(query)

    def matches_request(row: dict) -> bool:
        if focus and not (focus.supports(row['text'], ev.metadata(row)) and scope_matches(
                query, row.get('source_title', ''), row.get('section_heading', ''), default_full_term=True)):
            return False
        return not exams or any(ap_row_supports(row['text'], exam, score) for exam, score in exams.items())

    hits = index.search(query, top_k, reranker=rerank,
                        candidate_floor=config.get('focused_candidate_floor') if focus or exams else None,
                        candidate_filter=matches_request if focus or exams else None)
    scopes = catalog_scopes(query)
    if scopes and not (focus or exams):
        scoped_hits = [
            index.search(query, min(3, top_k), reranker=rerank,
                         candidate_floor=config.get('focused_candidate_floor'),
                         candidate_filter=lambda row: catalog_title_matches(
                             row['source_title'], program, edition))
            for program, edition in scopes
        ]
        types = catalog_elective_types(query)
        if types:
            scoped_hits = [[next((hit for hit in group if catalog_elective_fact(hit['text'], kind)), None)
                            for kind in types] for group in scoped_hits]
            if any(hit is None for group in scoped_hits for hit in group):
                return RetrievalResult(abstain=True, reason='missing catalog elective evidence')
        if all(scoped_hits):
            hits = merge_facets([], scoped_hits, top_k=top_k, budget=index.s.context_budget,
                                document_cap=index.s.max_per_document)
    if exams:
        if not all(any(ap_row_supports(hit['text'], exam, score) for hit in hits)
                   for exam, score in exams.items()):
            return RetrievalResult(abstain=True, reason='missing requested AP exam score evidence')
    reason = reject(query, hits, config) or evidence_reason(query, hits)
    if reason:
        return RetrievalResult(abstain=True, reason=reason)
    return RetrievalResult(passages=[Passage(
        chunk_id=h['chunk_id'], doc_id=h['doc_id'], text=h['text'],
        source_title=h.get('source_title', ''), section_heading=h.get('section_heading', ''),
        score=h['retrieval_score'], source_url=urls.get(h['doc_id'])) for h in hits])


def corpus_stats() -> dict:
    """Return full corpus counts and the active retrieval implementation."""
    return dict(_load()[3])
