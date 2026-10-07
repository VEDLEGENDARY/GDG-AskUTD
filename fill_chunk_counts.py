#!/usr/bin/env python3
"""Validate chunk JSON files and fill in ``n_sentences`` and ``token_count``.

Token count is ceil(characters / 4). Sentences are split on ., ! or ? followed
by whitespace and an uppercase letter, quote, or opening parenthesis.
Run ``python fill_chunk_counts.py backend/data/chunks/doc006.json``.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

FIELDS = ["chunk_id", "doc_id", "text", "source_title", "section_heading", "n_sentences", "token_count"]
LIGATURES = "\ufb00\ufb01\ufb02\ufb03\ufb04"
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")
CHUNK_ID = re.compile(r"^(doc\d{3})_p\d+_c\d+$")


def count_sentences(text: str) -> int:
    return len([part for part in SENTENCE_END.split(text.strip()) if part])


def process(path: Path) -> int:
    chunks = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    seen: set[str] = set()

    for chunk in chunks:
        chunk_id = chunk.get("chunk_id", "?")
        missing = [field for field in FIELDS if field not in chunk]
        if missing:
            errors.append(f"{chunk_id}: missing {missing}")
            continue
        match = CHUNK_ID.match(chunk_id)
        if not match or match.group(1) != chunk["doc_id"]:
            errors.append(f"{chunk_id}: chunk_id does not match doc_id {chunk['doc_id']}")
        if chunk_id in seen:
            errors.append(f"{chunk_id}: duplicate chunk_id")
        seen.add(chunk_id)

        text = chunk["text"]
        if not text.strip():
            errors.append(f"{chunk_id}: empty text")
        if any(char in text for char in LIGATURES):
            errors.append(f"{chunk_id}: contains ligature characters")
        if "\n" in text:
            errors.append(f"{chunk_id}: contains line breaks")

        chunk["n_sentences"] = count_sentences(text)
        chunk["token_count"] = math.ceil(len(text) / 4)

    path.write_text(json.dumps(chunks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for chunk in chunks:
        print(f"{chunk['chunk_id']:<16} sentences={chunk['n_sentences']:<3} tokens={chunk['token_count']}")
    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    return max(process(path) for path in args.files)


if __name__ == "__main__":
    raise SystemExit(main())
