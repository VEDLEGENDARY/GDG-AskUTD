#!/usr/bin/env python3
"""Add new PDFs to the corpus: extract text, number the document, and chunk it.

For every PDF given this script:

1. extracts and cleans the text with ``pdf_to_text.extract_text``,
2. writes it to ``backend/data/raw_text/docNNN.txt`` using the next free number,
3. splits it into sentence-aligned chunks and writes
   ``backend/data/chunks/docNNN_<slug>.json`` using the team chunk schema,
4. records the PDF to doc mapping in ``backend/data/doc_sources.json``.

Run ``python add_documents.py backend/data/raw_pdfs/<file>.pdf [...]``.
PDFs already listed in ``doc_sources.json`` are skipped. ``--dry-run`` shows what
would happen without writing anything. PDFs are never picked up automatically
because the original docs 001-118 predate ``doc_sources.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from fill_chunk_counts import SENTENCE_END, process as fill_counts
from pdf_to_text import extract_text

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "backend" / "data"
PDF_DIR, TEXT_DIR, CHUNK_DIR = DATA / "raw_pdfs", DATA / "raw_text", DATA / "chunks"
SOURCES = DATA / "doc_sources.json"

TARGET_WORDS = 120  # flush a chunk once it reaches this many words
MAX_WORDS = 200     # hard cap, safely below the evaluator's max_chunk_words
MIN_WORDS = 8       # drop fragments shorter than this
MIN_SECTION_WORDS = 70  # sections shorter than this are merged into the next one

LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}
BROWSER_HEADER = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*(AM|PM)?", re.I)
BROWSER_FOOTER = re.compile(r"^(https?://\S+)?\s*\d+\s*/\s*\d+$")
PAGE_NUMBER = re.compile(r"^(page\s+)?\d{1,3}(\s+of\s+\d{1,3})?$", re.I)


def clean_lines(text: str) -> list[str]:
    """Normalise ligatures and drop page furniture and repeated boilerplate lines."""
    for bad, good in LIGATURES.items():
        text = text.replace(bad, good)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [l for l in lines if not (BROWSER_HEADER.match(l) or BROWSER_FOOTER.match(l) or PAGE_NUMBER.match(l))]
    # Lines repeated many times (menus, headers, footers) carry no content.
    counts = Counter(l for l in lines if l)
    threshold = max(4, len(lines) // 40)
    return [l for l in lines if not l or counts[l] < threshold or len(l.split()) > 25]


def is_heading(line: str, following: str) -> bool:
    words = line.split()
    if not line or len(words) > 12 or line[-1] in ".,;:!?":
        return False
    if not following or len(following.split()) < 4:
        return False
    return line.isupper() or line.istitle() or sum(w[:1].isupper() for w in words) >= max(1, len(words) * 2 // 3)


def split_sections(lines: list[str]) -> list[tuple[str, str]]:
    """Return (heading, body) pairs; body paragraphs are joined into one string."""
    sections: list[tuple[str, list[str]]] = [("Overview", [])]
    for i, line in enumerate(lines):
        if not line:
            continue
        nxt = next((l for l in lines[i + 1:] if l), "")
        if is_heading(line, nxt):
            sections.append((line, []))
        else:
            sections[-1][1].append(line)
    merged: list[tuple[str, str]] = []
    pending_heading, pending_body = "", ""
    for heading, body_lines in sections:
        body = re.sub(r"\s+", " ", " ".join(body_lines)).strip()
        if not body:
            continue
        if pending_body:  # fold short sections into the next one so chunks stay meaningful
            body = pending_body + " " + heading + ". " + body
            heading = pending_heading
        if len(body.split()) < MIN_SECTION_WORDS:
            pending_heading, pending_body = heading, body
            continue
        merged.append((heading, body))
        pending_heading, pending_body = "", ""
    if pending_body:
        if merged:
            merged[-1] = (merged[-1][0], merged[-1][1] + " " + pending_body)
        else:
            merged.append((pending_heading, pending_body))
    return merged


def chunk_section(body: str) -> list[str]:
    sentences = [s for s in SENTENCE_END.split(body) if s.strip()]
    chunks, current, size = [], [], 0
    for sentence in sentences:
        words = sentence.split()
        while len(words) > MAX_WORDS:  # pathological run-on text with no sentence breaks
            if current:
                chunks.append(" ".join(current)); current, size = [], 0
            chunks.append(" ".join(words[:MAX_WORDS])); words = words[MAX_WORDS:]
        sentence = " ".join(words)
        if current and size + len(words) > MAX_WORDS:
            chunks.append(" ".join(current)); current, size = [], 0
        current.append(sentence); size += len(words)
        if size >= TARGET_WORDS:
            chunks.append(" ".join(current)); current, size = [], 0
    if current:
        chunks.append(" ".join(current))
    # Merge a short tail into the previous chunk so no tiny fragments remain.
    if len(chunks) > 1 and len(chunks[-1].split()) < MIN_WORDS * 2 and len((chunks[-2] + " " + chunks[-1]).split()) <= MAX_WORDS:
        tail = chunks.pop()
        chunks[-1] += " " + tail
    return [c for c in chunks if len(c.split()) >= MIN_WORDS]


def title_from(pdf: Path, lines: list[str]) -> str:
    stem = re.sub(r"^https?___", "", pdf.stem)
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    first = next((l for l in lines if l and 2 <= len(l.split()) <= 14 and l[-1] not in ".,;"), "")
    return first or stem.title()


def slugify(text: str, limit: int = 48) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-") or "document"


def next_doc_number() -> int:
    numbers = [int(m.group(1)) for p in TEXT_DIR.glob("doc*.txt") if (m := re.match(r"doc(\d{3})", p.name))]
    numbers += [int(m.group(1)) for p in CHUNK_DIR.glob("doc*.json") if (m := re.match(r"doc(\d{3})", p.name))]
    return max(numbers, default=0) + 1


def load_sources() -> dict[str, str]:
    return json.loads(SOURCES.read_text(encoding="utf-8")) if SOURCES.exists() else {}


def add_pdf(pdf: Path, number: int, dry_run: bool) -> tuple[str, int, int]:
    doc_id = f"doc{number:03d}"
    text = extract_text(pdf)
    lines = clean_lines(text)
    title = title_from(pdf, lines)
    chunks, section_no = [], 0
    for heading, body in split_sections(lines):
        pieces = chunk_section(body)
        if not pieces:
            continue
        section_no += 1
        for c_no, piece in enumerate(pieces, 1):
            chunks.append({
                "chunk_id": f"{doc_id}_p{section_no}_c{c_no}", "doc_id": doc_id, "text": piece,
                "source_title": title, "section_heading": heading, "n_sentences": 0, "token_count": 0,
            })
    if not chunks:
        raise ValueError("no usable text (scanned PDF? run OCR first)")
    if dry_run:
        return doc_id, len(text.split()), len(chunks)
    (TEXT_DIR / f"{doc_id}.txt").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    out = CHUNK_DIR / f"{doc_id}_{slugify(title)}.json"
    out.write_text(json.dumps(chunks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if fill_counts(out):
        raise ValueError(f"chunk validation failed for {out.name}")
    return doc_id, len(text.split()), len(chunks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDFs to add")
    parser.add_argument("--dry-run", action="store_true", help="report without writing files")
    args = parser.parse_args()

    sources = load_sources()
    known = set(sources.values())
    pdfs = [p for p in args.pdfs if p.name not in known]
    if not pdfs:
        print("Nothing to add.")
        return 0
    number, failures = next_doc_number(), 0
    for pdf in pdfs:
        try:
            doc_id, words, n_chunks = add_pdf(pdf, number, args.dry_run)
        except Exception as exc:
            print(f"SKIP {pdf.name}: {exc}", file=sys.stderr)
            failures += 1
            continue
        sources[doc_id] = pdf.name
        number += 1
        print(f"{doc_id}  {words:>6} words  {n_chunks:>3} chunks  {pdf.name}")
    if not args.dry_run:
        SOURCES.write_text(json.dumps(dict(sorted(sources.items())), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
