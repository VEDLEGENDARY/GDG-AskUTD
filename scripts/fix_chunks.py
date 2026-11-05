#!/usr/bin/env python3
"""Clean chunk files for docs 119 onward (web pages split by ``add_documents.py``).

Steps per doc, in order: replace breadcrumb or truncated titles, strip page
furniture (site footers, menus, chatbot prompts, table counters, icon glyphs),
repair headings that are really sentence fragments or table rows, drop repeated
sentences within the doc, drop letter-spaced or navigation-only chunks, and merge
short fragments into a neighbour. Chunk ids of kept chunks never change.
Changed files are re-counted with ``fill_chunk_counts.process``.

Usage:
    python scripts/fix_chunks.py [--docs 119-198] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = ROOT / "backend" / "data" / "chunks"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_corpus import doc_number, letter_spaced, navigation_like, normalized, parse_range  # noqa: E402

FIRST_ALLOWED_DOC = 119
FRAGMENT_WORDS = 30
MIN_KEEP_WORDS = 8
MAX_MERGED_WORDS = 250
MIN_DEDUPE_SENTENCE_WORDS = 6

REGISTRAR = "Office of the Registrar"
FINAID = "Office of Financial Aid"
CAREER = "University Career Center"
SUCCESS = "Student Success Center"
ADMISSION = "Office of Admission and Enrollment"
TITLES = {
    "doc120": "UT Dallas Course Catalogs",
    "doc123": "Transferring Credits to UT Dallas (Transfer Admissions)",
    "doc124": f"{FINAID}: Aid Programs",
    "doc125": f"{FINAID}: Cost of Attendance Calculator",
    "doc126": f"{FINAID}: Forms",
    "doc127": f"{FINAID}: Maintaining Aid",
    "doc128": f"{FINAID}: Receiving Aid",
    "doc129": f"{FINAID}: Resources",
    "doc130": f"{FINAID}: Scholarships",
    "doc131": f"{REGISTRAR}: Frequently Asked Questions",
    "doc132": f"{REGISTRAR}: Final Exam Assignments",
    "doc133": f"{REGISTRAR}: Electronic Forms and Other Resources",
    "doc134": f"{REGISTRAR}: Apply for Graduation",
    "doc135": f"{REGISTRAR}: Legislative Policies",
    "doc136": f"{REGISTRAR}: Texas Three Course Repeat Rule",
    "doc137": f"{REGISTRAR}: Texas 6-Withdrawals Rule",
    "doc138": f"{REGISTRAR}: FERPA",
    "doc139": f"{REGISTRAR}: Vaccination Requirement for Bacterial Meningitis",
    "doc140": f"{REGISTRAR}: Registration Procedures",
    "doc141": f"{REGISTRAR}: Academic Advising",
    "doc142": f"{REGISTRAR}: Audit a Course",
    "doc143": f"{REGISTRAR}: Online Drop/Withdrawal Process for Undergraduate Students",
    "doc144": f"{REGISTRAR}: Schedule Planner",
    "doc145": f"{REGISTRAR}: Special Programs",
    "doc146": f"{REGISTRAR}: Establishing Texas Residency",
    "doc147": f"{REGISTRAR}: Residency FAQ",
    "doc148": f"{REGISTRAR}: Residency Glossary",
    "doc149": f"{REGISTRAR}: Transcripts",
    "doc150": f"{REGISTRAR}: Official Transcripts",
    "doc151": f"{REGISTRAR}: Transcripts FAQ",
    "doc152": f"{REGISTRAR}: Unofficial Transcripts",
    "doc153": f"{REGISTRAR}: Transfer Credit Evaluation",
    "doc154": "Transfer Credit: A and AS Level Exam Credit",
    "doc155": "Transfer Credit: Advanced Placement (AP) Exam Credit",
    "doc156": "Transfer Credit: CLEP Exam Credit",
    "doc157": "Transfer Credit: International Baccalaureate (IB) Exam Credit",
    "doc158": "Transfer Credit Tool Tips",
    "doc159": "Transfer Student Services: Financial Aid and Scholarships",
    "doc160": "UT Dallas Academic Calendar",
    "doc161": "UT Dallas Admissions: Become a Comet",
    "doc162": "UT Dallas Galaxy Portal",
    "doc163": f"{FINAID}: Contact Us",
    "doc164": f"{REGISTRAR}: Graduation FAQs",
    "doc165": f"{REGISTRAR}: Excessive Hours",
    "doc166": f"{REGISTRAR}: Texas Tuition Rebate",
    "doc167": f"{REGISTRAR}: Residency Documentation",
    "doc168": f"{REGISTRAR}: Notarization of Transcripts and Diplomas",
    "doc169": "UT Dallas Academics",
    "doc170": f"{CAREER}: 12twenty@UTDallas for Students",
    "doc171": "Naveen Jindal School of Management: Academic Advising",
    "doc172": f"{SUCCESS}: Academic Success Coaching",
    "doc173": "School of Interdisciplinary Studies: Advisors",
    "doc174": f"{CAREER}: Career Fairs",
    "doc175": "UT Dallas Comet Promise",
    "doc176": f"{CAREER}: Comet Treks",
    "doc177": "UT Dallas Costs, Scholarships and Aid",
    "doc178": "Eugene McDermott Library",
    "doc179": "Undergraduate Education: Exploratory Advising",
    "doc180": f"{ADMISSION}: Freshman Scholarships",
    "doc181": "UT Dallas Student Union",
    "doc182": "University Housing: Housing Availability",
    "doc183": f"{CAREER}: International Students",
    "doc184": "Jonsson School of Engineering and Computer Science: Undergraduate Advising",
    "doc185": f"{SUCCESS}: Peer Tutoring",
    "doc186": SUCCESS,
    "doc187": f"{SUCCESS}: Supplemental Instruction",
    "doc188": "UT Dallas Testing Center",
    "doc189": FINAID,
    "doc190": f"{ADMISSION}: Transfer Scholarships",
    "doc191": "Undergraduate Education: Undergraduate Academic Advisors",
    "doc192": "Bass School of Arts, Humanities, and Technology: Undergraduate Advising",
    "doc193": "School of Natural Sciences and Mathematics: Undergraduate Advising",
    "doc194": "School of Behavioral and Brain Sciences: Undergraduate Advising",
    "doc195": "School of Economic, Political and Policy Sciences: Undergraduate Advising",
    "doc196": "UT Dallas University Housing",
    "doc197": "UT Dallas University Recreation",
    "doc198": f"{SUCCESS}: Writing Center",
}

_FOOTER_PHRASES = [
    r"Related Pages\.?", r"Privacy Policy", r"Office of the Registrar\.?", r"Login to Intranet\.?",
    r"© The University of Texas at Dallas\.?", r"Contact Us\.?", r"CONTACT US",
    r"800 W(?:est|\.)? Campbell R(?:oa)?d\.?,?", r"Richardson, (?:Texas|TX) 75080(?:-3021)?\.?",
    r"972-883-2111", r"Emergency Preparedness", r"Forms", r"Campus Carry", r"Campus Health Promotion",
    r"Campus Police", r"Required links", r"Questions or comments about this page\?",
    r"STAY CONNECTED WITH UT DALLAS", r"RESOURCES", r"Tobacco-Free Campus", r"UT System",
    r"Texas Veterans Portal\.?", r"Work at UT Dallas", r"Parking", r"Nondiscrimination Policy",
    r"Title IX Initiatives", r"Org\. Chart", r"A-Z Index", r"Student Achievements", r"HEERF Reporting",
    r"Counseling/Mental Health\.?", r"Report Concern for a Student", r"Safety", r"Hazing Prevention\.?",
    r"Public Course and Syllabus Information", r"Institutional Resume",
]
FOOTER_RUN = re.compile(r"(?:(?:%s)\s*)+" % "|".join(_FOOTER_PHRASES))
FOOTER_MARKER = re.compile(r"Privacy Policy|©|Related Pages|Required links|Login to Intranet")

_MENU_PHRASES = [
    "Deadlines", "Forms", "Code of Conduct", "FINANCIAL AID", "FATV", "Grants", "Loans", "Waivers",
    "Work Study", "Estimated Costs", "Apply", "Verification", "FAQ", "Hazlewood", "Federal Benefits",
    "Veteran Forms", "VA FAQ Listing", "Transfer Students", "Academic Excellence", "McDermott Scholars",
    "Parents", "Consumer Info", "Rights and Responsibilities", "HEERF Reporting", "AID PROGRAMS",
    "TOPICS", "VETERANS", "SCHOLARSHIPS", "RESOURCES",
]
MENU_RUN = re.compile(r"(?:\b(?:%s)\b\.?\s*){4,}" % "|".join(re.escape(p) for p in _MENU_PHRASES))

STRIP_PATTERNS = [
    re.compile(r"May I help you\?\s*Hi there!\s*I.m a chatbot here to answer your questions\.\s*What would you like to know\?"),
    re.compile(r"\bShowing \d+ to \d+ of \d+ entries\b"),
    re.compile(r"\bUpdated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} v[\w.]+"),
    re.compile(r"\b(?:VIEW|APPLY|LEARN|VISIT|SEE|EXPLORE)(?: [A-Z’']{2,}| UT| TO)+\b\s*\.?"),
    re.compile(r"[\ue000-\uf8ff▲▼]"),
    re.compile(r"\b(?:st|nd|rd|th)(?: (?:st|nd|rd|th))+\b|»"),
    re.compile(r"(?:\b\d+ )?UCC[-:].{0,160}?@utdcareercenter Posts Followers Following Follow Load more\.?"),
    re.compile(r"Need Support\? Incoming Student Current Student Contact Us OUE Contacts Email Us ¿Hablas español\?"),
    re.compile(r"Helpful Links Account Login Library Staff Login Pay Fines Frequently Asked Questions"
               r" Employment Site Index Stay Connected Support the Libraries"),
    re.compile(r"ABOUT Leadership Corporate Partners At a Glance Facilities Contact ACADEMICS .{0,300}?CAMPUS MAP GIVING"),
    re.compile(r"Stay Connected #utdstudentunion Load more|UPCOMING EVENTS \|"),
]

CHROME_HEADINGS = {"Office of the Registrar", "Related Pages", "FINANCIAL AID", "APPLY NOW", "Go to Galaxy"}
BAD_HEADING = re.compile(
    r"[\u2014†^*@]|^\d|\d{3}-\d{3}-\d{4}"
    r"|\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?\s?\d"
    r"|^(?:Spring|Summer|Fall) \d{4}$"
    r"|(?:\b(?:and|or|of|the|for|to|in|a|an|with|under|Please|Legislative)|[–\-&,(:])$"
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(“])")

log = logging.getLogger("fix_chunks")


def word_count(text: str) -> int:
    """Number of whitespace-separated words."""
    return len(text.split())


def tidy(text: str) -> str:
    """Collapse whitespace and stray spaces before punctuation."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,;:?!])", r"\1", text)
    return re.sub(r"([.,;:])(?:\s*[.,;:])+", r"\1", text).strip(" ,;")


