"""Shared request and serialization helpers."""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict

from fastapi import Request

from ..types import Citation, Passage, Turn

logger = logging.getLogger("askutd")


def new_request_id() -> str:
    return str(uuid.uuid4())


def to_turns(items) -> list[Turn]:
    return [Turn(role=item.role, content=item.content) for item in items]


def passage_citations(passages: list[Passage]) -> list[Citation]:
    return [Citation(i, p.chunk_id, p.doc_id, p.source_title, p.section_heading,
                     p.text[:240], p.source_url) for i, p in enumerate(passages, 1)]


def jsonable(value):
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value


def sse(event: str, payload) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable(payload), ensure_ascii=False, separators=(',', ':'))}\n\n"


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def record_request(request: Request, request_id: str, started: float, question: str,
                   abstained: bool, citation_count: int) -> int:
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    app = request.app
    app.state.db.save_request(
        app.state.settings.database_path, request_id=request_id, question=question,
        abstained=abstained, latency_ms=latency_ms, citation_count=citation_count,
        retriever=app.state.retrieval.corpus_stats().get("retriever", "unknown"),
        llm=app.state.generation.llm_status())
    logger.info("chat completed", extra={"request_id": request_id, "latency_ms": latency_ms,
                                         "abstained": abstained, "citation_count": citation_count,
                                         "question_preview": question[:80]})
    return latency_ms
