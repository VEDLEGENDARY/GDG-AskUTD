#!/usr/bin/env python3
"""Compare baseline and query-understanding rewrites on the owned dev set."""
from __future__ import annotations

import argparse
from dataclasses import asdict, fields
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.retrieval_support.index import LexicalIndex
from backend.app.retrieval_support import query as query_support
from backend.app.types import Turn
from evaluate import evaluate_chunks as ev

CASE_FILE = Path(__file__).with_name("development_cases.json")
CONFIG_FILE = ROOT / "backend/retrieval_config.json"
CHUNKS_DIR = ROOT / "backend/data/chunks"
BASELINE_REF = "a3d9817d129db5945aa0d60c1dbd8cfddeae3588"


def legacy_rewrite(query: str, history: list[Turn] | None) -> str:
    """The pre-assignment behavior, captured from the baseline commit."""
    if len(query.split()) > 12 or not re.search(
            r"^(?:what about|how about|and\b|what if|does (?:that|it)|can (?:they|i)|is (?:that|it))|\b(?:that|those|it)\b",
            query, re.I):
        return query
    if isinstance(history, list):
        for turn in reversed(history[-6:]):
            if isinstance(turn, Turn) and turn.role == "user" and isinstance(turn.content, str) and turn.content.strip():
                return turn.content[:500] + " " + query
    return query


def legacy_reject(query: str, hits: list[dict], config: dict) -> str | None:
    """The baseline reject logic before library-location evidence checking."""
    q = query_support
    if q.OUTSIDE.search(query):
        return "out of scope"
    if q.PERSONAL.search(query):
        return "private record or missing course context"
    if not hits:
        return "no evidence above score threshold"
    evidence = " ".join(ev.context_text(hit) for hit in hits)
    years = re.findall(r"\b20\d{2}\b", query)
    if any(year not in evidence for year in years):
        return "requested year absent from evidence"
    terms = set(ev.tokens(query)) - q.STOP
    coverage = max((len(terms & set(ev.tokens(ev.context_text(hit)))) / max(1, len(terms))
                    for hit in hits), default=0)
    if coverage < config["min_term_coverage"]:
        return "weak query term coverage"
    if max(hit["retrieval_score"] for hit in hits) < config["min_top_score"]:
        return "weak top evidence score"
    return None


def load_cases(chunks: list[dict]) -> list[dict]:
    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    chunk_ids = {chunk["chunk_id"] for chunk in chunks}
    if len(cases) < 25:
        raise ValueError("The Mentee 3 development set must contain at least 25 cases")
    ids = set()
    for case in cases:
        if case["id"] in ids:
            raise ValueError(f"Duplicate case id: {case['id']}")
        ids.add(case["id"])
        unknown_forbidden = set(case.get("forbidden_chunk_ids", [])) - chunk_ids
        if unknown_forbidden:
            raise ValueError(f"{case['id']}: unknown forbidden chunk IDs: {sorted(unknown_forbidden)}")
        if case["unanswerable"] == bool(case["evidence"]):
            raise ValueError(f"{case['id']}: answerability and evidence labels disagree")
        for evidence in case["evidence"]:
            if not any(ev.supports(chunk, evidence) for chunk in chunks):
                raise ValueError(f"{case['id']}: evidence label is not present in this corpus: {evidence}")
        normalized_history = []
        for item in case.get("history", []):
            if (isinstance(item, dict) and isinstance(item.get("role"), str)
                    and isinstance(item.get("content"), str)):
                normalized_history.append(Turn(item["role"], item["content"]))
            else:
                normalized_history.append(item)
        case["history"] = normalized_history
    return cases


def evaluate_case(case: dict, mode: str, index: LexicalIndex, config: dict) -> dict:
    started = time.perf_counter()
    history = case["history"]
    if mode == "baseline":
        query = legacy_rewrite(case["query"], history)
        reject = legacy_reject
    elif mode == "no_aliases":
        query = query_support._rewrite(case["query"], history, use_aliases=False, use_history=True)
        reject = query_support.reject
    elif mode == "no_history":
        query = query_support._rewrite(case["query"], history, use_aliases=True, use_history=False)
        reject = query_support.reject
    else:
        query = query_support.rewrite(case["query"], history)
        reject = query_support.reject
    hits = index.search(query, config["top_k"])
    reason = reject(query, hits, config)
    if reason:
        hits = []
    metrics = ev.grade(case, hits)
    evidence_found = [any(ev.supports(hit, group) for hit in hits) for group in case["evidence"]]
    forbidden = set(case.get("forbidden_chunk_ids", []))
    forbidden_retrieved = sorted(forbidden & {hit["chunk_id"] for hit in hits})
    accepted = bool(hits) and reason is None
    return {
        "id": case["id"], "category": case["category"], "query": case["query"],
        "rewritten": query, "accepted": accepted, "rejection_reason": reason,
        "retrieved_chunk_ids": [hit["chunk_id"] for hit in hits],
        "evidence_found": evidence_found, "forbidden_retrieved_chunk_ids": forbidden_retrieved,
        "metrics": metrics,
        "elapsed_ms": (time.perf_counter() - started) * 1000,
    }