def strip_furniture(text: str) -> str:
    """Remove site footers, menus, widgets and glyphs; keep real content."""
    for pattern in STRIP_PATTERNS:
        text = pattern.sub(" ", text)
    text = MENU_RUN.sub(" ", text)
    text = FOOTER_RUN.sub(lambda m: " " if FOOTER_MARKER.search(m.group(0)) else m.group(0), text)
    return tidy(text)


def heading_is_bad(heading: str) -> bool:
    """Headings that are table rows, contact lines, dates or cut-off sentences."""
    return bool(BAD_HEADING.search(heading.strip()))


def repair_headings(chunks: list[dict]) -> int:
    """Fold bad headings back into the text and inherit the previous good heading."""
    repaired, previous = 0, "Overview"
    for chunk in chunks:
        heading = chunk["section_heading"].strip()
        if heading in CHROME_HEADINGS or " > " in heading:
            chunk["section_heading"] = previous
            repaired += 1
        elif heading_is_bad(heading):
            joiner = " " if re.match(r"[a-z]", chunk["text"]) else ". "
            chunk["text"] = tidy(heading.rstrip(" .") + joiner + chunk["text"])
            chunk["section_heading"] = previous
            repaired += 1
        else:
            previous = heading
    return repaired


def drop_repeated_sentences(chunks: list[dict]) -> int:
    """Remove long statements already present in an earlier chunk of the same doc.

    Questions are kept because FAQ pages legitimately repeat prompts such as
    'What do I need to do?' under different answers. A chunk left holding only
    questions after removal is emptied, since its answers live elsewhere.
    """
    seen: set[str] = set()
    removed = 0
    for chunk in chunks:
        kept, dropped_here = [], 0
        for sentence in SENTENCE_SPLIT.split(chunk["text"]):
            key = normalized(sentence)
            repeatable = sentence.rstrip().endswith("?") or len(key.split()) < MIN_DEDUPE_SENTENCE_WORDS
            if not repeatable and key in seen:
                dropped_here += 1
                continue
            seen.add(key)
            kept.append(sentence)
        if dropped_here and all(sentence.rstrip().endswith("?") for sentence in kept):
            kept = []
        removed += dropped_here
        chunk["text"] = tidy(" ".join(kept))
    return removed


