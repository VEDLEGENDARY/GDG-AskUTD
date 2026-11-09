"""Grounded, cited answer generation over retrieved passages.

Public contract (see task-2-generation.md section 4.2): `ABSTAIN_TEXT`, `generate_answer`,
`stream_answer` and `llm_status`. None of them raise for normal bad input.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator

from .llm import LLM, ExtractiveLLM, get_provider
from .prompts import (ABSTAIN_SENTENCE, CONFIRM_NOTE, MAX_QUESTION_CHARS, build_prompt, leaked_system_prompt,
                      needs_confirmation, normalize_for_match, one_line, select_passages, strip_em_dashes)
from .types import Answer, Citation, Passage, Turn

logger = logging.getLogger("askutd.generation")

ABSTAIN_TEXT = ("I could not find that in the UT Dallas pages I have. Try rephrasing, "
                "or check with the relevant UT Dallas office.")
SNIPPET_CHARS = 240

_STREAM_HOLDBACK = 60  # longer than the 40 character leak window, so leaks are caught before display
_WORDS_PER_TOKEN = 4
_MARKER = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")
_MARKER_RUN = re.compile(r"\[\d+\](?:[ \t]*\[\d+\])+")
_PARTIAL_MARKER = re.compile(r"\[[\d,\s]*$")
_LETTER = re.compile(r"[^\W\d_]")
_HAS_CONFIRM = re.compile(r"\b(?:confirm|verify)\b", re.IGNORECASE)
_ABSTAIN_NORMS = (normalize_for_match(ABSTAIN_SENTENCE),
                  normalize_for_match("I couldn't find that in the UT Dallas pages I have"))

_override: LLM | None = None


def set_provider(provider: LLM | None) -> None:
    """Force a provider instance (tests, demos). Pass None to go back to LLM_PROVIDER."""
    global _override
    _override = provider


def _provider() -> LLM:
    return _override if _override is not None else get_provider()


def llm_status() -> str:
    """Describe the configured provider, e.g. "ollama:llama3.2:3b" or "extractive"."""
    try:
        return _provider().name
    except Exception:
        logger.exception("could not build the configured provider")
        return "extractive"


def _abstain() -> Answer:
    return Answer(text=ABSTAIN_TEXT, citations=[], abstained=True)


def make_snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """Flatten `text` and cut it to at most `limit` characters at a word boundary."""
    flat = strip_em_dashes(one_line(text))
    if len(flat) <= limit:
        return flat
    return one_line(flat, limit - 3).rstrip(" ,;:") + "..."


def tidy_citations(raw: str, k: int) -> tuple[str, list[int]]:
    """Drop markers outside 1..k and renumber the rest by first appearance.

    Returns the cleaned text and the original passage numbers in their new order, so
    `order[0]` is the passage now cited as [1]. Also replaces em dashes with commas.
    """
    order: list[int] = []

    def renumber(match: re.Match) -> str:
        markers: list[str] = []
        for part in match.group(1).split(","):
            n = int(part)
            if 1 <= n <= k:
                if n not in order:
                    order.append(n)
                marker = f"[{order.index(n) + 1}]"
                if marker not in markers:
                    markers.append(marker)
        return "".join(markers)

    text = _MARKER.sub(renumber, strip_em_dashes(raw))
    text = _MARKER_RUN.sub(lambda m: "".join(dict.fromkeys(re.findall(r"\[\d+\]", m.group(0)))), text)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), order


def _is_abstain(raw: str, order: list[int]) -> bool:
    norm = normalize_for_match(raw)
    if any(norm.startswith(sentence) for sentence in _ABSTAIN_NORMS):
        return True
    return not order and any(sentence in norm for sentence in _ABSTAIN_NORMS)


def _citation(n: int, passage: Passage) -> Citation:
    return Citation(n=n, chunk_id=passage.chunk_id, doc_id=passage.doc_id,
                    title=strip_em_dashes(passage.source_title), section=strip_em_dashes(passage.section_heading),
                    snippet=make_snippet(passage.text), source_url=passage.source_url)


def finalize(raw: str, passages: list[Passage]) -> Answer | None:
    """Turn a raw model reply into a validated Answer. None means the reply is unusable."""
    if not passages:
        return _abstain()
    if not raw or not raw.strip():
        return None
    if leaked_system_prompt(raw):
        logger.warning("model output repeated the system prompt, discarding it")
        return None
    text, order = tidy_citations(raw, len(passages))
    if _is_abstain(raw, order):
        return _abstain()
    if not _LETTER.search(_MARKER.sub("", text)):
        return None
    if not order:
        text, order = f"{text} [1]", [1]
    if needs_confirmation(text) and not _HAS_CONFIRM.search(text):
        text = f"{text} {CONFIRM_NOTE}"
    citations = [_citation(n, passages[original - 1]) for n, original in enumerate(order, 1)]
    return Answer(text=text, citations=citations, abstained=False)


def _prepare(question: str, passages: list[Passage] | None,
             history: list[Turn] | None) -> tuple[list[Passage], str, str] | None:
    q = one_line(question, MAX_QUESTION_CHARS)
    if not _LETTER.search(q) and not re.search(r"\d", q):
        return None
    selected = select_passages(passages)
    if not selected:
        return None
    system, user = build_prompt(q, selected, history)
    return selected, system, user


def _fallback(system: str, user: str, passages: list[Passage]) -> Answer:
    try:
        answer = finalize(ExtractiveLLM().complete(system, user), passages)
    except Exception:
        logger.exception("extractive fallback failed")
        answer = None
    return answer or _abstain()


def generate_answer(question: str, passages: list[Passage], history: list[Turn] | None = None) -> Answer:
    """Answer `question` from `passages` with validated [n] citations, or abstain."""
    try:
        prepared = _prepare(question, passages, history)
        if prepared is None:
            return _abstain()
        selected, system, user = prepared
        provider = _provider()
        try:
            raw = provider.complete(system, user)
        except Exception as exc:
            logger.warning("provider %s failed (%s), falling back to extractive", provider.name, exc)
            return _fallback(system, user, selected)
        answer = finalize(raw, selected)
        if answer is None and not isinstance(provider, ExtractiveLLM):
            logger.warning("provider %s gave unusable output, falling back to extractive", provider.name)
            return _fallback(system, user, selected)
        return answer or _abstain()
    except Exception:
        logger.exception("generate_answer failed unexpectedly")
        return _abstain()


def _pieces(text: str) -> list[str]:
    words = re.findall(r"\s*\S+", text)
    return ["".join(words[i:i + _WORDS_PER_TOKEN]) for i in range(0, len(words), _WORDS_PER_TOKEN)]


def _tokens(text: str) -> Iterator[dict]:
    for piece in _pieces(text):
        yield {"type": "token", "text": piece}


class _StreamValidator:
    """Releases streamed text only once it is citation-safe, and tracks what was shown."""

    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages
        self.raw = ""
        self.emitted = ""
        self.emitted_raw_end = 0
        self.mode = "probe"  # probe -> emit, or probe -> abstain, or emit -> leak

    @property
    def stopped(self) -> bool:
        return self.mode in ("abstain", "leak")

    def feed(self, piece: str) -> str:
        """Add a streamed piece and return the newly displayable text (possibly "")."""
        if self.stopped or not isinstance(piece, str) or not piece:
            return ""
        self.raw += piece
        if self.mode == "probe":
            norm = normalize_for_match(self.raw)
            if any(norm.startswith(sentence) for sentence in _ABSTAIN_NORMS):
                self.mode = "abstain"
                return ""
            if not norm or any(sentence.startswith(norm) for sentence in _ABSTAIN_NORMS):
                return ""
            self.mode = "emit"
        if leaked_system_prompt(self.raw):
            logger.warning("streamed output repeated the system prompt, stopping the stream")
            self.mode = "leak"
            return ""
        end = max(0, len(self.raw) - _STREAM_HOLDBACK)
        partial = _PARTIAL_MARKER.search(self.raw, 0, end)
        if partial:
            end = partial.start()
        space = max(self.raw.rfind(" ", self.emitted_raw_end, end), self.raw.rfind("\n", self.emitted_raw_end, end))
        if space > self.emitted_raw_end:
            end = space
        if end <= self.emitted_raw_end:
            return ""
        text = tidy_citations(self.raw[:end], len(self.passages))[0].rstrip()
        if len(text) <= len(self.emitted) or not text.startswith(self.emitted):
            return ""
        delta, self.emitted, self.emitted_raw_end = text[len(self.emitted):], text, end
        return delta

    def finish(self, failed: bool) -> Answer | None:
        """Validate what was received. After a failure or leak, only the shown part counts."""
        if self.mode == "abstain":
            return _abstain()
        source = self.raw[:self.emitted_raw_end] if failed or self.mode == "leak" else self.raw
        return finalize(source, self.passages) if source else None

    def remaining(self, answer: Answer) -> str:
        """Text of `answer` that the client has not seen yet."""
        if answer.text.startswith(self.emitted):
            return answer.text[len(self.emitted):]
        logger.warning("streamed text diverged from the validated answer")
        return ""


def _stream(question: str, passages: list[Passage], history: list[Turn] | None) -> Iterator[dict]:
    prepared = _prepare(question, passages, history)
    if prepared is None:
        yield from _tokens(ABSTAIN_TEXT)
        yield {"type": "final", "answer": _abstain()}
        return
    selected, system, user = prepared
    provider = _provider()
    validator = _StreamValidator(selected)
    failed = False
    pieces = None
    try:
        pieces = provider.stream(system, user)
        for piece in pieces:
            delta = validator.feed(piece)
            if delta:
                yield {"type": "token", "text": delta}
            if validator.stopped:
                break
    except Exception as exc:
        failed = True
        logger.warning("provider %s failed while streaming (%s), falling back to extractive", provider.name, exc)
    finally:
        close = getattr(pieces, "close", None)
        if callable(close):
            close()
    answer = validator.finish(failed)
    if answer is None:
        if not failed and not isinstance(provider, ExtractiveLLM):
            logger.warning("provider %s gave unusable output, falling back to extractive", provider.name)
        answer = _fallback(system, user, selected)
    yield from _tokens(validator.remaining(answer))
    yield {"type": "final", "answer": answer}


def stream_answer(question: str, passages: list[Passage], history: list[Turn] | None = None) -> Iterator[dict]:
    """Yield {"type": "token", "text"} events, then exactly one {"type": "final", "answer"}."""
    final_sent = False
    try:
        for event in _stream(question, passages, history):
            final_sent = final_sent or event["type"] == "final"
            yield event
    except Exception:
        logger.exception("stream_answer failed unexpectedly")
        if not final_sent:
            yield {"type": "final", "answer": _abstain()}
