"""Document catalog and starter question endpoints."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

from ..config import ROOT

router = APIRouter()
SUGGESTIONS = [
    "How do I drop a class?",
    "Am I eligible for a tuition rebate?",
    "How can I request my transcript?",
    "How do I establish Texas residency for tuition?",
    "How do I transfer credit to UT Dallas?",
    "When is the academic calendar for this semester?",
]


@lru_cache(maxsize=1)
def documents() -> list[dict]:
    manifest = ROOT / "backend" / "data" / "documents.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("documents"), list):
            return data["documents"]
    grouped: dict[str, dict] = {}
    for path in sorted((ROOT / "backend" / "data" / "chunks").glob("*.json")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in rows if isinstance(rows, list) else []:
            doc_id = row.get("doc_id")
            if not doc_id:
                continue
            doc = grouped.setdefault(doc_id, {"doc_id": doc_id, "title": row.get("source_title") or doc_id,
                                               "source_url": None, "chunks": 0})
            doc["chunks"] += 1
    return sorted(grouped.values(), key=lambda d: d["doc_id"])


@router.get("/documents")
def get_documents() -> list[dict]:
    return documents()


@router.get("/suggestions")
def get_suggestions() -> list[str]:
    return list(SUGGESTIONS)
