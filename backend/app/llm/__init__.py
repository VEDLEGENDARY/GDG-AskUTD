"""Pluggable LLM providers, selected with the LLM_PROVIDER environment variable."""
from __future__ import annotations

import logging
import os

from .base import LLM, LLMError
from .extractive import ExtractiveLLM
from .fake import FakeLLM
from .ollama_provider import DEFAULT_HOST, DEFAULT_MODEL, OllamaLLM
from .openai_compat import OpenAICompatLLM

logger = logging.getLogger("askutd.llm")

PROVIDERS = ("ollama", "openai_compat", "extractive", "fake")

__all__ = ["LLM", "LLMError", "ExtractiveLLM", "FakeLLM", "OllamaLLM", "OpenAICompatLLM",
           "PROVIDERS", "get_provider"]


def get_provider(name: str | None = None) -> LLM:
    """Build the provider named by `name` or LLM_PROVIDER (default `ollama`).

    Unknown names log a warning and use `extractive`.
    """
    choice = (name or os.environ.get("LLM_PROVIDER") or "ollama").strip().lower()
    if choice == "ollama":
        return OllamaLLM(host=os.environ.get("OLLAMA_HOST", DEFAULT_HOST),
                         model=os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL))
    if choice == "openai_compat":
        return OpenAICompatLLM(base_url=os.environ.get("OPENAI_BASE_URL", ""),
                               api_key=os.environ.get("OPENAI_API_KEY", ""),
                               model=os.environ.get("OPENAI_MODEL", ""))
    if choice == "fake":
        return FakeLLM()
    if choice != "extractive":
        logger.warning("unknown LLM_PROVIDER %r, using extractive", choice)
    return ExtractiveLLM()
