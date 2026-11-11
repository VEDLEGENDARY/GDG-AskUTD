"""Dev-only 50/100/200/full-index candidate sweep at fixed production thresholds."""

import argparse
import hashlib
import json
import math
import platform
import statistics
import subprocess
import time
from collections import Counter
from copy import copy
from dataclasses import replace
from pathlib import Path

from backend.app.retrieval import ROOT, _load, retrieve
from backend.app.retrieval_support.precision import evidence_reason
from backend.app.retrieval_support.query import reject, rewrite
from evaluate import evaluate_chunks as ev
from evaluate.mentee4.adapter import admit_candidates, scored_candidates, select_candidates
from evaluate.mentee4.hard_cases import CASES_PATH, load_cases
from evaluate.mentee4.run_experiments import VARIANTS, extra_metrics


def pool_index(index, limit):
    """Share read-only scoring features; copy only experimental settings."""
    experiment = copy(index)
    experiment.s = replace(index.s, candidate_pool=limit)
    experiment.s.validate()
    return experiment


def summarize(questions, rows):
    summary = ev.summarize(rows)
    values = [r["precision_at_5"] for r in rows if r["precision_at_5"] is not None]
    summary["precision_at_5"] = statistics.mean(values)
    return {"summary": summary, "additional_metrics": extra_metrics(questions, rows),
            "p50_ms": statistics.median(r["latency_ms"] for r in rows),
            "p95_ms": sorted(r["latency_ms"] for r in rows)[math.ceil(.95*len(rows))-1],
            "rows": rows}


def changes(before, after):
    result = []
    for old, new in zip(before, after):
        assert old["id"] == new["id"]
        if old["chunk_ids"] == new["chunk_ids"] and old["reason"] == new["reason"]:
            continue
        deltas = {key: new["metrics"][key] - old["metrics"][key]
                  for key in ("evidence_recall", "complete_evidence", "context_precision",
                              "reciprocal_rank", "abstention_correct")
                  if old["metrics"][key] is not None}
        result.append({"id": old["id"], "before": old["chunk_ids"],
                       "after": new["chunk_ids"], "deltas": deltas,
                       "regression": any(v < 0 for v in deltas.values())})
    return result


