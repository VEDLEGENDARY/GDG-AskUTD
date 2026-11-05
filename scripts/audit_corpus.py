#!/usr/bin/env python3
"""Audit chunk quality in ``backend/data/chunks``.

Reports chunks that are too short or too long, look like navigation, duplicate
other chunks, contain odd characters or page furniture, or lack a usable title
or heading. Read-only; use ``scripts/fix_chunks.py`` to repair docs.

Usage:
    python scripts/audit_corpus.py [--docs 119-198] [--show 3] [--json audit.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = ROOT / "backend" / "data" / "chunks"

MIN_WORDS = 15
MAX_WORDS = 250
NEAR_DUPLICATE = 0.8
ISSUES = (
    "short", "long", "navigation", "duplicate", "near_duplicate",
    "odd_characters", "page_furniture", "missing_title", "bad_title", "missing_heading",
)

FURNITURE = {
    "print header": re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4},? \d{1,2}:\d{2} ?[AP]M\b"),
    "skip link": re.compile(r"\bskip to (main )?content\b", re.I),
    "cookie notice": re.compile(r"\bcookies?\b.{0,80}\b(accept|consent|settings)\b", re.I),
    "page counter": re.compile(r"\bpage \d+ of \d+\b", re.I),
    "table counter": re.compile(r"\bshowing \d+ to \d+ of \d+ entries\b", re.I),
    "site footer": re.compile(r"800 W(\.|est)? Campbell R(oa)?d", re.I),
    "privacy link": re.compile(r"\bRelated Pages\b|\bPrivacy Policy\b"),
    "chatbot widget": re.compile(r"I.m a chatbot|May I help you\?", re.I),
    "call to action": re.compile(r"\b(VIEW THE FULL CALENDAR|APPLY NOW|EXPLORE THE PROGRAM|Request Information)\b"),
}
ODD_CHARACTERS = re.compile(r"[\ue000-\uf8ff\ufffd\u0000-\u0008\u000b-\u001f]|Ã.|â€")
BAD_TITLE = re.compile(r"(\s>\s|[–&\-,:]\s*$|\b(and|of|the|for|to|in)\s*$)", re.I)
SENTENCE_TITLE = re.compile(r"^(if|we|you|ut dallas prepares|join)\b", re.I)

log = logging.getLogger("audit_corpus")


def words(text: str) -> list[str]:
    """Whitespace-separated tokens."""
    return text.split()


def normalized(text: str) -> str:
    """Lowercase alphanumeric form used to compare chunk texts."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def shingles(text: str, size: int = 5) -> set[str]:
    """Word 5-grams of the normalized text."""
    tokens = normalized(text).split()
    return {" ".join(tokens[i : i + size]) for i in range(max(1, len(tokens) - size + 1))}


def letter_spaced(text: str) -> bool:
    """True when most tokens are single characters ('N e e d a s s i s t')."""
    tokens = words(text)
    return len(tokens) >= 10 and sum(len(t) == 1 for t in tokens) / len(tokens) > 0.5


def navigation_like(text: str) -> bool:
    """Menus and link lists: mostly capitalized words with almost no sentences."""
    tokens = [t for t in words(text) if re.search(r"[A-Za-z]", t)]
    if len(tokens) < 8:
        return False
    capitalized = sum(t[0].isupper() for t in tokens) / len(tokens)
    sentences = len(re.findall(r"[.!?](\s|$)", text))
    return capitalized > 0.6 and sentences / len(tokens) < 1 / 25


def furniture_found(text: str) -> list[str]:
    """Names of page-furniture patterns present in the text."""
    return [name for name, pattern in FURNITURE.items() if pattern.search(text)]


def doc_number(doc_id: str) -> int:
    """Numeric part of a docNNN id."""
    return int(re.sub(r"\D", "", doc_id) or 0)


def parse_range(spec: str | None) -> tuple[int, int] | None:
    """Parse '119-169' or '120' into an inclusive range."""
    if not spec:
        return None
    low, _, high = spec.partition("-")
    return int(low), int(high or low)


