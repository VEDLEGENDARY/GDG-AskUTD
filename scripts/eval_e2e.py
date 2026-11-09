#!/usr/bin/env python3
"""End-to-end benchmark run: retrieval, answer, abstention, citations and latency.

Uses backend.app.retrieval and backend.app.generation when they import. If either is
missing (or --fallback is given), it uses the evaluator's lexical Retriever and a small
extractive sentence picker, so the script always runs offline.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, replace
from functools import partial
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "evaluate"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import evaluate_chunks as ev  # noqa: E402
from backend.app.types import Answer, Citation, Passage, RetrievalResult  # noqa: E402

CHUNKS = ROOT / "backend" / "data" / "chunks"
QUESTIONS = ROOT / "evaluate" / "questions.json"
REGISTRY = ROOT / "backend" / "data" / "documents.json"
FALLBACK_ABSTAIN_TEXT = "I could not find that in the UT Dallas sources I have, so I cannot answer it reliably."
MARKER = re.compile(r"\[(\d+)\]")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])")
MIN_SENTENCE_OVERLAP = 2
ANSWER_SENTENCES = 2
SUPPORT_RATIO = 0.5
SNIPPET_CHARS = 240

log = logging.getLogger("eval_e2e")


@dataclass
class Pipeline:
    """The retrieve and answer callables under test and where each one came from."""

    retrieve: Callable[[str], RetrievalResult]
    answer: Callable[[str, list[Passage]], Answer]
    retriever_name: str
    generator_name: str


def key_terms(text: str) -> set[str]:
    """Content words (evaluator tokenizer, no stop words, longer than two characters)."""
    return {term for term in ev.tokens(MARKER.sub(" ", text)) if len(term) > 2}


def load_registry_urls(path: Path = REGISTRY) -> dict[str, str | None]:
    """Map doc_id to source_url from documents.json, or nothing if it is absent."""
    if not path.exists():
        return {}
    return {doc["doc_id"]: doc.get("source_url") for doc in json.loads(path.read_text(encoding="utf-8"))}


def baseline_retrieve(chunks: list[dict], top_k: int) -> Callable[[str], RetrievalResult]:
    """Wrap the evaluator's lexical Retriever in the shared retrieve() contract."""
    retriever = ev.Retriever(chunks, replace(ev.load_settings(), top_k=top_k))
    urls = load_registry_urls()

    def retrieve(query: str) -> RetrievalResult:
        passages = [
            Passage(
                chunk_id=hit["chunk_id"],
                doc_id=hit["doc_id"],
                text=hit["text"],
                source_title=hit.get("source_title", ""),
                section_heading=hit.get("section_heading", ""),
                score=round(hit["retrieval_score"], 4),
                source_url=urls.get(hit["doc_id"]),
            )
            for hit in retriever.retrieve(query)
        ]
        reason = None if passages else "no passage above min_score"
        return RetrievalResult(passages=passages, abstain=not passages, reason=reason)

    return retrieve


def make_citation(n: int, passage: Passage) -> Citation:
    """Citation for the passage shown to the reader as [n]."""
    return Citation(
        n=n,
        chunk_id=passage.chunk_id,
        doc_id=passage.doc_id,
        title=passage.source_title,
        section=passage.section_heading,
        snippet=passage.text[:SNIPPET_CHARS],
        source_url=passage.source_url,
    )


def extractive_answer(question: str, passages: list[Passage], abstain_text: str = FALLBACK_ABSTAIN_TEXT) -> Answer:
    """Answer with the passage sentences that share the most key terms with the question."""
    terms = key_terms(question)
    scored = []
    for n, passage in enumerate(passages, 1):
        for sentence in SENTENCE_BREAK.split(passage.text):
            overlap = len(terms & key_terms(sentence))
            if overlap >= MIN_SENTENCE_OVERLAP:
                scored.append((overlap, n, sentence.strip()))
    if not scored:
        return Answer(text=abstain_text, abstained=True)
    best = sorted(scored, key=lambda item: (-item[0], item[1]))[:ANSWER_SENTENCES]
    text = " ".join(f"{sentence} [{n}]" for _, n, sentence in best)
    cited = sorted({n for _, n, _ in best})
    return Answer(text=text, citations=[make_citation(n, passages[n - 1]) for n in cited])


def load_pipeline(chunks: list[dict], top_k: int, fallback: bool = False) -> Pipeline:
    """Prefer the real backend modules; fall back per module when one is unavailable."""
    retrieval = generation = None
    if not fallback:
        try:
            from backend.app import retrieval
        except ImportError as exc:
            log.warning("backend.app.retrieval unavailable (%s); using the evaluator Retriever", exc)
        try:
            from backend.app import generation
        except ImportError as exc:
            log.warning("backend.app.generation unavailable (%s); using the extractive picker", exc)
    if retrieval is not None:
        retrieve = partial(retrieval.retrieve, top_k=top_k)
        retriever_name = str(retrieval.corpus_stats().get("retriever", "backend.app.retrieval"))
    else:
        retrieve, retriever_name = baseline_retrieve(chunks, top_k), "evaluator-lexical"
    if generation is not None:
        answer, generator_name = generation.generate_answer, generation.llm_status()
    else:
        answer, generator_name = extractive_answer, "extractive-fallback"
    return Pipeline(retrieve, answer, retriever_name, generator_name)