def run():
    _load.cache_clear()
    start = time.perf_counter()
    index, config, _, _ = _load()
    cold_ms = (time.perf_counter()-start)*1000
    original_settings = replace(index.s)
    limits = [50, 100, 200, index.n]
    indexes = {limit: pool_index(index, limit) for limit in limits}
    corpus = ev.read_chunks(ROOT / config["chunks_path"])
    question_sets = {
        "shared_dev": (ROOT / "evaluate/questions.json",
                       ev.read_questions(ROOT / "evaluate/questions.json", corpus, "dev")),
        "hard_cases": (CASES_PATH, load_cases(corpus)),
    }
    datasets = {}
    for dataset, (path, questions) in question_sets.items():
        rows = {limit: {variant: [] for variant in VARIANTS} for limit in limits}
        diagnostics = []
        for q in questions:
            start = time.perf_counter()
            query = rewrite(q["query"].strip()[:2000], None)
            scored = scored_candidates(index, query)
            scoring_ms = (time.perf_counter()-start)*1000
            pools = {limit: admit_candidates(experiment, scored)
                     for limit, experiment in indexes.items()}
            for limit, experiment in indexes.items():
                for variant, (program, catalog, sufficiency) in VARIANTS.items():
                    start = time.perf_counter()
                    selected = select_candidates(experiment, query, pools[limit],
                                                 use_precision=program or catalog,
                                                 use_program=program, use_catalog=catalog)
                    existing = reject(query, selected, config)
                    additional = evidence_reason(query, selected) if sufficiency else None
                    reason = existing or additional
                    hits = [] if reason else selected
                    selection_ms = (time.perf_counter()-start)*1000
                    counts = Counter(h["doc_id"] for h in selected)
                    assert len(selected) <= 5
                    assert sum(h["estimated_tokens"] for h in selected) <= index.s.context_budget
                    assert all(n <= index.s.max_per_document for n in counts.values())
                    assert all(h["retrieval_score"] > 0 and
                               h["retrieval_score"] >= index.s.min_score for h in selected)
                    if variant == "baseline":
                        assert selected == experiment.search(query, 5), q["id"]
                        if limit == 50:
                            production = retrieve(q["query"])
                            assert [h["chunk_id"] for h in hits] == [h.chunk_id for h in production.passages]
                            assert reason == production.reason
                    rows[limit][variant].append({
                        "id": q["id"], "query": q["query"], "reason": reason,
                        "existing_reason": existing, "additional_reason": additional,
                        "chunk_ids": [h["chunk_id"] for h in hits],
                        "selected_before_rejection": [
                            {"chunk_id": h["chunk_id"], "retrieval_score": h["retrieval_score"],
                             "precision_score": h.get("precision_score"),
                             "estimated_tokens": h["estimated_tokens"]} for h in selected],
                        "metrics": ev.grade(q, hits),
                        "precision_at_5": (sum(any(ev.supports(h, group) for group in q["evidence"])
                                               for h in hits)/5 if not q["unanswerable"] else None),
                        "scoring_ms": scoring_ms, "selection_and_checks_ms": selection_ms,
                        "latency_ms": scoring_ms + selection_ms,
                    })
            # Labels are inspected only for diagnostics after retrieval and timing.
            coverage = {
                str(limit): [any(ev.supports(h, group) for h in pool) for group in q["evidence"]]
                for limit, pool in pools.items()
            }
            diagnostics.append({
                "id": q["id"], "query": q["query"], "coverage": coverage,
                "admitted_counts": {str(limit): len(pool) for limit, pool in pools.items()},
                "admitted_ids": {str(limit): [h["chunk_id"] for h in pool]
                                 for limit, pool in pools.items()},
                "score_eligible_in_full_index": len(pools[index.n]),
                "supporting_candidates_by_group": [
                    [{"chunk_id": index.chunks[i]["chunk_id"], "initial_rank": rank,
                      "retrieval_score": score,
                      "passes_score_threshold": score > 0 and score >= index.s.min_score}
                     for rank, (i, score) in enumerate(scored, 1)
                     if ev.supports(index.chunks[i], group)] for group in q["evidence"]
                ],
            })
        results = {}
        for limit in limits:
            variants = {}
            for name in VARIANTS:
                value = summarize(questions, rows[limit][name])
                value["changes_vs_pool_50"] = changes(rows[50][name], rows[limit][name])
                variants[name] = value
            coverages = [d["coverage"][str(limit)] for d in diagnostics if d["coverage"][str(limit)]]
            results[str(limit)] = {
                "variants": variants,
                "mean_admitted": statistics.mean(d["admitted_counts"][str(limit)] for d in diagnostics),
                "max_admitted": max(d["admitted_counts"][str(limit)] for d in diagnostics),
                "candidate_evidence_recall": statistics.mean(sum(c)/len(c) for c in coverages),
                "candidate_complete_evidence": statistics.mean(all(c) for c in coverages),
            }
        datasets[dataset] = {
            "questions": len(questions), "questions_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "pools": results, "candidate_diagnostics": diagnostics,
        }
        print("Finished", dataset, flush=True)
    assert index.s == original_settings
    assert _load()[1] == config
    digest = hashlib.sha256()
    for path in sorted((ROOT / config["chunks_path"]).glob("*.json")):
        digest.update(path.name.encode()); digest.update(b"\0"); digest.update(path.read_bytes())
    return {
        "split": "dev", "pool_limits": limits, "full_index_pool": index.n,
        "settings": config, "corpus_sha256": digest.hexdigest(), "cold_index_load_ms": cold_ms,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "python": platform.python_version(), "machine": platform.platform(),
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (Path(__file__), Path(__file__).with_name("adapter.py"),
                                    ROOT / "backend/app/retrieval_support/precision.py")},
        "notes": ["Only candidate count changes; original score threshold and context constraints stay fixed.",
                  "Full-index pool still applies min_score=0.3; it is not unrestricted context selection.",
                  "One scoring sample per query is reused across pools and variants; admission and parity checks excluded from timing.",
                  "Reported latency is scoring plus selection/checks, not production end-to-end latency.",
                  "Precision@5 divides relevant returned passages by 5, including empty slots; context precision uses actual hit count.",
                  "Index selection parity checked for every pool; production IDs/reasons checked at pool 50.",
                  "No test split or model service used."],
        "datasets": datasets,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "evaluate/runs/mentee-4") or output.exists():
        parser.error("Choose a fresh output file inside evaluate/runs/mentee-4")
    result = run()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    for dataset, data in result["datasets"].items():
        for limit, value in data["pools"].items():
            print(dataset, "pool", limit, "max admitted", value["max_admitted"],
                  "candidate recall", value["candidate_evidence_recall"],
                  "combined", value["variants"]["combined"]["summary"])
    print("Saved:", output)


if __name__ == "__main__":
    main()
