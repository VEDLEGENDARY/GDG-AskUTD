#!/usr/bin/env python3
"""Corpus audit and cleanup proposals (mentee 2). Never edits the source corpus.

Subcommands:
    audit     count corpus issues and list representative chunk ids
    propose   build per-rule edit proposals; dry run unless --write
    evaluate  score a staged corpus against the source with the production pipeline
    ablate    evaluate safe-only and per-rule variants in memory

Rule tiers:
    safe       character-level normalization; every word survives; staged by default
    review     furniture or heading edits with stable ids; staged only with --accept
    migration  merges, splits and retired ids; written as a proposal, never applied
    flag       reported for a human; no edit is proposed

Everything is written under evaluate/runs/mentee-2/. Output paths inside the source
corpus, or paths that resolve (through symlinks) onto an input, are refused.

Usage:
    python scripts/mentee2_corpus.py audit [--json evaluate/runs/mentee-2/audit.json]
    python scripts/mentee2_corpus.py propose [--accept R1,R2] [--write --out evaluate/runs/mentee-2/stage]
    python scripts/mentee2_corpus.py evaluate --staged evaluate/runs/mentee-2/stage --split dev
    python scripts/mentee2_corpus.py ablate --split dev [--json evaluate/runs/mentee-2/ablation-dev.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from audit_corpus import letter_spaced, navigation_like  # noqa: E402
from evaluate import evaluate_chunks as ev  # noqa: E402
from fill_chunk_counts import FIELDS, count_sentences  # noqa: E402
from fix_chunks import _FOOTER_PHRASES, CHROME_HEADINGS, FOOTER_MARKER  # noqa: E402

DATA_DIR = ROOT / "backend" / "data"
CHUNKS_DIR = DATA_DIR / "chunks"
RAW_TEXT_DIR = DATA_DIR / "raw_text"
REGISTRY = DATA_DIR / "documents.json"
QUESTIONS = ROOT / "evaluate" / "questions.json"
CONFIG = ROOT / "backend" / "retrieval_config.json"
RUNS_ROOT = ROOT / "evaluate" / "runs" / "mentee-2"
FIXTURES = ROOT / "evaluate" / "mentee2"
MANIFEST = "manifest.json"
TOOL = "mentee2_corpus"

SHORT_WORDS = 15
OVERSIZED_WORDS = 250
NEAR_DUPLICATE = 0.8
COMMON_SHINGLE = 50
SAMPLE = 5


@dataclass(frozen=True)
class Rule:
    rule_id: str
    tier: str
    summary: str


RULES = {r.rule_id: r for r in (
    Rule("S1", "safe", "Unicode NFC normalization"),
    Rule("S2", "safe", "remove zero-width, soft hyphen, BOM and control characters; non-breaking spaces become spaces"),
    Rule("S3", "safe", "collapse runs of spaces or tabs and trim the ends; line breaks are kept"),
    Rule("S4", "safe", "repair UTF-8 read as cp1252 (a stray 'A-circumflex' before a space, smart quotes, dashes)"),
    Rule("S5", "safe", "add the missing space in 'word.Word' joins; emails, URLs and abbreviations are skipped"),
    Rule("R1", "review", "remove a site breadcrumb trail 'UT Dallas > A > B > ' and keep the page name after it"),
    Rule("R2", "review", "remove a footer run that contains a footer marker (privacy policy, copyright, Related Pages)"),
    Rule("R3", "review", "remove a browser print stamp 'N of M MM/DD/YYYY H:MM PM'; the printed URL is kept"),
    Rule("R4", "review", "replace a footer-menu section heading with the generic 'Overview' (never a guessed heading)"),
    Rule("R5", "review", "move a heading glued to the end of a chunk onto the next chunk; must be its own raw_text line"),
    Rule("M1", "migration", "retire a chunk that contains nothing but footer or menu furniture"),
    Rule("M2", "migration", "retire a later exact duplicate with the same doc and heading; the first copy stays"),
    Rule("M3", "migration", "merge a chunk that ends mid-sentence with the next chunk that continues it"),
    Rule("M4", "migration", "merge a chunk the index filters out (outside min/max chunk words) into a neighbour"),
    Rule("M5", "migration", "split an oversized chunk at a sentence boundary that keeps exceptions with their rule"),
    Rule("F1", "flag", "letter-spaced extraction ('P o l i c y'); needs re-extraction from the source PDF"),
    Rule("F2", "flag", "exact duplicate text across docs or under different headings; every copy is kept"),
    Rule("F3", "flag", "near-duplicate pair; 'variant' when numbers, negations or conditions differ"),
    Rule("F4", "flag", "time-scoped text (term or catalog year); check freshness, never rewrite the year"),
    Rule("F5", "flag", "document belongs to a family of versions with different catalog years"),
    Rule("F6", "flag", "short chunk; kept because it may hold the only answer"),
    Rule("F7", "flag", "missing or generic metadata (no source URL or PDF, generic heading)"),
    Rule("F8", "flag", "table structure risk (column-header heading, table split across chunks)"),
    Rule("F9", "flag", "chunk boundary falls mid-sentence"),
)}
SAFE_RULES = [r for r, rule in RULES.items() if rule.tier == "safe"]
REVIEW_RULES = [r for r, rule in RULES.items() if rule.tier == "review"]

# ---------------------------------------------------------------- content guards

MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
PROTECTED = {
    "numbers": re.compile(r"\d+(?:[.,:/]\d+)*"),
    "money": re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?"),
    "percent": re.compile(r"\d+(?:\.\d+)?\s?%|\bpercent\b", re.I),
    "dates": re.compile(rf"\b{MONTH}\.? \d{{1,2}}\b|\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b|\b(?:19|20)\d{{2}}\b"),
    "negations": re.compile(r"\b(?:not|no|never|cannot|nor|neither|none|without)\b|n[\u2019']t\b", re.I),
    "conditions": re.compile(r"\b(?:except|exceptions?|unless|only|if|must|required?|prior|before|after|until"
                             r"|exempt(?:ion)?s?|waived?|eligible|ineligible|eligibility)\b", re.I),
}
MOJIBAKE_CHARS = "\u00c2\u00e2"


def words(text: str) -> list[str]:
    """Case-folded word tokens (NFKC) used for order and signature checks."""
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def signature(text: str) -> list[str]:
    """Word sequence with mojibake lead bytes removed; safe rules must keep it equal."""
    cleaned = [w.translate({ord(c): None for c in MOJIBAKE_CHARS}) for w in words(text)]
    return [w for w in cleaned if w]


def is_subsequence(small: list[str], big: list[str]) -> bool:
    """True when ``small`` appears in ``big`` in the same order (deletions only)."""
    stream = iter(big)
    return all(token in stream for token in small)


def content_guard(before: str, after: str) -> dict:
    """Protected facts removed or added by an edit, and whether word order survived."""
    report: dict = {}
    for name, pattern in PROTECTED.items():
        old, new = Counter(m.group(0).lower() for m in pattern.finditer(before)), Counter(
            m.group(0).lower() for m in pattern.finditer(after))
        if old - new:
            report[f"{name}_removed"] = sorted((old - new).elements())
        if new - old:
            report[f"{name}_added"] = sorted((new - old).elements())
    report["order_preserved"] = is_subsequence(words(after), words(before)) or signature(after) == signature(before)
    report["signature_equal"] = signature(after) == signature(before)
    return report


def guard_clean(report: dict) -> bool:
    """No protected fact removed or added and no reordering."""
    return report["order_preserved"] and not any(k.endswith(("_removed", "_added")) for k in report)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def corpus_hash(chunks: list[dict]) -> str:
    """Same fingerprint as evaluate_chunks reports (sorted-key JSON of the chunk list)."""
    return hashlib.sha256(json.dumps(chunks, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---------------------------------------------------------------- evidence labels

@dataclass(frozen=True)
class Group:
    """One evidence group of one benchmark question (read-only label)."""
    key: str
    split: str
    docs: tuple[str, ...]
    evidence: dict


def load_groups(path: Path = QUESTIONS) -> list[Group]:
    """All evidence groups from every split. Used only as a do-not-lose guard, never for tuning."""
    if not path.exists():
        return []
    groups = []
    for q in ev.read_json(path, comments=True):
        for i, e in enumerate(q.get("evidence", [])):
            groups.append(Group(f"{q['id']}#{i}", q.get("split", ""), tuple(e.get("doc_ids", [e.get("doc_id")])), e))
    return groups


class EvidenceIndex:
    """Which evidence groups each (doc, text) supports."""

    def __init__(self, groups: list[Group]):
        self.groups = groups
        self.by_doc: dict[str, list[Group]] = defaultdict(list)
        for g in groups:
            for d in g.docs:
                self.by_doc[d].append(g)

    def supported(self, doc_id: str, text: str) -> set[str]:
        row = {"doc_id": doc_id, "text": text}
        return {g.key for g in self.by_doc.get(doc_id, []) if ev.supports(row, g.evidence)}

    def corpus_support(self, chunks: list[dict]) -> dict[str, set[str]]:
        """Group key to the chunk ids that support it."""
        support: dict[str, set[str]] = {g.key: set() for g in self.groups}
        for c in chunks:
            for key in self.supported(c["doc_id"], c["text"]):
                support[key].add(c["chunk_id"])
        return support


# ---------------------------------------------------------------- span helpers

Span = tuple[int, int, str]


def apply_spans(text: str, spans: list[Span]) -> str:
    """Replace non-overlapping (start, end, replacement) spans."""
    out, pos = [], 0
    for start, end, replacement in sorted(spans):
        if start < pos:
            raise ValueError("overlapping spans")
        out += [text[pos:start], replacement]
        pos = end
    return "".join(out + [text[pos:]])


def regex_spans(pattern: re.Pattern, text: str, replacement="") -> list[Span]:
    return [(m.start(), m.end(), replacement(m) if callable(replacement) else replacement)
            for m in pattern.finditer(text)]


def absorb_space(text: str, spans: list[Span]) -> list[Span]:
    """Widen pure deletions so the text keeps exactly one space where a span was removed."""
    widened = []
    for start, end, replacement in spans:
        if replacement:
            widened.append((start, end, replacement))
            continue
        while end < len(text) and text[end] in " \t":
            end += 1
        if start == 0 or end == len(text):
            while start > 0 and text[start - 1] in " \t":
                start -= 1
        elif start > 0 and text[start - 1] not in " \t":
            widened.append((start, end, " "))
            continue
        widened.append((start, end, ""))
    return widened


# ---------------------------------------------------------------- safe rules

INVISIBLE = re.compile(r"[\u00ad\u200b-\u200d\u2060\ufeff\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]")
ODD_SPACE = re.compile(r"[\u00a0\u2007\u202f]")
SPACE_RUN = re.compile(r"[ \t]{2,}|\t")
EDGE_SPACE = re.compile(r"^[ \t]+|[ \t]+$")
_MOJIBAKE = {}
for _target in "\u2019\u2018\u201c\u2013\u2014\u2022\u00e9\u00e8\u00f1\u00fc\u00a9\u00ae\u00b0":
    try:
        _MOJIBAKE[_target.encode("utf-8").decode("cp1252")] = _target
    except UnicodeDecodeError:
        continue
MOJIBAKE = re.compile("|".join(map(re.escape, sorted(_MOJIBAKE, key=len, reverse=True))))
STRAY_A_CIRCUMFLEX = re.compile(r"(?<![^\W\d_])\u00c2(?=[ \u00a0])")
GLUED = re.compile(r"(?<![\w.@/:,$])([A-Za-z][a-z]+|\d{1,4})\.([A-Z][a-z]+)(?![\w.@/])")


def s1(text: str) -> list[Span]:
    normal = unicodedata.normalize("NFC", text)
    return [(0, len(text), normal)] if normal != text else []


def s2(text: str) -> list[Span]:
    return regex_spans(INVISIBLE, text) + regex_spans(ODD_SPACE, text, " ")


def s3(text: str) -> list[Span]:
    edges = regex_spans(EDGE_SPACE, text)
    inner = [(a, b, " ") for a, b, _ in regex_spans(SPACE_RUN, text)
             if not any(a < y and x < b for x, y, _ in edges)]
    return sorted(edges + inner)


def s4(text: str) -> list[Span]:
    spans = regex_spans(MOJIBAKE, text, lambda m: _MOJIBAKE[m.group(0)])
    taken = [(a, b) for a, b, _ in spans]
    return sorted(spans + [s for s in regex_spans(STRAY_A_CIRCUMFLEX, text)
                           if not any(a <= s[0] < b for a, b in taken)])


def s5(text: str) -> list[Span]:
    return [(m.end(1) + 1, m.end(1) + 1, " ") for m in GLUED.finditer(text)]


# ---------------------------------------------------------------- review rules

BREADCRUMB_ROOT = re.compile(r"(?:(?<=\s)|^)(?:UT Dallas|The University of Texas at Dallas|Harry W\. Bass Jr\.)(?= >)")
BREADCRUMB_SEP = re.compile(r" >(?: >)* ")
BREADCRUMB_SEGMENT = re.compile(r"[^>.!?]{1,80}?(?= >)")
_EXTRA_FURNITURE = [r"COPYRIGHT INFORMATION\.?", r"Copyright", r"VISIT", r"GIVING", r"APPLY"]
FURNITURE_PHRASE = "|".join(_FOOTER_PHRASES + _EXTRA_FURNITURE)
FOOTER_RUN = re.compile(r"(?:(?:%s)[\s.]*)+" % FURNITURE_PHRASE)
FURNITURE_ONLY = re.compile(r"^\s*(?:(?:%s)[\s.,]*)+$" % FURNITURE_PHRASE)
PRINT_STAMP = re.compile(r"\b\d{1,3} of \d{1,3} \d{1,2}/\d{1,2}/\d{4},? \d{1,2}:\d{2} ?[AP]M\b")
HEADING_WORD = r"(?:[A-Z][\w\u2019'/&-]*|(?:19|20)\d{2}|of|and|the|for|to|a|an|in|on|or|your|with|at|by)"
TRAILING_HEADING = re.compile(rf"(?<=[.!?:])\s+({HEADING_WORD}(?:\s+{HEADING_WORD}){{1,9}})$")
GENERIC_HEADINGS = {"Overview", ""}


def r1(text: str) -> list[Span]:
    spans = []
    for root in BREADCRUMB_ROOT.finditer(text):
        pos, last = root.end(), None
        while (sep := BREADCRUMB_SEP.match(text, pos)) is not None:
            last = sep.end()
            segment = BREADCRUMB_SEGMENT.match(text, last)
            if segment is None:
                break
            pos = segment.end()
        if last is not None:
            spans.append((root.start(), last, ""))
    return absorb_space(text, spans)


def furniture_only(text: str) -> bool:
    """The whole chunk is footer or menu furniture."""
    return bool(FURNITURE_ONLY.match(text))


def r2(text: str) -> list[Span]:
    if furniture_only(text):
        return []
    spans = [(m.start(), m.end(), "") for m in FOOTER_RUN.finditer(text)
             if FOOTER_MARKER.search(m.group(0)) and m.group(0).strip()]
    return absorb_space(text, spans)


def r3(text: str) -> list[Span]:
    return absorb_space(text, regex_spans(PRINT_STAMP, text))


def chrome_heading(heading: str) -> bool:
    """Site chrome, or a heading made only of footer phrases that includes a footer marker or 3+ phrases.

    A lone phrase such as 'Contact Us' or 'Forms' is a real heading on many pages and is kept.
    """
    heading = heading.strip()
    if heading in CHROME_HEADINGS:
        return True
    if not heading or not FURNITURE_ONLY.match(heading):
        return False
    return bool(FOOTER_MARKER.search(heading)) or len(re.findall(FURNITURE_PHRASE, heading)) >= 3


def read_raw_lines(directory: Path = RAW_TEXT_DIR) -> dict[str, list[str]]:
    """Whitespace-normalized lines of each raw_text/docNNN.txt in order (read-only); headings are whole lines."""
    lines: dict[str, list[str]] = {}
    for path in sorted(directory.glob("doc*.txt")) if directory.is_dir() else []:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines[path.stem] = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    return lines


def trailing_heading(text: str) -> re.Match | None:
    """A Title Case heading glued after the last sentence of a chunk."""
    m = TRAILING_HEADING.search(text)
    if not m:
        return None
    tokens = m.group(1).split()
    capitals = sum(t[0].isupper() for t in tokens)
    # Four-digit years are allowed ('Graduate Applications for Fall 2025'); other digits suggest a table row.
    if re.search(r"\d", YEAR.sub("", m.group(1))) or capitals < 2 or capitals / len(tokens) < 0.6 or not (tokens[-1][0].isupper() or YEAR.fullmatch(tokens[-1])):
        return None
    return m


TEXT_RULES = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "R1": r1, "R2": r2, "R3": r3}


# ---------------------------------------------------------------- proposal engine

def doc_order(chunks: list[dict]) -> dict[str, list[int]]:
    order: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(chunks):
        order[c["doc_id"]].append(i)
    return order


def edit_record(before: str, spans: list[Span]) -> list[dict]:
    return [{"start": a, "end": b, "removed": before[a:b], "inserted": r} for a, b, r in sorted(spans)]


class Proposer:
    """Run every rule over a corpus copy; apply safe rules and accepted review rules only."""

    def __init__(self, chunks: list[dict], groups: list[Group], accept: set[str] | None = None,
                 index_limits: tuple[int, int] = (3, 300), registry: list[dict] | None = None,
                 raw_lines: dict[str, list[str]] | None = None, skip: set[str] | None = None):
        unknown = (accept or set()) - set(REVIEW_RULES)
        if unknown:
            raise ValueError(f"only review rules can be accepted, not {sorted(unknown)}")
        bad = [k for k in skip or () if not re.fullmatch(r"R\d:doc\d{3}_p\d+_c\d+", k)]
        if bad:
            raise ValueError(f"--skip entries look like R5:doc178_p1_c1, not {bad}")
        self.source = chunks
        self.chunks = [dict(c) for c in chunks]
        self.accept = set(accept or ())
        self.skip = set(skip or ())  # 'RULE:chunk_id' proposals a reviewer rejected
        self.evidence = EvidenceIndex(groups)
        self.min_words, self.max_words = index_limits
        self.registry = registry or []
        self.raw_lines = raw_lines or {}
        self.proposals: list[dict] = []
        self.migrations: list[dict] = []
        self.flags: list[dict] = []

    # -- helpers
    def _status(self, rule: Rule, guard: dict, lost: set[str]) -> str:
        if lost:
            return "blocked"
        if rule.tier == "safe":
            return "auto" if guard["signature_equal"] and guard_clean(guard) else "blocked"
        return "needs_review"

    def _applied(self, rule: Rule, status: str, chunk_id: str) -> bool:
        if f"{rule.rule_id}:{chunk_id}" in self.skip:
            return False
        return status == "auto" or (rule.rule_id in self.accept and status == "needs_review")

    def _text_edit(self, rule: Rule, chunk: dict, spans: list[Span], field: str = "text", note: str = "",
                   extra: dict | None = None) -> dict:
        before = chunk[field]
        after = apply_spans(before, spans)
        guard = content_guard(before, after) if field == "text" else {"order_preserved": True, "signature_equal": True}
        lost = set()
        if field == "text":
            lost = self.evidence.supported(chunk["doc_id"], before) - self.evidence.supported(chunk["doc_id"], after)
            if not after.strip():
                lost.add("<empty text>")
        status = self._status(rule, guard, lost)
        proposal = {"rule": rule.rule_id, "tier": rule.tier, "doc_id": chunk["doc_id"], "chunk_id": chunk["chunk_id"],
                    "field": field, "before_sha256": sha(before), "after_sha256": sha(after),
                    "edits": edit_record(before, spans), "guard": guard, "evidence_lost": sorted(lost),
                    "status": status}
        if note:
            proposal["note"] = note
        if extra:
            proposal.update(extra)
        proposal["applied"] = self._applied(rule, status, chunk["chunk_id"])
        if proposal["applied"]:
            chunk[field] = after
        self.proposals.append(proposal)
        return proposal

    # -- passes
    def run(self) -> "Proposer":
        for chunk in self.chunks:
            for rule_id, fn in TEXT_RULES.items():
                spans = fn(chunk["text"])
                if spans:
                    note = self._r1_note(chunk, spans) if rule_id == "R1" else ""
                    self._text_edit(RULES[rule_id], chunk, spans, note=note)
        self._chrome_headings()
        self._trailing_headings()
        self._migrations()
        self._flags()
        return self

    def _r1_note(self, chunk: dict, spans: list[Span]) -> str:
        removed = set(ev.tokens(" ".join(chunk["text"][a:b] for a, b, _ in spans)))
        kept = set(ev.tokens(ev.metadata(chunk) + " " + apply_spans(chunk["text"], spans)))
        missing = sorted(removed - kept - {"ut", "dallas"})
        return f"context words not kept in title, heading or text: {', '.join(missing)}" if missing else ""

    def _chrome_headings(self) -> None:
        # The previous heading is not inherited: it can belong to another section (a course row, say),
        # which would attach the wrong context. 'Overview' carries no false context.
        rule = RULES["R4"]
        for chunk in self.chunks:
            heading = chunk["section_heading"]
            if chrome_heading(heading) and not furniture_only(chunk["text"]) and heading != "Overview":
                self._text_edit(rule, chunk, [(0, len(heading), "Overview")], field="section_heading",
                                note="heading was footer furniture")

    def _trailing_headings(self) -> None:
        rule = RULES["R5"]
        for indices in doc_order(self.chunks).values():
            for i, j in zip(indices, indices[1:]):
                chunk, following = self.chunks[i], self.chunks[j]
                m = trailing_heading(chunk["text"])
                if not m or len(COURSE.findall(chunk["text"])) >= 3:
                    continue  # table rows look like Title Case phrases; tables are flagged (F8), not edited
                ordered = self.raw_lines.get(chunk["doc_id"], [])
                lines, adjacent = set(ordered), set(zip(ordered, ordered[1:]))
                heading, current = " ".join(m.group(1).split()), following["section_heading"]
                if heading not in lines or heading.isupper():
                    continue  # not a standalone source line (or an all-caps menu), so not provably a heading
                if current not in GENERIC_HEADINGS | {chunk["section_heading"]}:
                    if current not in lines or re.search(r"\d", current):
                        continue
                    # A heading wrapped over two source lines is rejoined; otherwise parent and sub-heading.
                    heading = f"{heading} {current}" if (heading, current) in adjacent else f"{heading}: {current}"
                text_spans = [(m.start(), m.end(), "")]
                after = apply_spans(chunk["text"], text_spans)
                lost = (self.evidence.supported(chunk["doc_id"], chunk["text"])
                        - self.evidence.supported(chunk["doc_id"], after))
                status = "blocked" if lost or not after.strip() else "needs_review"
                proposal = {"rule": "R5", "tier": rule.tier, "doc_id": chunk["doc_id"], "chunk_id": chunk["chunk_id"],
                            "field": "text+next.section_heading", "next_chunk_id": following["chunk_id"],
                            "before_sha256": sha(chunk["text"]), "after_sha256": sha(after),
                            "edits": edit_record(chunk["text"], text_spans),
                            "heading_change": {"chunk_id": following["chunk_id"],
                                               "from": following["section_heading"], "to": heading},
                            "guard": content_guard(chunk["text"], after), "evidence_lost": sorted(lost),
                            "status": status, "note": "heading text moves to the chunk it introduces; no words leave the doc"}
                proposal["applied"] = self._applied(rule, status, chunk["chunk_id"])
                if proposal["applied"]:
                    chunk["text"] = after
                    following["section_heading"] = heading
                self.proposals.append(proposal)

    def _migrations(self) -> None:
        chunks = self.chunks
        order = doc_order(chunks)
        support = self.evidence.corpus_support(chunks)
        next_c = {d: max(int(re.search(r"_c(\d+)$", chunks[i]["chunk_id"]).group(1)) for i in idx)
                  for d, idx in order.items() if all(re.search(r"_c(\d+)$", chunks[i]["chunk_id"]) for i in idx)}
        retired: set[str] = set()

        def retire(rule_id: str, chunk: dict, into: str | None, reason: str) -> None:
            # Evidence floor: a group may lose this chunk only if another surviving chunk still supports it.
            at_risk = sorted(k for k in self.evidence.supported(chunk["doc_id"], chunk["text"])
                             if not (support[k] - retired - {chunk["chunk_id"]}))
            status = "blocked" if at_risk else "proposal_only"
            if status != "blocked":
                retired.add(chunk["chunk_id"])
            self.migrations.append({"rule": rule_id, "doc_id": chunk["doc_id"], "old_ids": [chunk["chunk_id"]],
                                    "new_ids": [into] if into else [], "mapping": {chunk["chunk_id"]: into},
                                    "text_sha256": sha(chunk["text"]), "reason": reason,
                                    "evidence_only_copy": at_risk, "status": status})

        for doc_id, indices in order.items():
            seen: dict[tuple[str, str], str] = {}
            for i in indices:
                c = chunks[i]
                if furniture_only(c["text"]):
                    retire("M1", c, None, "chunk is footer or menu furniture only: " + c["text"][:80])
                    continue
                key = (ev.normalize(c["text"]), c["section_heading"])
                if key in seen:
                    retire("M2", c, seen[key], f"exact duplicate of {seen[key]} under the same heading")
                else:
                    seen[key] = c["chunk_id"]

            for i, j in zip(indices, indices[1:]):
                a, b = chunks[i], chunks[j]
                if {a["chunk_id"], b["chunk_id"]} & retired:
                    continue
                broken = not re.search(r"[.!?:;)\]\"\u201d\u2019]\s*$", a["text"]) and re.match(r"[a-z]", b["text"])
                if broken and a["section_heading"] == b["section_heading"]:
                    self._merge("M3", a, b, "a ends mid-sentence and b continues it")
            for pos, i in enumerate(indices):
                c = chunks[i]
                n = len(c["text"].split())
                if c["chunk_id"] in retired or self.min_words <= n <= self.max_words:
                    continue
                if n < self.min_words and len(indices) > 1:
                    neighbour = chunks[indices[pos - 1]] if pos else chunks[indices[pos + 1]]
                    a, b = (neighbour, c) if pos else (c, neighbour)
                    self._merge("M4", a, b, f"{c['chunk_id']} has {n} words; the index drops chunks under "
                                f"{self.min_words} words, so its text is never searchable")
            for i in indices:
                c = chunks[i]
                if len(c["text"].split()) > OVERSIZED_WORDS and doc_id in next_c:
                    next_c[doc_id] += 1
                    self._split(c, re.sub(r"_c\d+$", f"_c{next_c[doc_id]}", c["chunk_id"]))

    def _merge(self, rule_id: str, a: dict, b: dict, reason: str) -> None:
        merged = a["text"].rstrip() + " " + b["text"].lstrip()
        n = len(merged.split())
        gained = sorted(self.evidence.supported(a["doc_id"], merged)
                        - self.evidence.supported(a["doc_id"], a["text"]) - self.evidence.supported(b["doc_id"], b["text"]))
        self.migrations.append({"rule": rule_id, "doc_id": a["doc_id"], "old_ids": [a["chunk_id"], b["chunk_id"]],
                                "new_ids": [a["chunk_id"]], "mapping": {a["chunk_id"]: a["chunk_id"], b["chunk_id"]: a["chunk_id"]},
                                "merged_words": n, "merged_sha256": sha(merged), "evidence_gained": gained,
                                "reason": reason,
                                "status": "proposal_only" if n <= self.max_words else "blocked",
                                **({"blocked_reason": f"merged chunk has {n} words, over {self.max_words}"} if n > self.max_words else {})})

    def _split(self, chunk: dict, new_id: str) -> None:
        text = chunk["text"]
        cuts = [m.end() for m in SENTENCE_BOUNDARY.finditer(text)]
        good = [p for p in cuts if not EXCEPTION_CUE.match(text, p) and not text[:p].rstrip().endswith(":")
                and min(len(text[:p].split()), len(text[p:].split())) >= SHORT_WORDS]
        record = {"rule": "M5", "doc_id": chunk["doc_id"], "old_ids": [chunk["chunk_id"]],
                  "words": len(text.split()), "reason": f"over {OVERSIZED_WORDS} words"}
        if not good:
            self.migrations.append({**record, "new_ids": [chunk["chunk_id"]], "mapping": {chunk["chunk_id"]: chunk["chunk_id"]},
                                    "status": "blocked", "blocked_reason": "no sentence boundary keeps exceptions with their rule"})
            return
        middle = len(text) / 2
        cut = min(good, key=lambda p: (abs(p - middle), p))
        left, right = text[:cut].rstrip(), text[cut:].lstrip()
        before = self.evidence.supported(chunk["doc_id"], text)
        after = self.evidence.supported(chunk["doc_id"], left) | self.evidence.supported(chunk["doc_id"], right)
        self.migrations.append({**record, "new_ids": [chunk["chunk_id"], new_id],
                                "mapping": {chunk["chunk_id"]: [chunk["chunk_id"], new_id]},
                                "split_at": cut, "left_words": len(left.split()), "right_words": len(right.split()),
                                "right_starts": right[:80], "evidence_lost": sorted(before - after),
                                "status": "blocked" if before - after else "proposal_only"})

    def _flags(self) -> None:
        self.flags = audit_flags(self.source, self.registry, (self.min_words, self.max_words))

    # -- results
    def summary(self) -> dict:
        by_rule: dict[str, Counter] = defaultdict(Counter)
        for p in self.proposals:
            by_rule[p["rule"]][p["status"]] += 1
            by_rule[p["rule"]]["applied" if p["applied"] else "not_applied"] += 1
        for m in self.migrations:
            by_rule[m["rule"]][m["status"]] += 1
        for f in self.flags:
            by_rule[f["rule"]]["flagged"] += 1
        return {r: dict(sorted(by_rule[r].items())) for r in RULES if r in by_rule}


SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])(?<!\b[A-Z]\.)\s+(?=[A-Z\"'(])")
EXCEPTION_CUE = re.compile(r"(?:However|Except|Exceptions?|Unless|Otherwise|This (?:does not|exception|rule does)"
                           r"|These (?:exceptions|rules)|In addition|Additionally|Note|Students who (?:are|have) exempt)\b")


# ---------------------------------------------------------------- flags and audit

TIME_SCOPE = re.compile(r"\b(?:Fall|Spring|Summer|Winter) (?:19|20)\d{2}\b|\b(?:19|20)\d{2}\s?[-\u2013]\s?(?:19|20)?\d{2}\b")
COURSE = re.compile(r"\b[A-Z]{2,4} \d{4}\b")
COLUMN_HEADING = re.compile(r"^(?:Description Course No|Course No\.? Description|Pre-Requisite Course|Course|Hours|Credit Hours)$", re.I)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def shingles(text: str, size: int = 5) -> set[str]:
    tokens = ev.normalize(text).split()
    return {" ".join(tokens[i:i + size]) for i in range(max(1, len(tokens) - size + 1))}


def table_like(text: str) -> bool:
    return len(COURSE.findall(text)) >= 3 and len(re.findall(r"[.!?](\s|$)", text)) <= len(COURSE.findall(text)) / 2


def near_duplicates(chunks: list[dict]) -> list[dict]:
    """Pairs with shingle Jaccard in [NEAR_DUPLICATE, 1); 'variant' when protected facts differ."""
    sets = [shingles(c["text"]) for c in chunks]
    postings: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(sets):
        for sh in s:
            postings[sh].append(i)
    candidates: set[tuple[int, int]] = set()
    for ids in postings.values():
        if 1 < len(ids) <= COMMON_SHINGLE:
            candidates.update((a, b) for x, a in enumerate(ids) for b in ids[x + 1:])
    pairs = []
    for a, b in sorted(candidates):
        union = sets[a] | sets[b]
        score = len(sets[a] & sets[b]) / len(union) if union else 0
        if NEAR_DUPLICATE <= score < 1 and ev.normalize(chunks[a]["text"]) != ev.normalize(chunks[b]["text"]):
            left, right = Counter(words(chunks[a]["text"])), Counter(words(chunks[b]["text"]))
            differing = sorted((left - right) + (right - left))
            protected = [w for w in differing if re.fullmatch(r"\d+", w)
                         or PROTECTED["negations"].fullmatch(w) or PROTECTED["conditions"].fullmatch(w)]
            pairs.append({"chunk_ids": [chunks[a]["chunk_id"], chunks[b]["chunk_id"]], "jaccard": round(score, 3),
                          "kind": "variant" if protected else "near_identical",
                          "differing_words": differing[:12], "protected_differences": protected[:12]})
    return pairs


def version_families(registry: list[dict]) -> list[dict]:
    families: dict[str, list[tuple[str, list[int]]]] = defaultdict(list)
    for row in registry:
        years = [int(y) for y in YEAR.findall(row.get("title", ""))]
        if not years:
            continue
        key = re.sub(r"\(?\b(?:19|20)\d{2}(?:\s*[-\u2013]\s*(?:19|20)?\d{2})?\b\)?|\bcatalog\b", "", row["title"], flags=re.I)
        families[re.sub(r"[^a-z]+", " ", key.lower()).strip()].append((row["doc_id"], years))
    out = []
    for key, members in sorted(families.items()):
        if len({max(y) for _, y in members}) < 2:
            continue
        newest = max(max(y) for _, y in members)
        for doc_id, years in sorted(members):
            out.append({"rule": "F5", "doc_id": doc_id, "family": key, "years": years,
                        "newest_in_family": newest, "older_version": max(years) < newest})
    return out


def audit_flags(chunks: list[dict], registry: list[dict], limits: tuple[int, int]) -> list[dict]:
    """Every flag-tier finding. No edits are proposed for flags."""
    flags: list[dict] = []
    clusters: dict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        clusters[ev.normalize(c["text"])].append(c)
    order = doc_order(chunks)
    for c in chunks:
        n = len(c["text"].split())
        if letter_spaced(c["text"]) or re.search(r"(?:\b\w ){6,}\w\b", c["text"]):
            flags.append({"rule": "F1", "chunk_id": c["chunk_id"], "detail": "letter-spaced run"})
        years = sorted(set(m.group(0) for m in TIME_SCOPE.finditer(c["text"])))
        if years:
            flags.append({"rule": "F4", "chunk_id": c["chunk_id"], "detail": ", ".join(years[:6])})
        if n < SHORT_WORDS:
            flags.append({"rule": "F6", "chunk_id": c["chunk_id"], "detail": f"{n} words"
                          + ("; dropped by the index min_chunk_words" if n < limits[0] else "")})
        if c["section_heading"] in GENERIC_HEADINGS:
            flags.append({"rule": "F7", "chunk_id": c["chunk_id"], "detail": "generic heading 'Overview'"})
        if COLUMN_HEADING.match(c["section_heading"].strip()):
            flags.append({"rule": "F8", "chunk_id": c["chunk_id"], "detail": f"column header as heading: {c['section_heading']!r}"})
    for cluster in clusters.values():
        if len(cluster) < 2:
            continue
        if len({c["doc_id"] for c in cluster}) > 1:
            flags.append({"rule": "F2", "chunk_id": cluster[0]["chunk_id"], "detail": "cross_doc",
                          "copies": [c["chunk_id"] for c in cluster]})
        per_doc: dict[str, list[dict]] = defaultdict(list)
        for c in cluster:
            per_doc[c["doc_id"]].append(c)
        for copies in per_doc.values():
            if len({c["section_heading"] for c in copies}) > 1:
                flags.append({"rule": "F2", "chunk_id": copies[0]["chunk_id"], "detail": "same_doc_different_heading",
                              "copies": [c["chunk_id"] for c in copies]})
    for pair in near_duplicates(chunks):
        flags.append({"rule": "F3", "chunk_id": pair["chunk_ids"][0], "detail": pair["kind"], **pair})
    flags += version_families(registry)
    for row in registry:
        missing = [k for k in ("source_url", "pdf") if not row.get(k)]
        if missing:
            flags.append({"rule": "F7", "doc_id": row["doc_id"], "detail": "registry missing " + ", ".join(missing)})
    for indices in order.values():
        for i, j in zip(indices, indices[1:]):
            a, b = chunks[i], chunks[j]
            ends_open = not re.search(r"[.!?:;)\]\"\u201d\u2019]\s*$", a["text"])
            if ends_open and re.match(r"[a-z]", b["text"]):
                flags.append({"rule": "F9", "chunk_id": a["chunk_id"], "detail": f"continues in {b['chunk_id']}"})
            if ends_open and table_like(a["text"]) and table_like(b["text"]):
                flags.append({"rule": "F8", "chunk_id": a["chunk_id"], "detail": f"table continues in {b['chunk_id']}"})
    return sorted(flags, key=lambda f: (f["rule"], f.get("chunk_id") or f.get("doc_id", "")))


def audit_report(chunks: list[dict], registry: list[dict], limits: tuple[int, int]) -> dict:
    """Counts with representative ids for every issue class, plus the proposal counts."""
    proposer = Proposer(chunks, load_groups(), index_limits=limits, registry=registry, raw_lines=read_raw_lines()).run()
    issues: dict[str, list[str]] = defaultdict(list)
    for c in chunks:
        if navigation_like(c["text"]):
            issues["navigation_like"].append(c["chunk_id"])
        if len(c["text"].split()) > OVERSIZED_WORDS:
            issues["oversized"].append(c["chunk_id"])
        if not c.get("source_title", "").strip() or not c.get("section_heading", "").strip():
            issues["missing_chunk_metadata"].append(c["chunk_id"])
        if table_like(c["text"]):
            issues["table_like"].append(c["chunk_id"])
        if len(c["text"].split()) < limits[0] or len(c["text"].split()) > limits[1]:
            issues["invisible_to_index"].append(c["chunk_id"])
    for p in proposer.proposals:
        issues[f"{p['rule']}_{RULES[p['rule']].summary.split(';')[0][:40]}"].append(p["chunk_id"])
    for m in proposer.migrations:
        issues[f"{m['rule']}_{m['status']}"].append(m["old_ids"][0])
    for f in proposer.flags:
        label = f"{f['rule']}_{f['detail'].split(':')[0].split(';')[0]}" if f["rule"] in {"F2", "F3", "F7", "F8"} else f["rule"]
        issues[label].append(f.get("chunk_id") or f.get("doc_id"))
    families = sorted({f["family"] for f in proposer.flags if f["rule"] == "F5"})
    exact = Counter(ev.normalize(c["text"]) for c in chunks)
    return {
        "corpus": {"chunks": len(chunks), "documents": len({c["doc_id"] for c in chunks}),
                   "corpus_sha256": corpus_hash(chunks), "exact_duplicate_copies": sum(n - 1 for n in exact.values()),
                   "version_families": families},
        "issues": {k: {"count": len(v), "sample": sorted(set(v))[:SAMPLE]} for k, v in sorted(issues.items())},
        "rules": {r.rule_id: {"tier": r.tier, "summary": r.summary} for r in RULES.values()},
        "proposal_summary": proposer.summary(),
    }


# ---------------------------------------------------------------- output safety

def protected_paths(inputs: list[Path]) -> list[Path]:
    return [p.resolve() for p in [DATA_DIR, CHUNKS_DIR, REGISTRY, QUESTIONS, CONFIG, FIXTURES, Path(__file__), *inputs]]


def check_output(path: Path, inputs: list[Path], root: Path = RUNS_ROOT) -> Path:
    """Resolve ``path`` (following symlinks) and refuse anything outside ``root`` or touching an input."""
    resolved, allowed = path.resolve(), root.resolve()
    if resolved == allowed or not resolved.is_relative_to(allowed):
        raise ValueError(f"output must be a path inside {root}, got {path}")
    for p in protected_paths(inputs):
        if resolved == p or resolved.is_relative_to(p) or p.is_relative_to(resolved):
            raise ValueError(f"output {path} resolves onto or around an input: {p}")
    return resolved


def write_file(target: Path, content: str, out_root: Path, inputs: list[Path]) -> None:
    """Write one file after re-checking it is not a symlink and stays inside the output root."""
    if target.is_symlink():
        raise ValueError(f"refusing to write through symlink {target}")
    resolved = target.resolve()
    if not resolved.is_relative_to(out_root) or any(resolved == p or resolved.is_relative_to(p) for p in protected_paths(inputs)):
        raise ValueError(f"refusing to write {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def prepare_output(out: Path, inputs: list[Path], replace: bool, root: Path = RUNS_ROOT) -> Path:
    resolved = check_output(out, inputs, root)
    if out.is_symlink():
        raise ValueError(f"output directory {out} is a symlink")
    if resolved.exists() and any(resolved.iterdir()):
        manifest = resolved / MANIFEST
        ours = manifest.is_file() and json.loads(manifest.read_text(encoding="utf-8")).get("tool") == TOOL
        if not (replace and ours):
            raise ValueError(f"{out} is not empty; pass --replace to overwrite an earlier {TOOL} run")
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


# ---------------------------------------------------------------- staging

def read_corpus(directory: Path) -> tuple[list[dict], dict[str, list[str]]]:
    """Chunks in evaluator order plus file name to chunk ids, for writing a staged copy."""
    chunks, files = [], {}
    for path in sorted(directory.rglob("*.json")):
        rows = ev.read_json(path)
        files[str(path.relative_to(directory))] = [r["chunk_id"] for r in rows]
        chunks.extend(rows)
    ev.read_chunks(directory)  # same validation the production loader applies
    return chunks, files


def recount(chunk: dict, original: dict) -> dict:
    if chunk["text"] == original["text"]:
        return {**original, "section_heading": chunk["section_heading"]}
    updated = {**original, "text": chunk["text"], "section_heading": chunk["section_heading"]}
    if "n_sentences" in original:
        updated["n_sentences"] = count_sentences(chunk["text"])
    if "token_count" in original:
        updated["token_count"] = math.ceil(len(chunk["text"]) / 4)
    ordered = {k: updated[k] for k in FIELDS if k in updated}
    return {**ordered, **{k: v for k, v in updated.items() if k not in ordered}}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def manifest_for(proposer: Proposer, source_dir: Path) -> dict:
    staged = [recount(c, o) for c, o in zip(proposer.chunks, proposer.source)]
    before = proposer.evidence.corpus_support(proposer.source)
    after = proposer.evidence.corpus_support(staged)
    lost = sorted(k for k in before if before[k] and not after[k])
    weakened = sorted(k for k in before if before[k] - after[k] and after[k])
    return {
        "tool": TOOL, "commit": git_commit(), "source": str(source_dir.resolve().relative_to(ROOT)) if source_dir.resolve().is_relative_to(ROOT) else str(source_dir),
        "source_corpus_sha256": corpus_hash(proposer.source), "staged_corpus_sha256": corpus_hash(staged),
        "accepted_review_rules": sorted(proposer.accept), "skipped_proposals": sorted(proposer.skip),
        "rules": {r.rule_id: {"tier": r.tier, "summary": r.summary} for r in RULES.values()},
        "summary": proposer.summary(),
        "staged_changes": {"chunks_changed": sum(c["text"] != o["text"] or c["section_heading"] != o["section_heading"]
                                                 for c, o in zip(staged, proposer.source)),
                           "chunk_ids_unchanged": [c["chunk_id"] for c in staged] == [c["chunk_id"] for c in proposer.source]},
        "evidence": {"groups": len(before), "lost_everywhere": lost, "chunks_no_longer_supporting": weakened},
        "proposals": proposer.proposals,
    }


def stage(proposer: Proposer, source_dir: Path, files: dict[str, list[str]], out: Path, replace: bool,
          root: Path = RUNS_ROOT) -> Path:
    inputs = [source_dir]
    out_root = prepare_output(out, inputs, replace, root)
    by_id = {c["chunk_id"]: recount(c, o) for c, o in zip(proposer.chunks, proposer.source)}
    for name, ids in sorted(files.items()):
        write_file(out_root / "chunks" / name, json.dumps([by_id[i] for i in ids], indent=2, ensure_ascii=False) + "\n",
                   out_root, inputs)
    dump = lambda obj: json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    write_file(out_root / MANIFEST, dump(manifest_for(proposer, source_dir)), out_root, inputs)
    write_file(out_root / "migration.json", dump({
        "tool": TOOL, "applied": False,
        "note": "Proposal only. Chunk ids change, so the mentor applies these after review, then rebuilds the index.",
        "migrations": proposer.migrations}), out_root, inputs)
    write_file(out_root / "flags.json", dump({"tool": TOOL, "flags": proposer.flags}), out_root, inputs)
    return out_root


# ---------------------------------------------------------------- evaluation adapter

def production_config() -> dict:
    return ev.read_json(CONFIG)


def build_index(chunks: list[dict], config: dict):
    """LexicalIndex with production settings. Does not touch retrieval._load or its cache."""
    from backend.app.retrieval_support.index import LexicalIndex
    settings = ev.Settings(**{f.name: config[f.name] for f in fields(ev.Settings)})
    settings.validate()
    return LexicalIndex(chunks, settings)


def staged_retrieve(index, config: dict, urls: dict[str, str], query: str, top_k: int = 5, history=None):
    """Evaluate a staged corpus with the same retrieval path used by chat."""
    from backend.app.retrieval import retrieve_from_index
    return retrieve_from_index(index, config, urls, query, top_k, history)


def run_split(chunks: list[dict], questions: list[dict], config: dict, urls: dict[str, str]) -> dict:
    from dataclasses import asdict
    started = time.perf_counter()
    index = build_index(chunks, config)
    cold_ms = (time.perf_counter() - started) * 1000
    for q in questions:  # warm caches once so latency excludes first-call effects
        staged_retrieve(index, config, urls, q["query"])
    rows, latencies = [], []
    for q in questions:
        t = time.perf_counter()
        result = staged_retrieve(index, config, urls, q["query"])
        latencies.append((time.perf_counter() - t) * 1000)
        hits = [{**asdict(p), "estimated_tokens": ev.cost(asdict(p))} for p in result.passages]
        rows.append({"id": q["id"], "reason": result.reason, "chunk_ids": [h["chunk_id"] for h in hits],
                     "metrics": ev.grade(q, hits)})
    ordered = sorted(latencies)
    return {"corpus_sha256": corpus_hash(chunks), "chunks": len(chunks), "indexed_chunks": index.n,
            "cold_index_ms": round(cold_ms, 1), "p50_ms": round(statistics.median(latencies), 3),
            "p95_ms": round(ordered[math.ceil(.95 * len(ordered)) - 1], 3),
            "summary": ev.summarize(rows), "rows": rows}


METRICS = ("complete_evidence", "evidence_recall", "reciprocal_rank", "context_precision", "abstention_correct")


def compare(before: dict, after: dict) -> dict:
    """Per-query changes; a regression is any metric that got worse."""
    regressions, improvements = [], []
    old = {r["id"]: r for r in before["rows"]}
    for row in after["rows"]:
        prior = old[row["id"]]
        delta = {k: (prior["metrics"][k], row["metrics"][k]) for k in METRICS
                 if prior["metrics"][k] is not None and prior["metrics"][k] != row["metrics"][k]}
        if not delta:
            continue
        worse = any(b < a for a, b in delta.values())
        better = any(b > a for a, b in delta.values())
        entry = {"id": row["id"], "delta": delta, "before_chunks": prior["chunk_ids"], "after_chunks": row["chunk_ids"]}
        if worse:
            regressions.append(entry)
        if better:
            improvements.append(entry)
    return {"regressions": regressions, "improvements": improvements,
            "summary_delta": {k: round((after["summary"][k] or 0) - (before["summary"][k] or 0), 4)
                              for k in (*METRICS, "estimated_tokens", "leaderboard_score")}}


def evidence_availability(groups: list[Group], before: list[dict], after: list[dict]) -> dict:
    index = EvidenceIndex(groups)
    a, b = index.corpus_support(before), index.corpus_support(after)
    return {"groups": len(groups), "lost_everywhere": sorted(k for k in a if a[k] and not b[k]),
            "chunks_no_longer_supporting": sorted(k for k in a if a[k] - b[k] and b[k]),
            "newly_supported_chunks": sorted(k for k in a if b[k] - a[k])}


def environment() -> dict:
    return {"commit": git_commit(), "python": platform.python_version(), "machine": platform.platform(),
            "processor": platform.processor() or platform.machine()}


def evaluate_corpora(source: list[dict], staged: list[dict], split: str) -> dict:
    from backend.app.retrieval import load_urls
    config = production_config()
    questions = ev.read_questions(QUESTIONS, source, split)  # labels validated against the source corpus
    urls = load_urls(ROOT / config["registry_path"])
    base, new = run_split(source, questions, config, urls), run_split(staged, questions, config, urls)
    settings = {k: config[k] for k in config if k not in {"chunks_path", "registry_path"}}
    return {"environment": environment(), "split": split, "settings": settings,
            "questions_sha256": hashlib.sha256(QUESTIONS.read_bytes()).hexdigest(), "questions": len(questions),
            "before": {k: v for k, v in base.items() if k != "rows"}, "after": {k: v for k, v in new.items() if k != "rows"},
            "comparison": compare(base, new),
            "evidence": evidence_availability(load_groups(), source, staged),
            "rows": {"before": base["rows"], "after": new["rows"]}}


def apply_migrations_in_memory(chunks: list[dict], migrations: list[dict]) -> list[dict]:
    """Experiment only: what the corpus would look like if every unblocked migration were applied."""
    by_id = {c["chunk_id"]: dict(c) for c in chunks}
    gone: set[str] = set()
    for m in migrations:
        if m["status"] != "proposal_only" or set(m["old_ids"]) & gone:
            continue
        if m["rule"] in {"M1", "M2"}:
            gone.add(m["old_ids"][0])
        elif m["rule"] in {"M3", "M4"}:
            a, b = m["old_ids"]
            if len((by_id[a]["text"] + " " + by_id[b]["text"]).split()) <= 300:
                by_id[a]["text"] = by_id[a]["text"].rstrip() + " " + by_id[b]["text"].lstrip()
                gone.add(b)
        elif m["rule"] == "M5":
            old, new = m["new_ids"]
            text = by_id[old]["text"]
            by_id[old]["text"], right = text[:m["split_at"]].rstrip(), text[m["split_at"]:].lstrip()
            by_id[new] = {**by_id[old], "chunk_id": new, "text": right}
    out = []
    for c in chunks:
        if c["chunk_id"] in gone:
            continue
        out.append(by_id[c["chunk_id"]])
        out += [by_id[m["new_ids"][1]] for m in migrations
                if m["rule"] == "M5" and m["status"] == "proposal_only" and m["old_ids"][0] == c["chunk_id"]]
    return out


def ablate(source: list[dict], split: str, registry: list[dict], limits: tuple[int, int]) -> dict:
    """Safe-only, safe plus each review rule alone, safe plus all review rules, and simulated migrations."""
    groups, raw = load_groups(), read_raw_lines()
    variants = [("safe", set())] + [(f"safe+{r}", {r}) for r in REVIEW_RULES] + [("safe+all_review", set(REVIEW_RULES))]
    config = production_config()
    from backend.app.retrieval import load_urls
    urls = load_urls(ROOT / config["registry_path"])
    questions = ev.read_questions(QUESTIONS, source, split)
    base = run_split(source, questions, config, urls)
    rows = []
    for name, accept in variants:
        proposer = Proposer(source, groups, accept, limits, registry, raw).run()
        staged = [recount(c, o) for c, o in zip(proposer.chunks, proposer.source)]
        result = run_split(staged, questions, config, urls)
        rows.append(_ablation_row(name, base, result, groups, source, staged, proposer))
        if name == "safe+all_review":
            migrated = apply_migrations_in_memory(staged, proposer.migrations)
            result = run_split(migrated, questions, config, urls)
            rows.append(_ablation_row("safe+all_review+migrations (simulated, ids change)", base, result, groups,
                                      source, migrated, proposer))
    return {"environment": environment(), "split": split, "questions": len(questions),
            "baseline": {k: v for k, v in base.items() if k != "rows"}, "variants": rows}


def _ablation_row(name, base, result, groups, source, staged, proposer) -> dict:
    cmp = compare(base, result)
    availability = evidence_availability(groups, source, staged)
    return {"variant": name, "chunks": result["chunks"], "chunks_changed": sum(
        1 for c in staged if c["text"] != {o["chunk_id"]: o for o in source}.get(c["chunk_id"], {}).get("text")),
        "summary": result["summary"], "p50_ms": result["p50_ms"], "p95_ms": result["p95_ms"],
        "cold_index_ms": result["cold_index_ms"], "delta": cmp["summary_delta"],
        "regressions": [r["id"] for r in cmp["regressions"]], "improvements": [r["id"] for r in cmp["improvements"]],
        "evidence_lost_everywhere": availability["lost_everywhere"],
        "chunks_no_longer_supporting": availability["chunks_no_longer_supporting"]}


# ---------------------------------------------------------------- CLI

def load_registry() -> list[dict]:
    return json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else []


def index_limits() -> tuple[int, int]:
    config = production_config()
    return config["min_chunk_words"], config["max_chunk_words"]


def write_json_report(path: Path | None, obj: dict, inputs: list[Path]) -> None:
    if path is None:
        return
    resolved = check_output(path, inputs)
    write_file(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n", resolved.parent, inputs)
    print(f"wrote {path}")


def print_table(summary: dict) -> None:
    print(f"{'rule':<5} {'tier':<10} counts")
    for rule_id, counts in summary.items():
        print(f"{rule_id:<5} {RULES[rule_id].tier:<10} {counts}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("audit", help="count issues with representative ids")
    a.add_argument("--chunks", type=Path, default=CHUNKS_DIR)
    a.add_argument("--json", type=Path)
    p = sub.add_parser("propose", help="build proposals; dry run unless --write")
    p.add_argument("--chunks", type=Path, default=CHUNKS_DIR)
    p.add_argument("--accept", default="", help="comma-separated review rules to stage, e.g. R1,R2")
    p.add_argument("--write", action="store_true", help="write manifest, migration proposal and staged corpus")
    p.add_argument("--out", type=Path, default=RUNS_ROOT / "stage")
    p.add_argument("--replace", action="store_true", help="replace an earlier staged run in --out")
    p.add_argument("--skip", default="", help="comma-separated RULE:chunk_id review proposals to leave out")
    e = sub.add_parser("evaluate", help="compare a staged corpus with the source on one split")
    e.add_argument("--staged", type=Path, required=True, help="staged run directory (contains chunks/)")
    e.add_argument("--chunks", type=Path, default=CHUNKS_DIR)
    e.add_argument("--split", choices=("dev", "test"), default="dev")
    e.add_argument("--json", type=Path)
    b = sub.add_parser("ablate", help="evaluate rule variants in memory")
    b.add_argument("--chunks", type=Path, default=CHUNKS_DIR)
    b.add_argument("--split", choices=("dev", "test"), default="dev")
    b.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    try:
        source, files = read_corpus(args.chunks)
        inputs = [args.chunks]
        if args.command == "audit":
            report = audit_report(source, load_registry(), index_limits())
            for issue, row in report["issues"].items():
                print(f"{issue:<48} {row['count']:>5}  {', '.join(row['sample'])}")
            write_json_report(args.json, report, inputs)
        elif args.command == "propose":
            accept = {r.strip() for r in args.accept.split(",") if r.strip()}
            if args.write:
                check_output(args.out, inputs)  # refuse a bad destination before doing any work
            skip = {k.strip() for k in args.skip.split(",") if k.strip()}
            proposer = Proposer(source, load_groups(), accept, index_limits(), load_registry(), read_raw_lines(),
                                skip).run()
            print_table(proposer.summary())
            if args.write:
                out = stage(proposer, args.chunks, files, args.out, args.replace)
                print(f"staged corpus and manifests written to {out}")
            else:
                print("dry run: nothing written (pass --write to stage under evaluate/runs/mentee-2/)")
        elif args.command == "evaluate":
            staged_dir = args.staged.resolve() / "chunks"
            if staged_dir.resolve() == args.chunks.resolve():
                raise ValueError("staged corpus is the source corpus")
            staged, _ = read_corpus(staged_dir)
            result = evaluate_corpora(source, staged, args.split)
            print(json.dumps({k: result[k] for k in ("split", "before", "after", "evidence")}
                             | {"summary_delta": result["comparison"]["summary_delta"],
                                "regressions": [r["id"] for r in result["comparison"]["regressions"]],
                                "improvements": [r["id"] for r in result["comparison"]["improvements"]]}, indent=2))
            write_json_report(args.json, result, inputs + [staged_dir])
        elif args.command == "ablate":
            result = ablate(source, args.split, load_registry(), index_limits())
            base = result["baseline"]["summary"]
            print(f"baseline leaderboard {base['leaderboard_score']:.2f} complete {base['complete_evidence']:.3f}")
            for row in result["variants"]:
                s = row["summary"]
                print(f"{row['variant']:<52} lb {s['leaderboard_score']:.2f} ({row['delta']['leaderboard_score']:+.2f}) "
                      f"complete {s['complete_evidence']:.3f} tokens {s['estimated_tokens']:.1f} "
                      f"changed {row['chunks_changed']} regress {len(row['regressions'])} lost {len(row['evidence_lost_everywhere'])}")
            write_json_report(args.json, result, inputs)
    except (ValueError, OSError, KeyError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
