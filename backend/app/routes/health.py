"""Liveness and dependency status."""
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict:
    retrieval = request.app.state.retrieval
    generation = request.app.state.generation
    stats = retrieval.corpus_stats()
    return {"status": "ok", "documents": stats.get("documents", 0),
            "chunks": stats.get("chunks", 0), "retriever": stats.get("retriever", "unknown"),
            "llm": generation.llm_status()}