def merge_fragments(chunks: list[dict]) -> tuple[list[dict], int]:
    """Fold chunks under FRAGMENT_WORDS into the previous (or next) chunk."""
    result: list[dict] = []
    merged = 0
    pending: dict | None = None
    for chunk in chunks:
        if pending is not None:
            chunk["text"] = tidy(pending["text"] + " " + chunk["text"])
            pending = None
        small = word_count(chunk["text"]) < FRAGMENT_WORDS
        if small and result and word_count(result[-1]["text"]) + word_count(chunk["text"]) <= MAX_MERGED_WORDS:
            result[-1]["text"] = tidy(result[-1]["text"] + " " + chunk["text"])
            merged += 1
        elif small and not result and len(chunks) > 1:
            pending = chunk
            merged += 1
        else:
            result.append(chunk)
    if pending is not None:
        result.append(pending)
        merged -= 1
    return result, merged


def clean_doc(doc_id: str, chunks: list[dict]) -> tuple[list[dict], Counter]:
    """Apply every cleaning step to one doc's chunks and count what changed."""
    stats: Counter = Counter()
    title = TITLES.get(doc_id)
    for chunk in chunks:
        if title and chunk["source_title"] != title:
            chunk["source_title"] = title
            stats["titles"] += 1
        if letter_spaced(chunk["text"]):
            chunk["text"] = ""
            stats["letter_spaced_dropped"] += 1
            continue
        cleaned = strip_furniture(chunk["text"])
        if cleaned != chunk["text"]:
            stats["furniture_stripped"] += 1
            chunk["text"] = cleaned
            if not cleaned:
                stats["navigation_dropped"] += 1
    chunks = [c for c in chunks if c["text"]]
    stats["headings_repaired"] = repair_headings(chunks)
    stats["sentences_deduped"] = drop_repeated_sentences(chunks)

    kept = []
    for chunk in chunks:
        empty = word_count(chunk["text"]) < MIN_KEEP_WORDS
        if (empty or navigation_like(chunk["text"])) and (len(kept) + 1 < len(chunks) or kept):
            stats["navigation_dropped"] += 1
            continue
        kept.append(chunk)
    kept, stats["fragments_merged"] = merge_fragments(kept)
    return kept, +stats