def summarize(cases: list[dict], rows: list[dict], latency_samples: list[float]) -> dict:
    expected = {case["id"]: case for case in cases}
    answerable = [row for row in rows if not expected[row["id"]]["unanswerable"]]
    controls = [row for row in rows if expected[row["id"]]["unanswerable"]]
    answer_recall = [bool(row["evidence_found"]) and all(row["evidence_found"]) for row in answerable]
    latencies = sorted(latency_samples)
    percentile = lambda p: latencies[max(0, math.ceil(p * len(latencies)) - 1)] if latencies else 0
    return {
        "cases": len(rows), "answerable": len(answerable), "unanswerable_controls": len(controls),
        "answerable_complete_evidence_rate": sum(answer_recall) / max(1, len(answer_recall)),
        "answerable_false_rejections": sum(not row["accepted"] for row in answerable),
        "lost_answerable_cases": [row["id"] for row, found in zip(answerable, answer_recall) if not found],
        "false_acceptances": sum(row["accepted"] for row in controls),
        "false_acceptance_cases": [row["id"] for row in controls if row["accepted"]],
        "population_leakage_cases": [row["id"] for row in answerable if row["forbidden_retrieved_chunk_ids"]],
        "correct_abstentions": sum(not row["accepted"] for row in controls),
        "mean_context_precision_answerable": sum(row["metrics"]["context_precision"] or 0 for row in answerable) / max(1, len(answerable)),
        "mean_reciprocal_rank_answerable": sum(row["metrics"]["reciprocal_rank"] or 0 for row in answerable) / max(1, len(answerable)),
        "mean_context_tokens": sum(row["metrics"]["estimated_tokens"] for row in rows) / max(1, len(rows)),
        "warmed_latency_ms_p50": percentile(0.50), "warmed_latency_ms_p95": percentile(0.95),
    }


def warmed_latency_samples(cases: list[dict], mode: str, index: LexicalIndex, config: dict) -> list[float]:
    """Warm the index path, then time ten repeat passes over every case."""
    for case in cases:
        evaluate_case(case, mode, index, config)
    samples = []
    for _ in range(10):
        for case in cases:
            samples.append(evaluate_case(case, mode, index, config)["elapsed_ms"])
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evaluate/mentee3/latest.json"))
    args = parser.parse_args()
    config = ev.read_json(CONFIG_FILE)
    settings = ev.Settings(**{field.name: config[field.name] for field in fields(ev.Settings)})
    settings.validate()
    chunks = ev.read_chunks(CHUNKS_DIR)
    cases = load_cases(chunks)
    cold_started = time.perf_counter()
    index = LexicalIndex(chunks, settings)
    cold_index_load_seconds = time.perf_counter() - cold_started
    modes = ("baseline", "no_aliases", "no_history", "new")
    started = time.perf_counter()
    rows = {mode: [evaluate_case(case, mode, index, config) for case in cases] for mode in modes}
    latencies = {mode: warmed_latency_samples(cases, mode, index, config) for mode in modes}
    summary = {mode: summarize(cases, results, latencies[mode]) for mode, results in rows.items()}
    report = {
        "baseline_ref": BASELINE_REF,
        "python_version": platform.python_version(), "machine": platform.platform(),
        "settings": asdict(settings),
        "corpus_sha256": hashlib.sha256(json.dumps(chunks, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "development_cases_sha256": hashlib.sha256(CASE_FILE.read_bytes()).hexdigest(),
        "elapsed_seconds": time.perf_counter() - started,
        "cold_index_load_seconds": cold_index_load_seconds,
        "warmed_latency_repetitions_per_case": 10,
        "run_failures": 0,
        "summary": summary,
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "report": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
