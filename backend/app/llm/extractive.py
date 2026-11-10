"""No-LLM fallback: answer with the passage sentences that best match the question."""
from __future__ import annotations

import math
import re
from collections.abc import Iterator

from ..prompts import parse_user_prompt

_STOP = frozenset(
    "a an the is are was were be been to of in on for and or with by at i my me do does did how what "
    "when where which who why can could should would will it its this that these those there their "
    "you your we our as from if about into than then so not no any some get "
    "ut utd dallas texas university student students".split())
# Questions about one student's own records or request status, which public pages cannot answer.
_PERSONAL = re.compile(
    r"^\s*(?:has|have|did|was|were)\b[^?]*\b(?:my|me|i)\b"
    r"|\bmy\s+(?:own|assigned)\b"
    r"|\b(?:my|i am taking)\b[^?]*\b(?:this semester|next semester|next week|yesterday|now)\b"
    r"|\bthis class\b",
    re.IGNORECASE)
_YEAR = re.compile(r"\b20\d\d\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")
_MAX_SENTENCES = 3
_MAX_WORDS = 120
_MIN_SENTENCE_WORDS = 4
_MAX_SENTENCE_WORDS = 70


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


def terms(text: str) -> set[str]:
    """Content words of `text`, lowercased and lightly stemmed."""
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.casefold()) if w not in _STOP}


def _with_marker(sentence: str, n: int) -> str:
    sentence = sentence.strip()
    if sentence and sentence[-1] in ".!?":
        return f"{sentence[:-1]} [{n}]{sentence[-1]}"
    return f"{sentence} [{n}]."


def extractive_answer(question: str, passages: list[str]) -> str:
    """Return 1 to 3 cited sentences from `passages`, or "" when nothing overlaps the question."""
    wanted = terms(question)
    if not wanted or _PERSONAL.search(question):
        return ""
    corpus = " ".join(passages)
    if any(year not in corpus for year in _YEAR.findall(question)):
        return ""
    needed = max(1, min(3, math.ceil(len(wanted) * 0.5)))
    candidates = []
    for p_index, text in enumerate(passages):
        rank_bonus = 0.3 * (1 - p_index / max(1, len(passages)))
        for s_index, sentence in enumerate(_SENTENCE_END.split(text)):
            if re.search(r"\b(?:follow these details|see policies|see details|for more information)\b", sentence, re.I):
                continue
            words = sentence.split()
            if not _MIN_SENTENCE_WORDS <= len(words) <= _MAX_SENTENCE_WORDS:
                continue
            overlap = len(wanted & terms(sentence))
            if overlap >= needed:
                candidates.append((overlap + rank_bonus, overlap, p_index, s_index, sentence.strip()))
    if not candidates:
        return ""
    candidates.sort(key=lambda c: (-c[0], c[2], c[3]))
    best_overlap = candidates[0][1]
    chosen, seen, words_used = [], set(), 0
    for score, overlap, p_index, s_index, sentence in candidates:
        if len(chosen) == _MAX_SENTENCES or overlap < best_overlap * 0.5:
            break
        key = sentence.casefold()
        length = len(sentence.split())
        if key in seen or (chosen and words_used + length > _MAX_WORDS):
            continue
        seen.add(key)
        chosen.append((p_index, s_index, sentence))
        words_used += length
    chosen.sort()
    return " ".join(_with_marker(sentence, p_index + 1) for p_index, _, sentence in chosen)


class ExtractiveLLM:
    """Provider that reads the numbered passages out of the user prompt. Never fails."""

    name = "extractive"

    def complete(self, system: str, user: str) -> str:
        """Return an extractive answer, or "" if no sentence matches."""
        question, passages = parse_user_prompt(user)
        return extractive_answer(question, passages)

    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield the extractive answer a few words at a time."""
        words = re.findall(r"\S+\s*", self.complete(system, user))
        for start in range(0, len(words), 4):
            yield "".join(words[start:start + 4])