def load_chunks(directory: Path = CHUNKS_DIR) -> list[dict]:
    """All chunk records in file order."""
    records: list[dict] = []
    for path in sorted(directory.glob("doc*.json")):
        for record in json.loads(path.read_text(encoding="utf-8")):
            records.append({**record, "_file": path.name})
    return records


def audit(records: list[dict], doc_range: tuple[int, int] | None = None) -> dict[str, list[dict]]:
    """Return issue name to a list of findings for chunks in ``doc_range``."""
    findings: dict[str, list[dict]] = defaultdict(list)
    by_text: dict[str, list[str]] = defaultdict(list)
    for record in records:
        by_text[normalized(record["text"])].append(record["chunk_id"])

    selected = [r for r in records if doc_range is None or doc_range[0] <= doc_number(r["doc_id"]) <= doc_range[1]]
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for record in selected:
        by_doc[record["doc_id"]].append(record)

    def add(issue: str, record: dict, detail: str = "") -> None:
        findings[issue].append({"chunk_id": record["chunk_id"], "detail": detail, "text": record["text"][:160]})

    for record in selected:
        text, count = record["text"], len(words(record["text"]))
        if count < MIN_WORDS:
            add("short", record, f"{count} words")
        if count > MAX_WORDS:
            add("long", record, f"{count} words")
        if navigation_like(text):
            add("navigation", record)
        twins = [c for c in by_text[normalized(text)] if c != record["chunk_id"]]
        if twins:
            add("duplicate", record, ", ".join(twins[:3]))
        odd = ODD_CHARACTERS.findall(text)
        if odd or letter_spaced(text):
            add("odd_characters", record, "letter-spaced" if letter_spaced(text) else repr("".join(odd[:5])))
        furniture = furniture_found(text)
        if furniture:
            add("page_furniture", record, ", ".join(furniture))
        title, heading = record.get("source_title", "").strip(), record.get("section_heading", "").strip()
        if not title:
            add("missing_title", record)
        elif BAD_TITLE.search(title) or SENTENCE_TITLE.search(title) or len(title.split()) > 12:
            add("bad_title", record, title)
        if not heading:
            add("missing_heading", record)

    for doc_records in by_doc.values():
        sets = [shingles(r["text"]) for r in doc_records]
        for i, left in enumerate(sets):
            for j in range(i):
                right = sets[j]
                overlap = len(left & right) / len(left | right) if left | right else 0.0
                if NEAR_DUPLICATE <= overlap < 1.0:
                    add("near_duplicate", doc_records[i], f"{overlap:.2f} vs {doc_records[j]['chunk_id']}")
                    break
    return findings


def render(findings: dict[str, list[dict]], total: int, show: int) -> str:
    """Plain-text summary table plus a few examples per issue."""
    lines = [f"Chunks audited: {total}", "", f"{'issue':<16} {'chunks':>6}  docs", f"{'-' * 16} {'-' * 6}  {'-' * 30}"]
    for issue in ISSUES:
        rows = findings.get(issue, [])
        docs = Counter(row["chunk_id"].split("_")[0] for row in rows)
        top = ", ".join(f"{doc}({n})" for doc, n in docs.most_common(5))
        lines.append(f"{issue:<16} {len(rows):>6}  {top}")
    flagged = {row["chunk_id"] for rows in findings.values() for row in rows}
    lines += ["", f"Chunks with at least one issue: {len(flagged)}"]
    if show:
        for issue in ISSUES:
            for row in findings.get(issue, [])[:show]:
                lines.append(f"  [{issue}] {row['chunk_id']} {row['detail']} :: {row['text'][:100]!r}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chunks", type=Path, default=CHUNKS_DIR, help="chunk directory")
    parser.add_argument("--docs", help="inclusive doc number range such as 119-169")
    parser.add_argument("--show", type=int, default=0, help="examples to print per issue")
    parser.add_argument("--json", type=Path, help="write all findings to this JSON file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    records = load_chunks(args.chunks)
    doc_range = parse_range(args.docs)
    total = sum(1 for r in records if doc_range is None or doc_range[0] <= doc_number(r["doc_id"]) <= doc_range[1])
    findings = audit(records, doc_range)
    sys.stdout.write(render(findings, total, args.show))
    if args.json:
        args.json.write_text(json.dumps(findings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.info("findings written to %s", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
