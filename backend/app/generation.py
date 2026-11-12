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
from .retrieval_support.focus import (WITHDRAWAL_DATE, ap_requests, ap_row_supports, evidence_sentences,
                                      focus_for, scope_matches)
from .retrieval_support.precision import (catalog_elective_fact, catalog_elective_types,
                                          catalog_scopes, catalog_title_matches)

logger = logging.getLogger("askutd.generation")

ABSTAIN_TEXT = ("I could not find that in the UT Dallas pages I have. Try rephrasing, "
                "or check with the relevant UT Dallas office.")
SNIPPET_CHARS = 240

_WORDS_PER_TOKEN = 4
_MARKER = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")
_MARKER_RUN = re.compile(r"\[\d+\](?:[ \t]*\[\d+\])+")
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


def _citation(n: int, passage: Passage, excerpt: str) -> Citation:
    return Citation(n=n, chunk_id=passage.chunk_id, doc_id=passage.doc_id,
                    title=strip_em_dashes(passage.source_title), section=strip_em_dashes(passage.section_heading),
                    snippet=make_snippet(excerpt), source_url=passage.source_url)


def _quote_key(text: str) -> str:
    normalized = strip_em_dashes(one_line(text))
    return re.sub(r"\s+([.,;:!?])", r"\1", normalized).casefold().rstrip(".!?")


def _matching_excerpt(claim: str, passage: Passage, allow_withdrawal_date: bool) -> str | None:
    key = _quote_key(claim)
    for sentence in evidence_sentences(passage.text):
        if _quote_key(sentence) == key:
            return sentence
        if allow_withdrawal_date:
            match = WITHDRAWAL_DATE.search(sentence)
            if match and _quote_key(match[0]) == key:
                return match[0]
    return None


def finalize(raw: str, passages: list[Passage], question: str = "") -> Answer | None:
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
        return None
    if len(text.split()) > 275:
        return None
    # Validate each citation against the exact claim, then locate a useful source excerpt.
    excerpts: dict[int, str] = {}
    focus = focus_for(question)
    relevant = not focus
    exams = ap_requests(question)
    covered_exams = set()
    catalog_requirements = {(program, edition, kind)
                            for program, edition in catalog_scopes(question)
                            for kind in catalog_elective_types(question)}
    covered_catalog = set()
    for claim in evidence_sentences(text):
        markers = [int(n) for n in re.findall(r"\[(\d+)\]", claim)]
        if not markers and _LETTER.search(claim):
            return None
        bare = _MARKER.sub("", claim)
        if not markers or not _quote_key(bare):
            return None
        for n in markers:
            passage = passages[order[n-1]-1]
            excerpt = _matching_excerpt(bare, passage, bool(focus and focus.name == "withdrawal deadline"))
            if excerpt is None:
                return None
            excerpts.setdefault(n, excerpt)
            if focus and focus.supports(bare, passage.source_title + " " + passage.section_heading):
                relevant |= scope_matches(question, passage.source_title, passage.section_heading,
                                          default_full_term=True)
            covered_exams.update(exam for exam, score in exams.items() if ap_row_supports(bare, exam, score))
            covered_catalog.update((program, edition, kind) for program, edition, kind in catalog_requirements
                                   if catalog_title_matches(passage.source_title, program, edition)
                                   and catalog_elective_fact(bare, kind))
    if (not relevant or len(excerpts) != len(order) or set(exams) != covered_exams
            or catalog_requirements != covered_catalog):
        return None
    if needs_confirmation(text) and not _HAS_CONFIRM.search(text):
        text = f"{text} {CONFIRM_NOTE}"
    citations = [_citation(n, passages[original - 1], excerpts[n]) for n, original in enumerate(order, 1)]
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


def _fallback(system: str, user: str, passages: list[Passage], question: str) -> Answer:
    try:
        answer = finalize(ExtractiveLLM().complete(system, user), passages, question)
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
            return _fallback(system, user, selected, question)
        answer = finalize(raw, selected, question)
        if answer is None and not isinstance(provider, ExtractiveLLM):
            logger.warning("provider %s gave unusable output, falling back to extractive", provider.name)
            return _fallback(system, user, selected, question)
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


def _stream(question: str, passages: list[Passage], history: list[Turn] | None) -> Iterator[dict]:
    # Validate the complete candidate before any model text reaches the browser.
    answer = generate_answer(question, passages, history)
    yield from _tokens(answer.text)
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
