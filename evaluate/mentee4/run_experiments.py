"""Run fixed dev-only feature ablations without changing production settings.

Run from the repository root:
python3 -m evaluate.mentee4.run_experiments --output evaluate/runs/mentee-4/ablations-dev.json
"""

import argparse
import hashlib
import json
import math
import platform
import statistics
import subprocess
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from backend.app.retrieval import ROOT, _load, retrieve
from backend.app.retrieval_support.query import reject, rewrite
from backend.app.retrieval_support.precision import evidence_reason, rerank
from evaluate import evaluate_chunks as ev
from evaluate.mentee4.adapter import candidate_pool, search
from evaluate.mentee4.hard_cases import CASES_PATH, load_cases

VARIANTS = {
    "baseline": (False, False, False),
    "program_only": (True, False, False),
    "catalog_only": (False, True, False),
    "combined": (True, True, False),
    "sufficiency_only": (False, False, True),
    "combined_sufficiency": (True, True, True),
}


def extra_metrics(questions, rows):
    """Answer precision here means complete labeled evidence, not answer accuracy."""
    labels = {q["id"]: q for q in questions}
    answered = [r for r in rows if r["chunk_ids"]]
    answerable = [r for r in rows if not labels[r["id"]]["unanswerable"]]
    unanswerable = [r for r in rows if labels[r["id"]]["unanswerable"]]
    return {
        "answered_count": len(answered),
        "answered_complete_evidence_precision": (
            sum(r["metrics"]["complete_evidence"] == 1 for r in answered)
            / len(answered) if answered else None
        ),
        "answerable_acceptance_rate": (
            sum(bool(r["chunk_ids"]) for r in answerable) / len(answerable)
            if answerable else None
        ),
        "false_acceptance_rate": (
            sum(bool(r["chunk_ids"]) for r in unanswerable) / len(unanswerable)
            if unanswerable else None
        ),
    }


