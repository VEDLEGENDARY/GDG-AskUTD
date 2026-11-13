"""Validated request and response models for the public HTTP API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .types import AnswerProvider


class TurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be empty")
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)
    history: list[TurnInput] = Field(default_factory=list, max_length=6)
    top_k: int = Field(default=5, ge=1, le=8)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        return value


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=64)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("request_id")
    @classmethod
    def strip_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("request_id must not be empty")
        return value

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class CitationOutput(BaseModel):
    n: int
    chunk_id: str
    doc_id: str
    title: str
    section: str
    snippet: str
    source_url: str | None = None


class ChatResponse(BaseModel):
    request_id: str
    answer: str
    abstained: bool
    citations: list[CitationOutput]
    latency_ms: int
    provider: AnswerProvider | None = None
