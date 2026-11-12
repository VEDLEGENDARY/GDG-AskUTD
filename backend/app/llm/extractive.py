"""No-LLM fallback: answer with the passage sentences that best match the question."""
from __future__ import annotations

import math
import re
from collections.abc import Iterator

from ..prompts import parse_user_prompt
from ..retrieval_support.focus import (DATE_FOCUSES, WITHDRAWAL_DATE, ap_requests, ap_row_supports,
                                       evidence_sentences, focus_for, scope_matches)
from ..retrieval_support.precision import (catalog_elective_fact, catalog_elective_types,
                                          catalog_scopes, catalog_title_matches)
from ..retrieval_support.query import private_reason

_STOP = frozenset(
    "a an the is are was were be been to of in on for and or with by at i my me do does did how what "
    "when where which who why can could should would will it its this that these those there their "
    "you your we our as from if about into than then so not no any some get "
    "ut utd dallas texas university student students".split())
_YEAR = re.compile(r"\b20\d\d\b")
_BOILERPLATE = re.compile(
    r"\b(?:follow these details|see policies|see details|for more information)\b"
    r"|^(?:click here|related pages|learn more|search:|login to intranet)\b", re.I)
_QUESTION_HEADING = re.compile(r"^(?:what|when|who|why|where|how|can|do|does|is|are)\b", re.I)
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


def extractive_answer(question: str, passages: list[str], headings: list[str] | None = None) -> str:
    """Return cited extracts when the supplied passages support the request."""
    wanted = terms(question)
    if not wanted or private_reason(question):
        return ""
    headings = headings if headings and len(headings) == len(passages) else [""] * len(passages)
    corpus = " ".join([*passages, *headings])
    if any(year not in corpus for year in _YEAR.findall(question)):
        return ""
    needed = max(1, min(3, math.ceil(len(wanted) * 0.5)))
    exams = ap_requests(question)
    if exams:
        extracts = []
        for exam, score in exams.items():
            match = next(((i, sentence) for i, passage in enumerate(passages, 1)
                          for sentence in evidence_sentences(passage)
                          if ap_row_supports(sentence, exam, score)), None)
            if match is None:
                return ""
            i, sentence = match
            extracts.append(_with_marker(sentence, i))
            if len(exams) == 1:
                options = next((part for part in evidence_sentences(passages[i-1])
                                if part.startswith("The equivalency options") or part.startswith("The options listed")), "")
                if options:
                    extracts.append(_with_marker(options, i))
        return " ".join(extracts)
    scopes, elective_types = catalog_scopes(question), catalog_elective_types(question)
    if scopes and elective_types:
        extracts = []
        for program, edition in scopes:
            for kind in elective_types:
                matches = [(i, sentence)
                           for i, (passage, heading) in enumerate(zip(passages, headings), 1)
                           if catalog_title_matches(heading.split(" | Section: ", 1)[0], program, edition)
                           for sentence in evidence_sentences(passage)
                           if catalog_elective_fact(sentence, kind)]
                match = max(matches, key=lambda item: "-".join(edition) in item[1], default=None)
                if match is None:
                    return ""
                i, sentence = match
                extracts.append(_with_marker(sentence, i))
        return " ".join(extracts)
    focus = focus_for(question)
    candidates = []
    passage_terms = [terms(text) for text in passages]
    document_frequency = {term: sum(term in vocabulary for vocabulary in passage_terms) for term in wanted}
    weights = {term: 1 + math.log((len(passages) + 1) / (frequency + 1))
               for term, frequency in document_frequency.items()}

    for p_index, text in enumerate(passages):
        rank_bonus = 0.3 * (1 - p_index / max(1, len(passages)))
        heading = headings[p_index]
        title, _, section = heading.partition(" | Section: ")
        for s_index, sentence in enumerate(evidence_sentences(text)):
            sentence = sentence.strip()
            if _BOILERPLATE.search(sentence) or (sentence.endswith("?") and _QUESTION_HEADING.search(sentence)):
                continue
            if focus:
                dated = focus.name in DATE_FOCUSES
                strictly_scoped = dated or focus.name == "complete withdrawal and six-drop limit"
                if not focus.supports(sentence, "" if strictly_scoped else heading):
                    continue
                if not scope_matches(question, title, section, default_full_term=True):
                    continue
                if focus.name == "withdrawal deadline" and (date := WITHDRAWAL_DATE.search(sentence)):
                    sentence = date[0]
                if focus.name == "course audit" and re.search(r"\bCS\s*\d{4}\b", question, re.I):
                    if not re.search(r"\bcomputer science\b.*\bcannot be audited\b", sentence, re.I):
                        continue
            words = sentence.split()
            if not _MIN_SENTENCE_WORDS <= len(words) <= _MAX_SENTENCE_WORDS:
                continue
            matching = wanted & terms(sentence)
            overlap = len(matching)
            if overlap >= needed or (focus and overlap):
                score = sum(weights[term] for term in matching) + rank_bonus
                candidates.append((score, overlap, p_index, s_index, sentence))
    if not candidates:
        return ""
    candidates.sort(key=lambda c: (-c[0], c[2], c[3]))
    best_overlap = candidates[0][1]
    chosen, seen, words_used = [], set(), 0
    limit = 1 if focus and focus.name in DATE_FOCUSES else _MAX_SENTENCES
    for _, overlap, p_index, s_index, sentence in candidates:
        if len(chosen) == limit or overlap < best_overlap * 0.5:
            break
        key = sentence.casefold()
        length = len(sentence.split())
        if key in seen or (chosen and words_used + length > _MAX_WORDS):
            continue
        seen.add(key)
        chosen.append((p_index, s_index, sentence))
        words_used += length
    return " ".join(_with_marker(sentence, p_index + 1) for p_index, _, sentence in chosen)


class ExtractiveLLM:
    """Provider that reads the numbered passages out of the user prompt. Never fails."""

    name = "extractive"

    def complete(self, system: str, user: str) -> str:
        """Return an extractive answer, or "" if no sentence matches."""
        question, passages = parse_user_prompt(user)
        block = user.partition("<passages>\n")[2].partition("\n</passages>")[0]
        headings = re.findall(r"^\[\d+\] Title: (.*)$", block, re.M)
        return extractive_answer(question, passages, headings)

    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield the extractive answer a few words at a time."""
        words = re.findall(r"\S+\s*", self.complete(system, user))
        for start in range(0, len(words), 4):
            yield "".join(words[start:start + 4])
