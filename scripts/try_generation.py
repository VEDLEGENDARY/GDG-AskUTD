#!/usr/bin/env python3
"""Manual demo: retrieve passages for a question and print the generated, cited answer.

Usage:
    python scripts/try_generation.py "How do I drop a class?"
    LLM_PROVIDER=extractive python scripts/try_generation.py --stream "How do I get a transcript?"
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import generation  # noqa: E402
from backend.app.llm import PROVIDERS  # noqa: E402
from backend.app.types import Answer, Passage  # noqa: E402

logger = logging.getLogger("askutd.try_generation")


class _FallbackWatcher(logging.Handler):
    """Notices when generation falls back to the extractive provider."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.fell_back = False

    def emit(self, record: logging.LogRecord) -> None:
        if "falling back to extractive" in record.getMessage():
            self.fell_back = True


def _baseline_passages(question: str, top_k: int) -> list[Passage]:
    sys.path.insert(0, str(ROOT / "evaluate"))
    import evaluate_chunks as baseline

    settings = baseline.load_settings(baseline.DEFAULT_CONFIG)
    settings = dataclasses.replace(settings, top_k=top_k, candidate_pool=max(settings.candidate_pool, top_k))
    chunks = baseline.read_chunks(ROOT / "backend" / "data" / "chunks")
    rows = baseline.Retriever(chunks, settings).retrieve(question)
    return [Passage(chunk_id=row["chunk_id"], doc_id=row["doc_id"], text=row["text"],
                    source_title=row.get("source_title", ""), section_heading=row.get("section_heading", ""),
                    score=float(row.get("retrieval_score", 0.0)))
            for row in rows]


def retrieve_passages(question: str, top_k: int) -> tuple[list[Passage], str]:
    """Use backend/app/retrieval.py when present, otherwise the baseline evaluator retriever."""
    if (ROOT / "backend" / "app" / "retrieval.py").exists():
        try:
            from backend.app import retrieval

            result = retrieval.retrieve(question, top_k=top_k)
            return ([] if result.abstain else list(result.passages)), "backend.app.retrieval"
        except Exception:
            logger.exception("backend.app.retrieval failed, using the baseline retriever")
    return _baseline_passages(question, top_k), "baseline (evaluate/evaluate_chunks.py)"


def _show(answer: Answer, streamed: bool) -> None:
    if not streamed:
        print(answer.text)
    print(f"\nAbstained: {answer.abstained}")
    if answer.citations:
        print("\nCitations:")
    for citation in answer.citations:
        print(f"[{citation.n}] {citation.title} | {citation.section} ({citation.chunk_id})")
        print(f"    {citation.snippet}")
        if citation.source_url:
            print(f"    {citation.source_url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", nargs="+", help="question to ask")
    parser.add_argument("--top-k", type=int, default=5, choices=range(1, 9), metavar="1-8")
    parser.add_argument("--provider", choices=PROVIDERS[:3], help="override LLM_PROVIDER")
    parser.add_argument("--stream", action="store_true", help="print tokens as they arrive")
    args = parser.parse_args()

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING").upper(),
                        format="%(levelname)s %(name)s: %(message)s")
    watcher = _FallbackWatcher()
    logging.getLogger("askutd").addHandler(watcher)
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider

    question = " ".join(args.question)
    passages, retriever = retrieve_passages(question, args.top_k)
    configured = generation.llm_status()
    print(f"Retriever: {retriever}")
    print(f"Passages: {len(passages)}")
    print("\nAnswer:")
    if args.stream:
        answer = None
        for event in generation.stream_answer(question, passages):
            if event["type"] == "token":
                print(event["text"], end="", flush=True)
            else:
                answer = event["answer"]
        print()
    else:
        answer = generation.generate_answer(question, passages)
    _show(answer, args.stream)
    used = f"extractive (fallback, {configured} was unavailable)" if watcher.fell_back else configured
    print(f"\nProvider: {used}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
