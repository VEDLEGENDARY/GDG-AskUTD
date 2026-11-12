"""Validate source-backed mentee-4 fixtures without changing shared labels."""

import json
from collections import Counter
from pathlib import Path

from backend.app.retrieval import ROOT, _load
from evaluate import evaluate_chunks as ev

CASES_PATH = Path(__file__).with_name("hard_cases.json")


def validate_cases(cases, chunks):
    """Check exact quotes, scoped labels, negative claims and fixture diversity."""
    by_id = {c["chunk_id"]: c for c in chunks}
    if len(cases) < 25:
        raise ValueError("At least 25 cases are required")
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    if len({ev.normalize(c["query"]) for c in cases}) != len(cases):
        raise ValueError("Duplicate queries")
    for case in cases:
        if case["split"] != "dev":
            raise ValueError("Hard cases must be dev-only")
        if not case["hard_negatives"]:
            raise ValueError(f"{case['id']}: missing explicit hard negatives")
        refs = (case.get("sources", []) + case.get("ambiguity_sources", [])
                + case["hard_negatives"])
        for ref in refs:
            source = by_id.get(ref["chunk_id"])
            if source is None or source["doc_id"] != ref["doc_id"]:
                raise ValueError(f"{case['id']}: invalid source ID")
            if not ref["quote"] or ref["quote"] not in source["text"]:
                raise ValueError(f"{case['id']}: quote is not exact source text")
            if ref["source_title"] != source.get("source_title", ""):
                raise ValueError(f"{case['id']}: source title differs")

        if case["unanswerable"]:
            if case["evidence"] or len(case.get("ambiguity_sources", [])) < 2:
                raise ValueError("Ambiguity requires competing sources and no unique-answer evidence")
            if not case.get("unanswerable_reason") or not case.get("expected_behavior"):
                raise ValueError("Ambiguous cases need an explanation and expected behavior")
        else:
            covered = set()
            for source in case["sources"]:
                group = source["group"]
                if not 0 <= group < len(case["evidence"]):
                    raise ValueError("Invalid evidence group")
                if not ev.supports(by_id[source["chunk_id"]], case["evidence"][group]):
                    raise ValueError("Cited source does not satisfy its evidence group")
                if not ev.supports({"doc_id": source["doc_id"], "text": source["quote"]},
                                   case["evidence"][group]):
                    raise ValueError("Cited quote does not establish its evidence group")
                covered.add(group)
            if not case["evidence"] or covered != set(range(len(case["evidence"]))):
                raise ValueError("Every required evidence group needs a source quote")

        for negative in case["hard_negatives"]:
            if not negative["reason"]:
                raise ValueError("Every negative needs an explanation")
            groups = negative["unsupported_groups"]
            if not case["unanswerable"] and not groups:
                raise ValueError("An answerable negative must identify its unsupported facets")
            for group in groups:
                if not 0 <= group < len(case["evidence"]):
                    raise ValueError("Invalid negative evidence group")
                if ev.supports(by_id[negative["chunk_id"]], case["evidence"][group]):
                    raise ValueError("Hard negative actually supports its supposedly missing facet")

    categories = Counter(c["category"] for c in cases)
    if not all(categories[name] for name in (
        "wrong_program", "wrong_year", "wrong_population", "compound",
        "cross_document", "navigation", "ambiguous_time", "ambiguous_program",
    )):
        raise ValueError("Missing a required challenge category")
    return {"cases": len(cases), "answerable": sum(not c["unanswerable"] for c in cases),
            "ambiguous": sum(c["unanswerable"] for c in cases),
            "categories": dict(categories)}


def load_cases(chunks):
    cases = ev.read_questions(CASES_PATH, chunks, "dev")
    validate_cases(cases, chunks)
    return cases


def main():
    index, _, _, _ = _load()
    corpus = ev.read_chunks(ROOT / "backend/data/chunks")
    cases = load_cases(corpus)
    summary = validate_cases(cases, corpus)
    summary["infeasible_ids"] = [
        c["id"] for c in cases
        if not c["unanswerable"] and not ev.evidence_feasible(c, index.chunks, index.s)
    ]
    shared_dev = ev.read_questions(ROOT / "evaluate/questions.json", corpus, "dev")
    summary["duplicate_shared_dev_queries"] = sorted(
        {ev.normalize(c["query"]) for c in cases}
        & {ev.normalize(c["query"]) for c in shared_dev}
    )
    print(json.dumps(summary, indent=2))
    if summary["infeasible_ids"] or summary["duplicate_shared_dev_queries"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
