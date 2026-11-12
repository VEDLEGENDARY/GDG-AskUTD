#!/usr/bin/env python3
"""Build ``backend/data/documents.json``, the registry of every chunked document.

Docs listed in ``doc_sources.json`` (doc119 onward) take their PDF from that file.
Older docs are recovered by extracting every raw PDF with ``pdf_to_text`` and
matching it to ``raw_text/docNNN.txt`` by Jaccard similarity on 5-word shingles.
A match is accepted only when it clears a high threshold and either beats the
runner-up by a clear margin or is an exact text match; the doc's chunk text must
also point at the same PDF. Everything else stays unmatched; nothing is guessed.

Usage:
    python scripts/build_registry.py [--report /tmp/registry_report.md]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend" / "data"
CHUNKS_DIR = DATA / "chunks"
RAW_TEXT_DIR = DATA / "raw_text"
RAW_PDF_DIR = DATA / "raw_pdfs"
DOC_SOURCES = DATA / "doc_sources.json"
WEB_SOURCES = DATA / "web_sources.json"
REGISTRY = DATA / "documents.json"
DEFAULT_CACHE = Path(tempfile.gettempdir()) / "askutd_pdf_text_cache.json"

SHINGLE = 5
CHAR_SHINGLE = 30
MATCH_THRESHOLD = 0.6
MIN_MARGIN = 0.15
CHUNK_TOLERANCE = 0.02
LETTER_SPACED_RATIO = 0.5
URL_PREFIX = "https___"
FILE_EXTENSIONS = ("pdf", "html", "htm", "aspx", "php")
UTD_HOST = re.compile(r"^([a-z0-9]+)-utdallas-edu$")
UPLOAD_PATH = re.compile(r"^files/\d{4}/\d{2}$")

log = logging.getLogger("build_registry")


@dataclass(frozen=True)
class UrlGuess:
    """A URL recovered from a PDF filename plus the reasons it may be wrong."""

    url: str | None
    concerns: tuple[str, ...] = ()


def filename_to_url(filename: str) -> UrlGuess:
    """Invert the naming rule in documentation/naming.md for one PDF filename."""
    stem = filename.strip()
    while stem.lower().endswith(".pdf"):
        stem = stem[:-4].rstrip()
    if not stem.startswith(URL_PREFIX):
        return UrlGuess(None, ("filename is not in URL form",))
    concerns: list[str] = []
    rest = stem[len(URL_PREFIX):]
    if URL_PREFIX in rest:
        rest = rest[rest.rindex(URL_PREFIX) + len(URL_PREFIX):]
        concerns.append("doubled URL prefix in filename")
    host_form, _, path_form = rest.partition("_")
    host_match = UTD_HOST.match(host_form)
    if host_match is None:
        return UrlGuess(None, (f"host {host_form!r} is not a known utdallas.edu host",))
    host = f"{host_match.group(1)}.utdallas.edu"
    trailing_slash = path_form.endswith("_")
    segments = [segment for segment in path_form.split("_") if segment]
    if len(segments) > 4 and UPLOAD_PATH.match("/".join(segments[:3])):
        segments = segments[:3] + ["_".join(segments[3:])]
        concerns.append("underscore kept inside an uploaded file name")
    if segments:
        last = segments[-1]
        for extension in FILE_EXTENSIONS:
            if last.lower().endswith(f"-{extension}"):
                segments[-1] = f"{last[: -len(extension) - 1]}.{extension}"
                concerns.append(f"extension .{extension} inferred from trailing -{extension}")
                break
        if re.search(r"[a-z][A-Z]", segments[-1]) and "." not in segments[-1]:
            concerns.append("last segment looks like an in-page anchor")
        elif len(segments) == 4 and UPLOAD_PATH.match("/".join(segments[:3])) and "." not in segments[-1]:
            concerns.append("uploaded file name has no recorded extension")
    path = "/".join(segments)
    url = f"https://{host}/{path}"
    if trailing_slash and path:
        url += "/"
    return UrlGuess(url, tuple(concerns))


def words(text: str) -> list[str]:
    """Lowercase alphanumeric words."""
    return re.findall(r"[a-z0-9]+", text.lower())


def shingles(text: str, size: int = SHINGLE) -> set[str]:
    """Return the set of word n-grams used for matching."""
    tokens = words(text)
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def char_shingles(text: str, size: int = CHAR_SHINGLE) -> set[str]:
    """Character n-grams over text with all whitespace and punctuation removed."""
    squashed = "".join(words(text))
    return {squashed[i : i + size] for i in range(max(1, len(squashed) - size + 1))}


def is_letter_spaced(text: str) -> bool:
    """True when most tokens are single characters, as in 'H o m e / P o l i c y'."""
    tokens = text.split()
    return bool(tokens) and sum(len(token) == 1 for token in tokens) / len(tokens) > LETTER_SPACED_RATIO


def jaccard(left: set[str], right: set[str]) -> float:
    """Jaccard similarity of two sets (0 when either is empty)."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def containment(part: set[str], whole: set[str]) -> float:
    """Share of ``part`` found in ``whole``."""
    return len(part & whole) / len(part) if part else 0.0


