"""Provider for any OpenAI compatible `/chat/completions` endpoint, using `requests`."""
from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from .base import DEFAULT_TEMPERATURE, DEFAULT_TIMEOUT_S, MAX_OUTPUT_TOKENS, LLMError


class OpenAICompatLLM:
    """Calls `<base_url>/chat/completions` with an optional bearer token."""

    def __init__(self, base_url: str, api_key: str = "", model: str = "",
                 timeout: float = DEFAULT_TIMEOUT_S, temperature: float = DEFAULT_TEMPERATURE) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout = timeout
        self.temperature = temperature
        self.name = f"openai_compat:{self.model or 'unset'}"

    def _request(self, system: str, user: str, stream: bool) -> requests.Response:
        if not self.base_url or not self.model:
            raise LLMError("OPENAI_BASE_URL and OPENAI_MODEL must be set")
        url = self.base_url if self.base_url.endswith("/chat/completions") else f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": stream,
        }
        response = requests.post(url, json=payload, headers=headers, timeout=self.timeout, stream=stream)
        response.raise_for_status()
        return response

    def complete(self, system: str, user: str) -> str:
        """Return the first choice's message content."""
        try:
            data = self._request(system, user, False).json()
            text = data["choices"][0]["message"].get("content") or ""
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(f"openai_compat request failed: {exc}") from exc
        if not text.strip():
            raise LLMError("openai_compat returned empty output")
        return text

    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield delta content from the server-sent event stream."""
        try:
            with self._request(system, user, True) as response:
                for raw in response.iter_lines():
                    line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    choices = json.loads(body).get("choices") or [{}]
                    piece = (choices[0].get("delta") or {}).get("content") or ""
                    if piece:
                        yield piece
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(f"openai_compat stream failed: {exc}") from exc