def fix_file(path: Path, dry_run: bool) -> Counter:
    """Clean one chunk file in place; returns the change counts."""
    original = json.loads(path.read_text(encoding="utf-8"))
    chunks = [dict(chunk) for chunk in original]
    doc_id = chunks[0]["doc_id"]
    cleaned, stats = clean_doc(doc_id, chunks)
    stats["chunks_before"], stats["chunks_after"] = len(original), len(cleaned)
    if cleaned != original and not dry_run:
        from fill_chunk_counts import process

        path.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if process(path) != 0:
            raise RuntimeError(f"fill_chunk_counts rejected {path.name}")
        stats["written"] = 1
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docs", default=f"{FIRST_ALLOWED_DOC}-999", help="inclusive doc number range")
    parser.add_argument("--chunks", type=Path, default=CHUNKS_DIR, help="chunk directory")
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    low, high = parse_range(args.docs) or (FIRST_ALLOWED_DOC, 999)
    if low < FIRST_ALLOWED_DOC:
        parser.error(f"docs below doc{FIRST_ALLOWED_DOC} are hand-chunked and must not be changed")
    totals: Counter = Counter()
    for path in sorted(args.chunks.glob("doc*.json")):
        if not low <= doc_number(path.name[:6]) <= high:
            continue
        stats = fix_file(path, args.dry_run)
        totals.update(stats)
        changes = {k: v for k, v in stats.items() if k not in {"chunks_before", "chunks_after", "written"}}
        if changes:
            log.info("%s: %d -> %d chunks %s", path.name, stats["chunks_before"], stats["chunks_after"], dict(changes))
    log.info("total: %s", dict(totals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
