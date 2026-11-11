from copy import deepcopy
import unittest

from backend.app.retrieval_support.precision import rerank


def candidate(chunk_id, program, score):
    return {
        "chunk_id": chunk_id,
        "doc_id": f"doc-{chunk_id}",
        "text": f"Requirements for {program}.",
        "source_title": f"B.S. in {program}",
        "section_heading": "Graduation Requirements",
        "retrieval_score": score,
        "estimated_tokens": 20,
    }


def test_requested_program_ranks_above_wrong_program():
    candidates = [
        candidate("engineering", "Computer Engineering", 0.50),
        candidate("science", "Computer Science", 0.45),
    ]

    results = rerank("Computer Science requirements", candidates)

    assert results[0]["chunk_id"] == "science"


def test_inputs_and_original_fields_are_preserved():
    candidates = [
        candidate("engineering", "Computer Engineering", 0.50),
        candidate("science", "Computer Science", 0.45),
    ]
    original = deepcopy(candidates)

    results = rerank("Computer Science requirements", candidates)

    assert candidates == original
    originals = {item["chunk_id"]: item for item in original}
    assert len(results) == len(original)
    assert {item["chunk_id"] for item in results} == set(originals)

    for result in results:
        source = originals[result["chunk_id"]]
        assert result is not source
        for key, value in source.items():
            assert result[key] == value


def test_equal_scores_use_chunk_id_for_stable_order():
    candidates = [
        candidate("b", "Computer Science", 0.45),
        candidate("a", "Computer Science", 0.45),
    ]

    results = rerank("Computer Science requirements", candidates)

    assert [item["chunk_id"] for item in results] == ["a", "b"]


def test_comparing_both_programs_does_not_penalize_either():
    candidates = [
        candidate("engineering", "Computer Engineering", 0.50),
        candidate("science", "Computer Science", 0.45),
    ]

    results = rerank(
        "Compare Computer Science and Computer Engineering",
        candidates,
    )

    for result in results:
        assert result["precision_score"] == result["retrieval_score"]

def test_catalog_ranges_allow_spacing_and_multiple_years():
    from backend.app.retrieval_support.precision import _catalog_ranges

    assert _catalog_ranges(
        "Compare 2016 - 2018 with 2020–2021"
    ) == {
        ("2016", "2018"),
        ("2020", "2021"),
    }
    assert _catalog_ranges("No catalog year specified") == set()
def test_catalog_mismatch_is_penalized_independently():
    candidates = [
        candidate(
            "wrong-year",
            "Computer Science Degree Plan (2021-2022 Catalog)",
            0.45,
        ),
        candidate(
            "requested-year",
            "Computer Science Degree Plan (2020-2021 Catalog)",
            0.45,
        ),
    ]

    results = rerank(
        "Compare Computer Science 2016-2018 with 2020-2021",
        candidates,
        use_program=False,
    )
    scores = {h["chunk_id"]: h["precision_score"] for h in results}

    assert scores["requested-year"] == 0.45
    assert scores["wrong-year"] < scores["requested-year"]


def test_unspecified_query_year_does_not_penalize_catalog():
    candidates = [
        candidate(
            "science",
            "Computer Science Degree Plan (2021-2022 Catalog)",
            0.45,
        )
    ]

    results = rerank(
        "Computer Science requirements",
        candidates,
        use_program=False,
    )

    assert results[0]["precision_score"] == 0.45


def test_unknown_candidate_catalog_stays_neutral():
    candidates = [candidate("science", "Computer Science", 0.45)]

    results = rerank(
        "Computer Science requirements for 2020-2021",
        candidates,
        use_program=False,
    )

    assert results[0]["precision_score"] == 0.45


def test_features_can_be_disabled():
    candidates = [
        candidate(
            "engineering",
            "Computer Engineering (2021-2022 Catalog)",
            0.50,
        )
    ]

    results = rerank(
        "Computer Science 2020-2021 requirements",
        candidates,
        use_program=False,
        use_catalog=False,
    )

    assert results[0]["precision_score"] == 0.50


def test_sufficiency_rejects_empty_and_title_only_evidence():
    from backend.app.retrieval_support.precision import evidence_reason

    query = "Computer Engineering plan 2025-2026 calculus requirements"
    assert evidence_reason(query, []) is not None
    assert evidence_reason(query, [{"source_title": query, "text": ""}]) is not None
    assert evidence_reason(query, [{"source_title": query,
                                   "text": "Home. Links. Search."}]) is not None