def run(hard_cases=False):
    _load.cache_clear()
    start = time.perf_counter()
    index, config, _, _ = _load()
    cold_ms = (time.perf_counter() - start) * 1000
    questions_path = CASES_PATH if hard_cases else ROOT / "evaluate/questions.json"
    questions = (load_cases(ev.read_chunks(ROOT / config["chunks_path"])) if hard_cases
                 else ev.read_questions(questions_path, index.chunks, "dev"))
    corpus_hash = hashlib.sha256()
    for path in sorted((ROOT / config["chunks_path"]).glob("*.json")):
        corpus_hash.update(path.name.encode())
        corpus_hash.update(b"\0")
        corpus_hash.update(path.read_bytes())

    variants = {}
    baseline_rows = {}
    for name, (program, catalog, sufficiency) in VARIANTS.items():
        rows, latencies = [], []
        for q in questions:
            start = time.perf_counter()
            query = rewrite(q["query"].strip()[:2000], None)
            selected = search(index, query, use_precision=program or catalog,
                              use_program=program, use_catalog=catalog)
            existing_reason = reject(query, selected, config)
            additional_reason = evidence_reason(query, selected) if sufficiency else None
            reason = existing_reason or additional_reason
            hits = [] if reason else selected
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)

            # Validate pre-rejection selection too; rejection must not hide violations.
            counts = Counter(h["doc_id"] for h in selected)
            assert len(selected) <= 5
            assert sum(h["estimated_tokens"] for h in selected) <= index.s.context_budget
            assert all(n <= index.s.max_per_document for n in counts.values())
            assert all(h["retrieval_score"] > 0 and
                       h["retrieval_score"] >= index.s.min_score for h in selected)

            row = {
                "id": q["id"], "query": q["query"], "reason": reason,
                "existing_reason": existing_reason,
                "additional_reason": additional_reason,
                "chunk_ids": [h["chunk_id"] for h in hits],
                "selected_before_rejection": [
                    {key: h[key] for key in (
                        "chunk_id", "retrieval_score", "estimated_tokens"
                    )} | {"precision_score": h.get("precision_score")}
                    for h in selected
                ],
                "latency_ms": elapsed, "metrics": ev.grade(q, hits),
            }
            if hard_cases:
                # Diagnostics only, after retrieval/timing: labels never affect scoring.
                candidates = candidate_pool(index, query)
                ranked = rerank(query, candidates, use_program=program, use_catalog=catalog)
                precision_positions = {h["chunk_id"]: n for n, h in enumerate(ranked, 1)}
                row["candidate_log"] = [
                    {"chunk_id": h["chunk_id"], "doc_id": h["doc_id"],
                     "retrieval_score": h["retrieval_score"],
                     "precision_score": h["precision_score"],
                     "precision_rank": precision_positions[h["chunk_id"]],
                     "supporting_groups": [n for n, group in enumerate(q["evidence"])
                                           if ev.supports(h, group)]}
                    for h in ranked
                ]
                row["candidate_evidence_covered"] = [
                    any(ev.supports(h, group) for h in candidates) for group in q["evidence"]
                ]
                candidate_ids = {h["chunk_id"] for h in candidates}
                row["hard_negative_candidate_ids"] = [
                    h["chunk_id"] for h in q["hard_negatives"] if h["chunk_id"] in candidate_ids
                ]
            if name == "baseline":
                assert selected == index.search(query, 5), q["id"]
                production = retrieve(q["query"])
                assert row["chunk_ids"] == [p.chunk_id for p in production.passages], q["id"]
                assert reason == production.reason, q["id"]
                production_hits = [
                    {**asdict(p), "estimated_tokens": ev.cost(asdict(p))}
                    for p in production.passages
                ]
                assert row["metrics"] == ev.grade(q, production_hits), q["id"]
                baseline_rows[q["id"]] = row
            rows.append(row)

        changes = []
        for row in rows:
            baseline = baseline_rows[row["id"]]
            if row["chunk_ids"] != baseline["chunk_ids"] or row["reason"] != baseline["reason"]:
                deltas = {
                    key: row["metrics"][key] - baseline["metrics"][key]
                    for key in ("evidence_recall", "complete_evidence", "context_precision",
                                "reciprocal_rank", "abstention_correct")
                    if row["metrics"][key] is not None
                }
                changes.append({"id": row["id"], "deltas": deltas,
                                "regression": any(v < 0 for v in deltas.values()),
                                "new_acceptance_without_labeled_support": (
                                    not baseline["chunk_ids"] and bool(row["chunk_ids"])
                                    and row["metrics"]["evidence_recall"] == 0
                                ),
                                "before": baseline["chunk_ids"], "after": row["chunk_ids"]})
        variants[name] = {
            "summary": ev.summarize(rows), "additional_metrics": extra_metrics(questions, rows),
            "p50_ms": statistics.median(latencies),
            "p95_ms": sorted(latencies)[math.ceil(.95 * len(latencies)) - 1],
            "changes": changes, "rows": rows,
        }

    return {
        "split": "dev", "questions": len(questions),
        "dataset": "mentee4_hard_cases" if hard_cases else "shared_dev",
        "questions_path": str(questions_path.relative_to(ROOT)),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "python": platform.python_version(), "machine": platform.platform(),
        "questions_sha256": hashlib.sha256(questions_path.read_bytes()).hexdigest(),
        "corpus_sha256": corpus_hash.hexdigest(), "settings": config,
        "cold_index_load_ms": cold_ms,
        "parity": "index selection, production IDs/reasons/metrics passed for all dev questions",
        "notes": ["Optional extra sufficiency checks run after selection; existing checks always apply.",
                  "Fixed top_k=5; original candidate pool and score threshold preserved.",
                  "One warm timing sample per question per variant, fixed variant order.",
                  "Timing excludes grading, assertions and production parity calls.",
                  "Complete-evidence precision is a retrieval proxy, not factual answer accuracy."],
        "variants": variants,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hard-cases", action="store_true",
                        help="Use the separate 25-case mentee-4 dev fixture")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "evaluate/runs/mentee-4"):
        parser.error("output must be inside evaluate/runs/mentee-4")
    if output.exists():
        parser.error("output already exists; choose a new filename")
    result = run(hard_cases=args.hard_cases)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    for name, variant in result["variants"].items():
        print(name, json.dumps(variant["summary"]))
        print(" Changed queries:", len(variant["changes"]),
              "Regressions:", sum(c["regression"] for c in variant["changes"]))
    print("Parity:", result["parity"])
    print("Saved:", output)


if __name__ == "__main__":
    main()
