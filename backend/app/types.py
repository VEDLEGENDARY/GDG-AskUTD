"""Shared data types for the GDG-AskUTD backend. Do not change without team agreement."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AnswerProvider = Literal['gemini', 'ollama', 'extractive', 'api']


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    doc_id: str
    text: str
    source_title: str
    section_heading: str
    score: float
    source_url: str | None = None


@dataclass(frozen=True)
class RetrievalResult:
    passages: list[Passage] = field(default_factory=list)
    abstain: bool = False
    reason: str | None = None  # why it abstained, for logs only


@dataclass(frozen=True)
class Turn:
    role: str  # "user" or "assistant"
    content: str


@dataclass(frozen=True)
class Citation:
    n: int  # the [n] marker used in the answer text, 1-based
    chunk_id: str
    doc_id: str
    title: str
    section: str
    snippet: str  # at most 240 characters of the cited passage
    source_url: str | None = None


@dataclass(frozen=True)
class Answer:
    text: str  # contains [1] style markers that match Citation.n
    citations: list[Citation] = field(default_factory=list)
    abstained: bool = False
    provider: AnswerProvider | None = None
