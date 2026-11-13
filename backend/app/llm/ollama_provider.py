"""Ollama provider using the HTTP chat API through `requests`."""
from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from .base import DEFAULT_TEMPERATURE, DEFAULT_TIMEOUT_S, MAX_OUTPUT_TOKENS, LLMError

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2:3b"


class OllamaLLM:
    """Talks to a local or remote Ollama server at `/api/chat`."""

    def __init__(self, host: str = DEFAULT_HOST, model: str = DEFAULT_MODEL,
                 timeout: float = DEFAULT_TIMEOUT_S, temperature: float = DEFAULT_TEMPERATURE) -> None:
        self.host = (host or DEFAULT_HOST).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.temperature = temperature
        self.name = f"ollama:{self.model}"

    def _payload(self, system: str, user: str, stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": stream,
            "options": {"temperature": self.temperature, "num_predict": MAX_OUTPUT_TOKENS},
        }

    def complete(self, system: str, user: str, *, output_schema: dict | None = None) -> str:
        """Return the whole reply from one non-streaming request."""
        payload = self._payload(system, user, False)
        if output_schema is not None:
            payload["format"] = output_schema
        try:
            response = requests.post(f"{self.host}/api/chat", json=payload,
                                     timeout=self.timeout)
            response.raise_for_status()
            text = (response.json().get("message") or {}).get("content") or ""
        except (requests.RequestException, ValueError, AttributeError) as exc:
            raise LLMError(f"ollama request failed: {exc}") from exc
        if not text.strip():
            raise LLMError("ollama returned empty output")
        return text

    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield content pieces from Ollama's newline-delimited JSON stream."""
        try:
            with requests.post(f"{self.host}/api/chat", json=self._payload(system, user, True),
                               timeout=self.timeout, stream=True) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise LLMError(f"ollama error: {data['error']}")
                    piece = (data.get("message") or {}).get("content") or ""
                    if piece:
                        yield piece
                    if data.get("done"):
                        break
        except (requests.RequestException, ValueError, AttributeError) as exc:
            raise LLMError(f"ollama stream failed: {exc}") from exc
