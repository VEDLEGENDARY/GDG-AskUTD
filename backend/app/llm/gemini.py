"""Google AI Studio sentence selection through the Gemini Developer API."""
from __future__ import annotations

import requests

from .base import LLMError

MODEL = "gemini-3.1-flash-lite"


class GeminiLLM:
    name = f"gemini:{MODEL}"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def complete(self, system: str, user: str, *, output_schema: dict) -> str:
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is missing")
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json={"systemInstruction": {"parts": [{"text": system}]},
                      "contents": [{"parts": [{"text": user}]}],
                      "generationConfig": {"responseMimeType": "application/json",
                                           "responseJsonSchema": output_schema,
                                           "maxOutputTokens": 128,
                                           "thinkingConfig": {"thinkingLevel": "MINIMAL"}}},
                timeout=(3, 12),
            )
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts if not part.get("thought"))
        except requests.HTTPError as exc:
            raise LLMError(f"Gemini returned HTTP {exc.response.status_code}") from None
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise LLMError("Gemini request failed or returned no usable content") from None
