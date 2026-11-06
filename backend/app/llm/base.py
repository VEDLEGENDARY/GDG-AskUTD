"""Provider interface shared by every LLM backend."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

DEFAULT_TIMEOUT_S = 60.0
DEFAULT_TEMPERATURE = 0.1
MAX_OUTPUT_TOKENS = 320


class LLMError(RuntimeError):
    """Raised by a provider when it cannot produce usable output."""


@runtime_checkable
class LLM(Protocol):
    """A text generator that takes a system prompt and a user prompt."""

    name: str

    def complete(self, system: str, user: str) -> str:
        """Return the full reply. Raise on connection errors, timeouts or empty output."""
        ...

    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield the reply in pieces as it is produced."""
        ...
