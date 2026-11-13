"""Synchronous and server-sent-event chat endpoints."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from ..generation import drop_clarification
from ..schemas import ChatRequest, ChatResponse
from ..types import Answer
from ..retrieval_support.query import rewrite
from .common import client_ip, new_request_id, record_request, sse, to_turns

router = APIRouter()
logger = logging.getLogger("askutd")


def rate_limit(request: Request) -> None:
    ok, retry_after = request.app.state.limiter.consume(client_ip(request))
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail={"code": "rate_limit_exceeded",
                                                     "message": "Too many chat requests. Please retry shortly."},
                            headers={"Retry-After": str(retry_after)})


def _answer(request: Request, body: ChatRequest, request_id: str, started: float) -> ChatResponse:
    retrieval = request.app.state.retrieval
    generation = request.app.state.generation
    history = to_turns(body.history)
    question = rewrite(body.question, history)
    result = retrieval.retrieve(body.question, body.top_k, history)
    if clarification := drop_clarification(question):
        answer = clarification
    elif result.abstain:
        answer = Answer(generation.ABSTAIN_TEXT, abstained=True)
    else:
        answer = generation.generate_answer(question, result.passages, history)
    latency = record_request(request, request_id, started, body.question,
                             answer.abstained, len(answer.citations))
    return ChatResponse(request_id=request_id, answer=answer.text, abstained=answer.abstained,
                        citations=[c.__dict__ for c in answer.citations], latency_ms=latency)


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(rate_limit)])
async def chat(body: ChatRequest, request: Request):
    request_id = getattr(request.state, "request_id", None) or new_request_id()
    started = time.perf_counter()
    return await run_in_threadpool(_answer, request, body, request_id, started)


@router.post("/chat/stream", dependencies=[Depends(rate_limit)])
async def chat_stream(body: ChatRequest, request: Request):
    request_id = getattr(request.state, "request_id", None) or new_request_id()
    started = time.perf_counter()

    def events():
        yield sse("meta", {"request_id": request_id})
        try:
            retrieval = request.app.state.retrieval
            generation = request.app.state.generation
            history = to_turns(body.history)
            question = rewrite(body.question, history)
            result = retrieval.retrieve(body.question, body.top_k, history)
            yield sse("retrieval", {
                "passages": len(result.passages), "documents": len({p.doc_id for p in result.passages}),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "status": "insufficient" if result.abstain else "retrieved",
                "chunks": [p.chunk_id for p in result.passages],
            })
            if clarification := drop_clarification(question):
                answer = clarification
            elif result.abstain:
                answer = Answer(generation.ABSTAIN_TEXT, abstained=True)
            else:
                answer = generation.generate_answer(question, result.passages, history)
            yield sse("citations", answer.citations)
            yield sse("token", {"text": answer.text})
            latency = record_request(request, request_id, started, body.question,
                                     answer.abstained, len(answer.citations))
            yield sse("done", {"abstained": answer.abstained, "latency_ms": latency})
        except Exception:
            logger.exception("streaming chat failed", extra={"request_id": request_id})
            yield sse("error", {"code": "internal_error", "message": "The request could not be completed."})

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-ID": request_id})
