"""Offline canned retrieval and generation used by the UI during early development."""
from __future__ import annotations

import json
from functools import lru_cache

from .config import ROOT
from .types import Answer, Citation, Passage, RetrievalResult, Turn

ABSTAIN_TEXT = "I couldn't find that information in the available UT Dallas sources."

PASSAGES = [
    Passage("stub_drop_1", "stub_drop", "Students may drop a class through the registration system before the published deadline. Check the academic calendar for dates and consult the Registrar for withdrawal rules.", "Dropping a Class", "Drop and withdrawal process", .96, "https://registrar.utdallas.edu/"),
    Passage("stub_tuition_1", "stub_tuition", "A tuition rebate may be available to eligible undergraduate students who complete their degree within the required time. Eligibility and application details are provided by the university.", "Tuition Rebate", "Eligibility", .93, "https://bursar.utdallas.edu/"),
    Passage("stub_transcript_1", "stub_transcript", "Official transcripts are requested through the Office of the Registrar. Processing options and fees may apply.", "Transcripts", "Request a transcript", .91, "https://registrar.utdallas.edu/transcript/"),
]


def retrieve(query: str, top_k: int = 5, history: list[Turn] | None = None) -> RetrievalResult:
    if "weather" in query.casefold():
        return RetrievalResult(abstain=True, reason="stub weather example")
    words = set(query.casefold().split())
    scored = sorted(PASSAGES, key=lambda p: (-sum(word in (p.source_title + " " + p.text).casefold()
                                                    for word in words), p.chunk_id))
    matches = [p for p in scored if any(word in (p.source_title + " " + p.text).casefold() for word in words)]
    return RetrievalResult(passages=(matches or PASSAGES)[:top_k])


def generate_answer(question: str, passages: list[Passage], history: list[Turn] | None = None) -> Answer:
    if not passages:
        return Answer(ABSTAIN_TEXT, abstained=True)
    citations = [Citation(i, p.chunk_id, p.doc_id, p.source_title, p.section_heading,
                          p.text[:240], p.source_url) for i, p in enumerate(passages, 1)]
    title = passages[0].source_title
    return Answer(f"The available information is covered in {title}. [1]", citations)


def stream_answer(question: str, passages: list[Passage], history: list[Turn] | None = None):
    answer = generate_answer(question, passages, history)
    for token in answer.text.split(" "):
        yield {"type": "token", "text": token + " "}
    yield {"type": "final", "answer": answer}


@lru_cache(maxsize=1)
def corpus_stats() -> dict:
    files = sorted((ROOT / "backend" / "data" / "chunks").glob("*.json"))
    if not files:
        return {"documents": 3, "chunks": len(PASSAGES), "retriever": "stub"}
    count = 0
    for path in files:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            count += len(rows) if isinstance(rows, list) else 0
        except (OSError, json.JSONDecodeError):
            continue
    return {"documents": len(files), "chunks": count, "retriever": "stub"}


def llm_status() -> str:
    return "stub"