def load_chunk_docs(directory: Path = CHUNKS_DIR) -> dict[str, list[dict]]:
    """Map doc_id to its chunk records, read from every chunk JSON file."""
    docs: dict[str, list[dict]] = {}
    for path in sorted(directory.glob("doc*.json")):
        for record in json.loads(path.read_text(encoding="utf-8")):
            docs.setdefault(record["doc_id"], []).append(record)
    return docs


def doc_title(records: list[dict]) -> str:
    """Most common source_title among a doc's chunks."""
    return Counter(record["source_title"] for record in records).most_common(1)[0][0]


def extract_pdf_texts(pdf_dir: Path, cache_path: Path | None) -> dict[str, str]:
    """Extract text from every PDF, reusing a cache keyed by file hash."""
    sys.path.insert(0, str(ROOT))
    from pdf_to_text import extract_text

    cache: dict[str, str] = {}
    if cache_path and cache_path.is_file():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    texts: dict[str, str] = {}
    for pdf in sorted(pdf_dir.iterdir()):
        if not pdf.is_file() or ".pdf" not in pdf.name.lower():
            continue
        key = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if key not in cache:
            try:
                cache[key] = extract_text(pdf)
            except Exception as exc:  # noqa: BLE001 - one broken PDF must not stop the run
                log.warning("could not extract %s: %s", pdf.name, exc)
                cache[key] = ""
        texts[pdf.name] = cache[key]
    if cache_path:
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
    return texts


@dataclass(frozen=True)
class Match:
    """Best PDF candidate for one doc and whether it was accepted."""

    doc_id: str
    pdf: str | None
    score: float
    runner_up: float
    accepted: bool
    reason: str


def _rank(target: set[str], pool: dict[str, set[str]], measure=jaccard) -> list[tuple[float, str]]:
    return sorted(((measure(target, other), name) for name, other in pool.items()), reverse=True)


def match_documents(
    doc_texts: dict[str, str],
    chunk_texts: dict[str, str],
    pdf_texts: dict[str, str],
) -> dict[str, Match]:
    """Pair each doc with its source PDF, or explain why no pair was accepted."""
    pdf_sets = {name: shingles(text) for name, text in pdf_texts.items()}
    pdf_trigrams = {name: shingles(text, 3) for name, text in pdf_texts.items()}
    spaced = {name: char_shingles(text) for name, text in pdf_texts.items() if is_letter_spaced(text)}
    pdf_words = {name: words(text) for name, text in pdf_texts.items()}

    matches: dict[str, Match] = {}
    for doc_id, text in sorted(doc_texts.items()):
        ranked = _rank(shingles(text), pdf_sets)
        method = "word shingles"
        chunk_text = chunk_texts.get(doc_id, "")
        chunk_rank = _rank(shingles(chunk_text, 3), pdf_trigrams, containment)
        if spaced and (not ranked or ranked[0][0] < MATCH_THRESHOLD):
            spaced_ranked = _rank(char_shingles(text), spaced)
            if spaced_ranked and spaced_ranked[0][0] >= MATCH_THRESHOLD:
                ranked = spaced_ranked
                method = "character shingles on a letter-spaced PDF"
                chunk_rank = _rank(char_shingles(chunk_text), spaced, containment)
        if not ranked:
            matches[doc_id] = Match(doc_id, None, 0.0, 0.0, False, "no PDFs to compare")
            continue
        score, name = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        doc_words = words(text)
        exact = [other for other, tokens in pdf_words.items() if tokens == doc_words]
        chunk_score = dict((pdf, value) for value, pdf in chunk_rank).get(name, 0.0)
        if score < MATCH_THRESHOLD:
            reason = f"best score {score:.2f} is below {MATCH_THRESHOLD}"
        elif score - runner_up < MIN_MARGIN and exact != [name]:
            reason = f"ambiguous, runner-up `{ranked[1][1]}` scored {runner_up:.2f}"
        elif chunk_rank and chunk_score < chunk_rank[0][0] - CHUNK_TOLERANCE:
            reason = f"chunk text points to `{chunk_rank[0][1]}` instead"
        elif score - runner_up < MIN_MARGIN:
            reason = f"accepted: exact text match, {method}"
        else:
            reason = f"accepted: {method}"
        matches[doc_id] = Match(doc_id, name, score, runner_up, reason.startswith("accepted"), reason)
    return matches


