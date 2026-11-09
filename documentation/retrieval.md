# Retrieval service

`backend.app.retrieval.retrieve(query, top_k=5, history=None)` returns the shared
`RetrievalResult`; an abstention always has an empty passage list and a log-only
reason. `corpus_stats()` reports 198 documents, 3,003 chunks and `lexical` for the
current merged corpus. Counts describe the full corpus before chunk-size filters.

## Loading and scoring

The index, configuration and optional source registry load lazily through a
single-entry `functools.lru_cache`. Changes require a process restart; tests can
call `_load.cache_clear()`. Paths resolve against the repository root, independently
of the working directory. No model, network service, GPU or new dependency is
required. Semantic retrieval is intentionally omitted, so the runtime never
downloads models.

The service reuses evaluator tokenization, BM25, TF-IDF cosine, metadata weighting
and MMR. It precomputes lengths, vector norms, metadata tokens and passage costs.
It preserves the per-document cap and counts title, section and passage text in
the 1,200 estimated-token budget. `top_k` must be an integer from 1 through 8.
The optional documents registry supplies HTTP(S) source URLs. Missing, malformed
or invalid entries yield `None`; URLs are never inferred from titles.

## Abstention and follow-ups

The baseline normalizes BM25 by the best candidate, so its score alone is not
an absolute confidence measure. The service combines these checks:

1. Empty, non-string and punctuation-only questions abstain with `empty query`.
2. Deterministic rules reject weather, jokes, explicit code requests, selected
   other-school requests, private record/status questions and unspecified classes.
3. Every explicitly requested four-digit year must occur in the selected evidence.
4. At least one selected passage must cover 25% of the question's content terms,
   using the evaluator tokenizer plus additional generic-word exclusions.
5. At least one passage must score 0.3 or higher. No surviving hits also abstains.

These are transparent heuristics, not calibrated probabilities. There is no
question-ID, reference-evidence or benchmark-answer lookup in the service.
Short elliptical follow-ups, at most 12 words, are appended to the latest user
turn among the last six history items. Assistant text and malformed history
items are ignored. For example, `what about graduate students?` after
`How do I drop a class?` retains the registration topic. This heuristic cannot
resolve all pronouns or changes of subject. Generation receives the original
question and history under the existing API contract.

## Configuration

`backend/retrieval_config.json` contains the same required baseline keys as
`evaluate/config.example.json`:

| Keys | Meaning |
| --- | --- |
| `top_k`, `candidate_pool` | Baseline output default and candidate pool; public `top_k` argument controls runtime output count |
| `bm25_k1`, `bm25_b` | Term-frequency saturation and length normalization |
| `lexical_weight` | BM25 contribution versus TF-IDF cosine |
| `metadata_weight` | Title/section coverage contribution |
| `diversity_lambda` | Relevance versus MMR redundancy penalty |
| `min_score` | Minimum candidate score |
| `max_per_document` | Maximum passages from one document |
| `min_chunk_words`, `max_chunk_words` | Indexing length filters |
| `context_budget` | Estimated context token limit |
| `chunks_path`, `registry_path` | Repository-relative corpus and optional registry paths |
| `min_term_coverage` | Minimum content-term coverage in one hit, 0.25 |
| `min_top_score` | Minimum best selected score, 0.3 |

Missing or invalid corpus/configuration makes retrieval fail closed and logs the
load error. `corpus_stats()` raises on invalid deployment files so health checks
do not claim a usable index. Fix deployment files before accepting traffic.

## Evaluation and retuning

Run from the repository root, using Python 3.12 or later:

```sh
python -m unittest discover -s backend/tests -p 'test_retrieval*.py'
python -m unittest discover -s evaluate -p 'test_*.py'
python scripts/eval_retrieval.py --split dev --json evaluate/runs/retrieval-dev.json
```

Change thresholds or ranking settings using dev only, restart the process between
settings, and compare leaderboard, abstention and complete evidence together.
Inspect false refusals on public procedural questions, not just private-record
accuracy. Keep the context cap fixed and include cold-start time separately from
warm request latency. Once settings are frozen, run test once:

```sh
python scripts/eval_retrieval.py --split test --json evaluate/runs/retrieval-test.json
```

The script calls the production function, converts passages back to evaluator
hits, and uses unchanged `grade()` and `summarize()`. Warm p95 uses nearest rank.
It also records benchmark SHA-256 and per-question diagnostics in optional JSON.

## Final results, November 9, 2026

The merged benchmark has 102 questions per split, including 25 unanswerable
questions each. The task's older 164-question benchmark and baseline numbers are
historical, not a controlled comparison against this expanded corpus/benchmark.
SHA-256: `1bd70731ab578587a9fbc34940157b62b96ed2b2518b86fb62634d8cb4f20385`.

| Metric | Dev | Test, evaluated once |
| --- | ---: | ---: |
| Leaderboard | 61.84 | 59.71 |
| Complete evidence | 0.5714 | 0.6104 |
| Evidence recall | 0.7305 | 0.7554 |
| Context precision | 0.4840 | 0.5385 |
| Abstention correct | 0.7600 | 0.4000 |
| Warm p50, ms | 42.62 | 36.25 |
| Warm p95, ms | 62.35 | 48.37 |

Dev exceeds the requested 55 leaderboard, 0.60 abstention and 0.434 minimum
complete-evidence targets. Test exceeds the historical 53.2 leaderboard threshold.
Test abstention remains weak: 15 of 25 unsupported questions still receive hits.
No settings were changed after that test run. Do not interpret passing the overall
leaderboard as reliable rejection of all unsupported questions.

Verification on Windows, Python 3.13.15: all 84 backend tests passed with one
explicit live-Ollama skip, all 63 evaluator tests passed, 12 API tests passed under
pytest, and all five document-tool tests passed. Benchmark label validation passed.
The added ten tests cover synthetic scoring parity, bad input, unknown terms,
scope, URLs, cache reuse, follow-ups, caps/budget and real-corpus retrieval, plus
real-engine HTTP health/chat/streaming/feedback through an in-process TestClient.
No server was started. A Python 3.12 interpreter was not available locally.

## Hand-off and known gaps

Task 3's existing non-stub engine loader now imports retrieval and generation
successfully. The existing Dockerfile must copy `evaluate/`,
`backend/retrieval_config.json` and `backend/data/documents.json` into the image.
The last file is optional for retrieval but needed for source links. The generation
module also imports `requests`, which the current Dockerfile does not install.
These Task 3-owned files were left untouched as required by the task boundaries.

Rules can miss private-record paraphrases, reject some legitimate requests and
accept unrelated evidence containing a requested year. Other-school detection is
not exhaustive. Multi-part questions may need passages below the candidate cutoff.
There is no claim of semantic search or factual answer verification. The next
retrieval iteration should use new development examples and preserve this test
run as a final result rather than tuning against its errors.