def citation_report(answer: Answer, passages: list[Passage]) -> dict:
    """Check that each [n] resolves to a retrieved passage and that it backs its sentence."""
    by_n = {citation.n: citation for citation in answer.citations}
    retrieved = {passage.chunk_id: passage for passage in passages}
    markers = [int(n) for n in MARKER.findall(answer.text)]
    orphans = sorted({n for n in markers if n not in by_n or by_n[n].chunk_id not in retrieved})
    checked = supported = 0
    for sentence in SENTENCE_BREAK.split(answer.text):
        cited = {int(n) for n in MARKER.findall(sentence)} - set(orphans)
        terms = key_terms(sentence)
        if not cited or not terms:
            continue
        checked += 1
        shared = max(len(terms & key_terms(retrieved[by_n[n].chunk_id].text)) for n in cited)
        supported += shared / len(terms) >= SUPPORT_RATIO
    return {
        "markers": len(markers),
        "orphan_markers": orphans,
        "citation_valid": None if answer.abstained else bool(markers) and not orphans,
        "citation_support": supported / checked if checked else None,
    }


def evaluate_question(question: dict, pipeline: Pipeline) -> dict:
    """Run one benchmark question through the pipeline and grade every stage."""
    start = time.perf_counter()
    result = pipeline.retrieve(question["query"])
    retrieved_at = time.perf_counter()
    passages = [] if result.abstain else list(result.passages)
    answer = pipeline.answer(question["query"], passages)
    done = time.perf_counter()
    hits = [
        {"chunk_id": p.chunk_id, "doc_id": p.doc_id, "text": p.text,
         "source_title": p.source_title, "section_heading": p.section_heading}
        for p in passages
    ]
    for hit in hits:
        hit["estimated_tokens"] = ev.cost(hit)
    return {
        "question": question,
        "metrics": ev.grade(question, hits),
        "retrieval_abstained": result.abstain,
        "retrieval_reason": result.reason,
        "retrieved": [{"chunk_id": p.chunk_id, "doc_id": p.doc_id, "score": p.score} for p in passages],
        "answer": asdict(answer),
        "answer_abstention_correct": answer.abstained == question["unanswerable"],
        **citation_report(answer, passages),
        "answer_words": len(MARKER.sub(" ", answer.text).split()),
        "retrieval_ms": round((retrieved_at - start) * 1000, 1),
        "generation_ms": round((done - retrieved_at) * 1000, 1),
        "latency_ms": round((done - start) * 1000, 1),
    }


def mean(values: list) -> float | None:
    """Average of the non-null values, or None when there are none."""
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def summarize(rows: list[dict]) -> dict:
    """Aggregate retrieval, abstention, citation and latency metrics."""
    answerable = [row for row in rows if not row["question"]["unanswerable"]]
    unanswerable = [row for row in rows if row["question"]["unanswerable"]]
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "questions": len(rows),
        "retrieval": ev.summarize(rows),
        "answer_abstention_accuracy": mean([row["answer_abstention_correct"] for row in rows]),
        "answered_when_answerable": mean([not row["answer"]["abstained"] for row in answerable]),
        "abstained_when_unanswerable": mean([row["answer"]["abstained"] for row in unanswerable]),
        "citation_valid": mean([row["citation_valid"] for row in rows]),
        "citation_support": mean([row["citation_support"] for row in rows]),
        "answer_words_mean": mean([row["answer_words"] for row in rows]),
        "latency_ms_p50": statistics.median(latencies) if latencies else None,
        "latency_ms_p95": latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None,
    }


def fmt(value: float | None, digits: int = 3) -> str:
    """Table cell for a possibly missing number."""
    return "n/a" if value is None else f"{value:.{digits}f}"


def render(summary: dict, pipeline: Pipeline, split: str) -> str:
    """Markdown summary table, ready to paste into a PR."""
    retrieval = summary["retrieval"]
    rows = [
        ("split", split),
        ("retriever", pipeline.retriever_name),
        ("generator", pipeline.generator_name),
        ("questions", str(summary["questions"])),
        ("retrieval leaderboard score", fmt(retrieval["leaderboard_score"], 2)),
        ("evidence recall", fmt(retrieval["evidence_recall"])),
        ("complete evidence", fmt(retrieval["complete_evidence"])),
        ("context precision", fmt(retrieval["context_precision"])),
        ("retrieval abstention (unanswerable)", fmt(retrieval["abstention_correct"])),
        ("answer abstention accuracy", fmt(summary["answer_abstention_accuracy"])),
        ("answered when answerable", fmt(summary["answered_when_answerable"])),
        ("abstained when unanswerable", fmt(summary["abstained_when_unanswerable"])),
        ("citation validity", fmt(summary["citation_valid"])),
        ("citation support", fmt(summary["citation_support"])),
        ("mean answer words", fmt(summary["answer_words_mean"], 1)),
        ("latency p50 ms", fmt(summary["latency_ms_p50"], 1)),
        ("latency p95 ms", fmt(summary["latency_ms_p95"], 1)),
    ]
    lines = ["| metric | value |", "| --- | --- |"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="End-to-end AskUTD benchmark run.")
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--limit", type=int, help="only the first N questions of the split")
    parser.add_argument("--json", type=Path, dest="json_path", help="write per-question results here")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--fallback", action="store_true",
                        help="skip backend.app and use the offline retriever and extractive picker")
    parser.add_argument("--chunks", type=Path, default=CHUNKS)
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(levelname)s %(message)s")

    chunks = ev.read_chunks(args.chunks)
    questions = ev.read_questions(args.questions, chunks, args.split)[: args.limit]
    pipeline = load_pipeline(chunks, args.top_k, args.fallback)
    rows = [evaluate_question(question, pipeline) for question in questions]
    summary = summarize(rows)
    sys.stdout.write(render(summary, pipeline, args.split))
    if args.json_path:
        payload = {
            "split": args.split,
            "retriever": pipeline.retriever_name,
            "generator": pipeline.generator_name,
            "top_k": args.top_k,
            "summary": summary,
            "results": rows,
        }
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log.info("Per-question results written to %s", args.json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
