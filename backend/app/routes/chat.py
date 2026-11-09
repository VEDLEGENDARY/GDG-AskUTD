"""Synchronous and server-sent-event chat endpoints."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from ..schemas import ChatRequest, ChatResponse
from ..types import Answer
from .common import client_ip, new_request_id, passage_citations, record_request, sse, to_turns

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
    result = retrieval.retrieve(body.question, body.top_k, history)
    if result.abstain:
        answer = Answer(generation.ABSTAIN_TEXT, abstained=True)
    else:
        answer = generation.generate_answer(body.question, result.passages, history)
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
            result = retrieval.retrieve(body.question, body.top_k, history)
            if result.abstain:
                answer = Answer(generation.ABSTAIN_TEXT, abstained=True)
                citations = []
                yield sse("citations", citations)
                yield sse("token", {"text": answer.text})
            else:
                citations = passage_citations(result.passages)
                yield sse("citations", citations)
                answer = None
                for item in generation.stream_answer(body.question, result.passages, history):
                    if item.get("type") == "token":
                        yield sse("token", {"text": item.get("text", "")})
                    elif item.get("type") == "final":
                        answer = item["answer"]
                if answer is None:
                    answer = generation.generate_answer(body.question, result.passages, history)
                final_citations = answer.citations
                if [c.__dict__ for c in final_citations] != [c.__dict__ for c in citations]:
                    yield sse("citations", final_citations)
            latency = record_request(request, request_id, started, body.question,
                                     answer.abstained, len(answer.citations))
            yield sse("done", {"abstained": answer.abstained, "latency_ms": latency})
        except Exception:
            logger.exception("streaming chat failed", extra={"request_id": request_id})
            yield sse("error", {"code": "internal_error", "message": "The request could not be completed."})

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Request-ID": request_id})