def test_sufficiency_does_not_combine_unrelated_program_and_year():
    from backend.app.retrieval_support.precision import evidence_reason

    query = "Computer Engineering plan 2025-2026 calculus requirements"
    hits = [
        {"source_title": "Computer Engineering plan 2019-2020",
         "text": "Calculus requirements include a minimum grade of C or better."},
        {"source_title": "Computer Science plan 2025-2026",
         "text": "Calculus requirements include a minimum grade of C or better."},
    ]
    original = deepcopy(hits)
    assert evidence_reason(query, hits) is not None
    assert hits == original


def test_sufficiency_requires_every_requested_catalog():
    from backend.app.retrieval_support.precision import evidence_reason

    query = "Compare Computer Science plan electives for 2016-2018 and 2020-2021"
    hits = [{"source_title": "Computer Science plan 2016-2018",
             "text": "Students must complete eleven hours of electives approved by an advisor."}]
    assert evidence_reason(query, hits) is not None
    hits.append({"source_title": "Computer Science plan 2020-2021",
                 "text": "Students must complete ten hours of electives approved by an advisor."})
    assert evidence_reason(query, hits) is None


def test_sufficiency_requires_both_standing_and_declaration_facets():
    from backend.app.retrieval_support.precision import evidence_reason

    query = "At 53 credits what is my class standing and when must I declare a major?"
    declaration = {"text": "Students must declare a major by 54 semester credit hours."}
    standing = {"text": "Sophomore students have completed 30-53 semester credit hours."}
    assert evidence_reason(query, [declaration]) is not None
    assert evidence_reason(query, [standing]) is not None
    assert evidence_reason(query, [standing, declaration]) is None
    assert evidence_reason(query, [{"text": standing["text"] + " " + declaration["text"]}]) is None


def test_sufficiency_requires_eligibility_and_documents_across_sources():
    from backend.app.retrieval_support.precision import evidence_reason

    query = "Am I eligible and what documents do I need?"
    eligibility = {"doc_id": "a", "text": "To be eligible applicants must hold a bachelor's degree."}
    documents = {"doc_id": "b", "text": "Applicants must submit official transcripts and two reference letters."}
    assert evidence_reason(query, [eligibility]) is not None
    assert evidence_reason(query, [documents]) is not None
    assert evidence_reason(query, [eligibility, documents]) is None
    assert evidence_reason(query, [{"text": "Eligibility and documents are listed in the menu."}]) is not None


def test_unrecognized_question_defers_to_existing_checks():
    from backend.app.retrieval_support.precision import evidence_reason

    assert evidence_reason("How do I pay tuition?", [{"text": "Payment information."}]) is None


def test_catalog_quantities_accept_paraphrases_without_filler_word_overlap():
    from backend.app.retrieval_support.precision import evidence_reason

    hits = [{"source_title": "Computer Science degree plan 2020-2021",
             "text": "The degree requires 124 hours and totals 73 lower-division and 51 upper-division hours."}]
    original = deepcopy(hits)
    for query in (
        "Give its lower/upper division breakdown for the Computer Science degree plan 2020-2021.",
        "For Computer Science 2020-2021, report the degree plan's lower and upper division quantities.",
        "Computer Science catalog 2020-2021: describe lower-division versus upper-division amounts.",
    ):
        assert evidence_reason(query, hits) is None
    assert hits == original


def test_catalog_quantities_require_body_facts_and_allow_scoped_multiple_passages():
    from backend.app.retrieval_support.precision import evidence_reason

    query = "Computer Science plan 2020-2021 lower and upper division totals"
    lower = {"source_title": "Computer Science plan 2020-2021",
             "text": "The applicable degree plan requires 73 lower-division hours of approved coursework."}
    upper = {"source_title": "Computer Science plan 2020-2021",
             "text": "The applicable degree plan requires 51 upper-division hours of approved coursework."}
    assert evidence_reason(query, [lower]) is not None
    assert evidence_reason(query, [lower, upper]) is None
    wrong_scope = {**upper, "source_title": "Computer Science plan 2021-2022"}
    assert evidence_reason(query, [lower, wrong_scope]) is not None
    navigation = {"source_title": query + " 73 lower-division 51 upper-division",
                  "text": "Browse the catalog menu and contact an advisor to learn more about requirements."}
    assert evidence_reason(query, [navigation]) is not None


