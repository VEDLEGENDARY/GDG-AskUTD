"""Lazy, offline retrieval service implementing the shared backend contract."""
from __future__ import annotations

import json
import logging
from dataclasses import fields
from functools import lru_cache
from pathlib import Path

from evaluate import evaluate_chunks as ev

from .retrieval_support.index import LexicalIndex
from .retrieval_support.query import reject, rewrite
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
    stats = {'documents': len({c['doc_id'] for c in chunks}), 'chunks': len(chunks), 'retriever': 'lexical'}
    return index, config, load_urls(ROOT / config['registry_path']), stats


def retrieve(query: str, top_k: int = 5, history: list[Turn] | None = None) -> RetrievalResult:
    """Return budgeted passages, or an empty abstention for unsupported questions."""
    if not isinstance(query, str) or not query.strip() or not ev.tokens(query):
        return RetrievalResult(abstain=True, reason='empty query')
    if type(top_k) is not int or not 1 <= top_k <= 8:
        return RetrievalResult(abstain=True, reason='invalid top_k')
    query = rewrite(query.strip()[:2000], history)
    try:
        index, config, urls, _ = _load()
        hits = index.search(query, top_k)
        reason = reject(query, hits, config)
        if reason:
            return RetrievalResult(abstain=True, reason=reason)
        return RetrievalResult(passages=[Passage(
            chunk_id=h['chunk_id'], doc_id=h['doc_id'], text=h['text'],
            source_title=h.get('source_title', ''), section_heading=h.get('section_heading', ''),
            score=h['retrieval_score'], source_url=urls.get(h['doc_id'])) for h in hits])
    except (OSError, ValueError, KeyError, TypeError):
        log.exception('Retrieval corpus could not be loaded')
        return RetrievalResult(abstain=True, reason='retrieval unavailable')


def corpus_stats() -> dict:
    """Return full corpus counts and the active retrieval implementation."""
    return dict(_load()[3])
