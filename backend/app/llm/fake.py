"""Deterministic provider for tests. Never touches the network."""
from __future__ import annotations

from collections.abc import Callable, Iterator

DEFAULT_REPLY = "This is a fake answer based on the first passage [1]."


class FakeLLM:
    """Returns a fixed or computed reply and records every call.

    `error` is raised by `complete` and before the first `stream` piece. `fail_after`
    raises `error` (or a RuntimeError) after that many stream pieces instead.
    """

    name = "fake"

    def __init__(self, reply: str | Callable[[str, str], str] = DEFAULT_REPLY,
                 error: Exception | None = None, chunk_size: int = 3,
                 fail_after: int | None = None) -> None:
        self.reply = reply
        self.error = error
        self.chunk_size = max(1, chunk_size)
        self.fail_after = fail_after
        self.calls: list[tuple[str, str]] = []

    def _text(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply(system, user) if callable(self.reply) else self.reply

    def complete(self, system: str, user: str) -> str:
        """Return the reply, or raise the configured error."""
        if self.error is not None and self.fail_after is None:
            self._text(system, user)
            raise self.error
        return self._text(system, user)

    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield the reply `chunk_size` characters at a time."""
        if self.error is not None and self.fail_after is None:
            self._text(system, user)
            raise self.error
        text = self._text(system, user)
        for count, start in enumerate(range(0, len(text), self.chunk_size)):
            if self.fail_after is not None and count >= self.fail_after:
                raise self.error or RuntimeError("fake stream failure")
            yield text[start:start + self.chunk_size]