def test_program_comparison_needs_both_programs_in_the_shared_catalog():
    from backend.app.retrieval_support.precision import evidence_reason

    query = "Compare Computer Science and Computer Engineering plans in 2016-2018: lower/upper division totals"
    science = {"source_title": "Computer Science plan 2016-2018",
               "text": "The degree totals 67 lower-division and 57 upper-division hours for graduation."}
    engineering = {"source_title": "Computer Engineering plan 2016-2018",
                   "text": "The degree totals 67 lower-division and 59 upper-division hours for graduation."}
    assert evidence_reason(query, [science]) is not None
    assert evidence_reason(query, [science, engineering]) is None


def test_scope_does_not_require_an_explicitly_excluded_program():
    from backend.app.retrieval_support.precision import evidence_reason

    hit = {"source_title": "Computer Science plan 2016-2018",
           "text": "The degree totals 67 lower-division and 57 upper-division hours for graduation."}
    for exclusion in ("Do not substitute the", "Excluding", "Rather than", "Instead of"):
        query = ("Computer Science plan 2016-2018 lower/upper division totals. "
                 + exclusion + " Computer Engineering plan.")
        assert evidence_reason(query, [hit]) is None


def test_catalog_elective_numbers_cannot_come_from_title_or_wrong_year():
    from backend.app.retrieval_support.precision import evidence_reason

    query = "Computer Science plan 2020-2021 elective-hour total"
    navigation = {"source_title": "Computer Science plan 2020-2021: 10 hours of electives",
                  "text": "See the catalog navigation menu and contact an advisor for further details."}
    correct = {"source_title": "Computer Science plan 2020-2021",
               "text": "Students must complete ten hours of electives approved by their academic advisor."}
    assert evidence_reason(query, [navigation]) is not None
    assert evidence_reason(query, [correct]) is None
    assert evidence_reason(query, [{**correct, "source_title": "Computer Science plan 2016-2018"}]) is not None


def test_complete_source_backed_program_comparison_is_not_refused():
    from backend.app.retrieval import ROOT
    from backend.app.retrieval_support.precision import evidence_reason
    from evaluate import evaluate_chunks as ev
    from evaluate.mentee4.hard_cases import load_cases

    chunks = ev.read_chunks(ROOT / "backend/data/chunks")
    case = next(c for c in load_cases(chunks)
                if c["id"] == "mentee4-dev-same-year-degree-totals")
    source_ids = {s["chunk_id"] for s in case["sources"]}
    hits = [c for c in chunks if c["chunk_id"] in source_ids]
    assert ev.grade(case, [{**h, "estimated_tokens": ev.cost(h)} for h in hits])["complete_evidence"] == 1
    assert evidence_reason(case["query"], hits) is None


def test_hard_cases_are_source_backed_and_budget_feasible():
    from backend.app.retrieval import ROOT, _load
    from evaluate import evaluate_chunks as ev
    from evaluate.mentee4.hard_cases import load_cases, validate_cases

    index, _, _, _ = _load()
    chunks = ev.read_chunks(ROOT / "backend/data/chunks")
    cases = load_cases(chunks)
    summary = validate_cases(cases, chunks)
    assert summary["cases"] == 25
    assert summary["answerable"] == 23
    for case in cases:
        if not case["unanswerable"]:
            assert ev.evidence_feasible(case, index.chunks, index.s), case["id"]
    shared = ev.read_questions(ROOT / "evaluate/questions.json", chunks, "dev")
    assert not ({ev.normalize(c["query"]) for c in cases}
                & {ev.normalize(c["query"]) for c in shared})


def test_hard_case_validator_rejects_bad_quotes_ids_and_negative_claims():
    from backend.app.retrieval import ROOT
    from evaluate import evaluate_chunks as ev
    from evaluate.mentee4.hard_cases import load_cases, validate_cases

    chunks = ev.read_chunks(ROOT / "backend/data/chunks")
    cases = load_cases(chunks)
    bad_quote = deepcopy(cases)
    bad_quote[0]["sources"][0]["quote"] = "An invented statement absent from the source."
    with unittest.TestCase().assertRaisesRegex(ValueError, "quote"):
        validate_cases(bad_quote, chunks)
    bad_id = deepcopy(cases)
    bad_id[0]["sources"][0]["chunk_id"] = "nonexistent_chunk"
    with unittest.TestCase().assertRaisesRegex(ValueError, "source ID"):
        validate_cases(bad_id, chunks)
    bad_negative = deepcopy(cases)
    ref = bad_negative[0]["sources"][0]
    negative = bad_negative[0]["hard_negatives"][0]
    negative.update({k: ref[k] for k in ("chunk_id", "doc_id", "quote", "source_title")})
    with unittest.TestCase().assertRaisesRegex(ValueError, "actually supports"):
        validate_cases(bad_negative, chunks)