def build_registry(
    chunk_docs: dict[str, list[dict]],
    sources: dict[str, str],
    matches: dict[str, Match],
    web_sources: dict[str, dict] | None = None,
) -> list[dict]:
    """Assemble one registry entry per chunked doc, sorted by doc_id."""
    entries = []
    web_sources = web_sources or {}
    for doc_id in sorted(chunk_docs):
        pdf = sources.get(doc_id)
        if pdf is None and doc_id in matches and matches[doc_id].accepted:
            pdf = matches[doc_id].pdf
        url = web_sources.get(doc_id, {}).get("url")
        if url is None and pdf:
            url = filename_to_url(pdf).url
        entries.append(
            {
                "doc_id": doc_id,
                "title": doc_title(chunk_docs[doc_id]),
                "source_url": url,
                "pdf": pdf,
                "chunks": len(chunk_docs[doc_id]),
            }
        )
    return entries


def render_report(entries: list[dict], matches: dict[str, Match], pdf_names: list[str]) -> str:
    """Markdown tables of matched, unmatched, low-confidence and unused items."""
    titles = {entry["doc_id"]: entry["title"] for entry in entries}
    ordered = sorted(matches.values(), key=lambda m: m.doc_id)
    shared = Counter(entry["pdf"] for entry in entries if entry["pdf"])
    lines = ["### Recovered matches", "", "| doc | PDF | score | runner-up | note |", "| --- | --- | --- | --- | --- |"]
    for match in ordered:
        if match.accepted:
            note = match.reason.removeprefix("accepted: ")
            if shared[match.pdf] > 1:
                note = f"{note}; PDF shared by {shared[match.pdf]} docs"
            lines.append(f"| {match.doc_id} | `{match.pdf}` | {match.score:.2f} | {match.runner_up:.2f} | {note} |")
    lines += ["", "### Unmatched docs", "", "| doc | title | best candidate | reason |", "| --- | --- | --- | --- |"]
    for match in ordered:
        if not match.accepted:
            lines.append(f"| {match.doc_id} | {titles.get(match.doc_id, '')} | `{match.pdf}` | {match.reason} |")
    lines += ["", "### Low-confidence URLs", "", "| doc | URL | concern |", "| --- | --- | --- |"]
    for entry in entries:
        if entry["pdf"]:
            guess = filename_to_url(entry["pdf"])
            if guess.concerns:
                lines.append(f"| {entry['doc_id']} | {guess.url or 'null'} | {'; '.join(guess.concerns)} |")
    unused = [name for name in pdf_names if name not in shared]
    lines += ["", f"### PDFs with no chunked doc ({len(unused)})", ""]
    lines += [f"- `{name}`" for name in unused]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=REGISTRY, help="registry JSON path")
    parser.add_argument("--report", type=Path, help="write a markdown match report here")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="PDF text cache file")
    parser.add_argument("--no-cache", action="store_true", help="always re-extract PDFs")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    chunk_docs = load_chunk_docs()
    sources = json.loads(DOC_SOURCES.read_text(encoding="utf-8"))
    web_sources = json.loads(WEB_SOURCES.read_text(encoding="utf-8"))
    pdf_texts = extract_pdf_texts(RAW_PDF_DIR, None if args.no_cache else args.cache)
    claimed = set(sources.values())
    candidates = {name: text for name, text in pdf_texts.items() if name not in claimed}
    pending = [doc_id for doc_id in chunk_docs if doc_id not in sources and doc_id not in web_sources]
    doc_texts = {
        doc_id: (RAW_TEXT_DIR / f"{doc_id}.txt").read_text(encoding="utf-8")
        for doc_id in pending
        if (RAW_TEXT_DIR / f"{doc_id}.txt").is_file()
    }
    chunk_texts = {doc_id: " ".join(r["text"] for r in chunk_docs[doc_id]) for doc_id in pending}
    matches = match_documents(doc_texts, chunk_texts, candidates)
    entries = build_registry(chunk_docs, sources, matches, web_sources)
    args.output.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    accepted = sum(match.accepted for match in matches.values())
    log.info("wrote %d entries to %s", len(entries), args.output)
    log.info("recovered %d of %d older docs; %d unmatched", accepted, len(pending), len(pending) - accepted)
    if args.report:
        args.report.write_text(render_report(entries, matches, sorted(pdf_texts)), encoding="utf-8")
        log.info("report written to %s", args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