def test_adapter_switches_preserve_constraints_and_source_fields():
    from collections import Counter
    from dataclasses import replace

    from backend.app.retrieval import _load
    from backend.app.retrieval_support.index import LexicalIndex
    from evaluate.mentee4.adapter import candidate_pool, search

    _, config, _, _ = _load()
    from dataclasses import fields
    from evaluate import evaluate_chunks as ev
    settings = ev.Settings(**{f.name: config[f.name] for f in fields(ev.Settings)})
    settings = replace(settings, min_score=0, context_budget=80, max_per_document=1)
    chunks = [candidate("a", "Computer Engineering (2021-2022)", 0),
              candidate("b", "Computer Science (2020-2021)", 0),
              candidate("c", "Computer Science (2020-2021)", 0)]
    chunks[2]["doc_id"] = chunks[1]["doc_id"]
    index = LexicalIndex(chunks, settings)
    query = "Computer Science 2020-2021 requirements"
    pool = candidate_pool(index, query)
    originals = {h["chunk_id"]: h for h in pool}
    assert search(index, query) == index.search(query, 5)
    for program in (False, True):
        for catalog in (False, True):
            hits = search(index, query, use_precision=True,
                          use_program=program, use_catalog=catalog)
            assert sum(h["estimated_tokens"] for h in hits) <= settings.context_budget
            assert all(n <= 1 for n in Counter(h["doc_id"] for h in hits).values())
            for hit in hits:
                for key, value in originals[hit["chunk_id"]].items():
                    assert hit[key] == value
                direct = rerank(query, [originals[hit["chunk_id"]]],
                                use_program=program, use_catalog=catalog)[0]
                assert hit["precision_score"] == direct["precision_score"]


def test_broader_pool_admits_only_extra_score_eligible_candidates():
    from dataclasses import fields, replace
    from backend.app.retrieval import _load
    from backend.app.retrieval_support.index import LexicalIndex
    from evaluate import evaluate_chunks as ev
    from evaluate.mentee4.adapter import admit_candidates, select_candidates
    from evaluate.mentee4.run_pool_sweep import pool_index

    _, config, _, _ = _load()
    settings = ev.Settings(**{f.name: config[f.name] for f in fields(ev.Settings)})
    settings = replace(settings, candidate_pool=5, min_score=0.3)
    chunks = [candidate(str(i), "Computer Science", 0) for i in range(7)]
    index = LexicalIndex(chunks, settings)
    original_settings = replace(index.s)
    scored = list(enumerate([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.2]))
    wider = pool_index(index, 7)
    before = admit_candidates(index, scored)
    after = admit_candidates(wider, scored)
    assert len(before) == 5
    assert len(after) == 6  # last candidate still fails min_score
    assert after[:5] == before
    assert index.s == original_settings
    assert wider.s.min_score == index.s.min_score
    snapshot = deepcopy(after)
    for enabled in (False, True):
        selected = select_candidates(wider, "Computer Science", after, use_precision=enabled)
        assert after == snapshot
        assert all(h["retrieval_score"] >= 0.3 for h in selected)
        assert sum(h["estimated_tokens"] for h in selected) <= settings.context_budget


def test_scored_candidates_preserve_production_admission_and_stable_ties():
    from dataclasses import fields, replace
    from backend.app.retrieval import _load
    from backend.app.retrieval_support.index import LexicalIndex
    from evaluate import evaluate_chunks as ev
    from evaluate.mentee4.adapter import candidate_pool, scored_candidates

    _, config, _, _ = _load()
    settings = ev.Settings(**{f.name: config[f.name] for f in fields(ev.Settings)})
    settings = replace(settings, candidate_pool=5)
    chunks = [candidate(str(i), "Computer Science", 0) for i in reversed(range(7))]
    index = LexicalIndex(chunks, settings)
    scored = scored_candidates(index, "Computer Science")
    assert [index.chunks[i]["chunk_id"] for i, _ in scored] == [str(i) for i in range(7)]
    admitted = candidate_pool(index, "Computer Science")
    assert len(admitted) == 5
    assert [h["retrieval_score"] for h in admitted] == [score for _, score in scored[:5]]


def load_tests(loader, tests, pattern):
    """Expose function tests to the repository's stdlib-unittest CI job."""
    return unittest.TestSuite(
        unittest.FunctionTestCase(test, description=name)
        for name, test in sorted(globals().items())
        if name.startswith("test_") and callable(test)
    )
