# Mentee 3 handoff: query understanding

## Summary

Implemented on branch `codex/mentee-3-query-understanding`, based on mentor baseline `a3d9817d129db5945aa0d60c1dbd8cfddeae3588`.

The query rewriter now adds a small set of corpus-supported terms while retaining the student's words: `undergrad`/`graduate`, singular `class`/`course` in an explicit registration or drop action, `sign up`/registration wording, and `waitlist`/`wait list`. It expands a full-semester or whole-university withdrawal only when the query explicitly describes that scope. A request about dropping one class is never changed into a university withdrawal.

Follow-ups continue to use only prior user turns. A population in a follow-up replaces the prior population, while a clearly different subject such as the library does not inherit a registration topic. Rewriting is idempotent, and a direct call with a question longer than 500 characters returns it unchanged. The chat request schema already limits normal generation requests to 500 characters, so this avoids silently cutting conditions for valid app requests without growing a query beyond that boundary.

Rejection checks now distinguish public instructions such as “How do I request my transcript?” and “Where do I find my enrollment appointment?” from personal record questions. A requested year must occur in evidence that also overlaps the query's topic terms. A library location question abstains if retrieved evidence only mentions library services or a room inside the library.

## Alias provenance

- `undergrad` and `grad` are common short forms of the undergraduate and graduate populations named separately in the Registrar's *Registering for Classes* chunks (`doc110`).
- `class` and `course` both occur in the add/drop and withdrawal policies in the *2025-2026 Undergraduate Catalog* (`doc011`) and Registrar's *Dropping a Class* page (`doc108`). Expansion is limited to singular forms in explicit registration/drop contexts because broad plural expansion reduced retrieval of an online drop instruction during development.
- `sign up` is expanded only when the phrase names a class or course; the Registrar's registration pages describe this process as registering/enrolling in classes.
- `waitlist`/`wait list` variants are supported by the Registrar's *Registration Procedures* (`doc140`) and Schedule Planner registration page (`doc144`).
- Full-university withdrawal wording is supported by the *Undergraduate Catalog* withdrawal section (`doc011`) and the *Texas 6-Withdrawals Rule* (`doc137`), which explicitly distinguishes a complete university withdrawal from a course withdrawal.
- `UTD` is retained rather than expanded. The current lexical tokenizer treats `UTD`, `UT`, `Dallas`, `Texas`, and `University` as stop words, so adding those terms would not improve ranking. The development set includes an UTD wording case to track this behavior.

## Development set and how to extend it

`evaluate/mentee3/development_cases.json` contains 39 cases: 32 answerable queries with source-backed passage labels and 7 unanswerable controls. It covers drop versus course withdrawal versus university withdrawal, date and population constraints, campus abbreviation, an acronym with context, spelling errors, public versus personal requests, assistant-output leakage, malformed history, topic switches, and unsupported future terms. Population follow-ups also label the undergraduate chunk as forbidden when the student switches to graduate registration.

To add a case, edit that JSON file and give it a unique `id`, a `category`, the exact student `query`, and a `history` array of `{ "role", "content" }` turns. For an answerable query, set `unanswerable` to `false` and add an `evidence` entry with a real `doc_id` plus an `any_of` or `all_of` phrase copied from a supporting chunk in `backend/data/chunks`. For a control, set `unanswerable` to `true` and use an empty evidence list. The runner checks that every evidence label exists in the current corpus before scoring, which helps distinguish a query-understanding miss from a corpus gap.

Run the development comparison from the repo root:

```bash
./.venv/bin/python evaluate/mentee3/run_eval.py --output /tmp/mentee3-run.json
```

The report compares baseline behavior, current behavior with aliases disabled, current behavior with history disabled, and the full change. It prints false acceptances, false rejections, lost answerable cases, population leakage against each case's `forbidden_chunk_ids`, evidence metrics, context size, and warmed latency. Generated JSON belongs in `/tmp` or the ignored `evaluate/mentee3/latest.json`, not in the labeled source file.

## Measurements

Measured against the same 38 cases, corpus, and retrieval settings, using the existing lexical retriever. These are evidence retrieval results, not generated-answer accuracy.

| Mode | Answerable complete evidence | False acceptances | Answerable false rejections | Mean context precision | Mean reciprocal rank |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 27/32 (84.4%) | 3/7 | 0/32 | 0.2406 | 0.6208 |
| No aliases (new rejection/history) | 28/32 (87.5%) | 0/7 | 0/32 | 0.2719 | 0.6271 |
| No history (new aliases/rejection) | 30/32 (93.8%) | 0/7 | 0/32 | 0.3167 | 0.7083 |
| Full change | 32/32 (100%) | 0/7 | 0/32 | 0.3417 | 0.7708 |

The full change retrieves complete evidence for four additional cases versus the no-alias ablation. History handling recovers the registration-deadline and graduate-population follow-ups that the no-history ablation loses. The query-local rejection changes removed the three baseline false acceptances in this small control set. No answerable case regressed in the final labeled set, and neither population-switch case retrieved its forbidden undergraduate chunk. During development, adding plural class/course aliases did harm one drop-instruction query's ranking; that expansion was narrowed to singular forms and the case is retained as a regression check.

Run metadata: baseline SHA `a3d9817d129db5945aa0d60c1dbd8cfddeae3588`; Python 3.12.16; macOS 26.3.1 arm64; 198 chunk files; corpus SHA-256 `aa120d8cf208bdf3d5e363714416a1c3c3e997949530492d761bb9da91bfa7db`; dev-set SHA-256 `7d6820efc479bcadbbcd4ac1d4aa56dcd51d0244008cf7e275df731ee34233ee`. Production retrieval settings were unchanged (`top_k=5`, candidate pool 50, context budget 1200 tokens, minimum score 0.3). Cold lexical-index construction took 0.061 seconds. For the full change, warmed per-case p50/p95 was 4.44/6.25 ms over 10 repeat passes; mean selected context was 435.3 estimated tokens. The runner completed with 0 failures.

## Validation commands

```bash
./.venv/bin/python -m unittest backend.tests.test_mentee3_query -v
./.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py' -v
./.venv/bin/python evaluate/mentee3/run_eval.py --output /tmp/mentee3-run.json
```

Results: focused tests passed (21 tests); backend suite passed (109 tests, one opt-in live Ollama test skipped); development evaluation completed (39 cases). `pytest` is not installed in this virtual environment, so the unittest-based suite was used to execute all backend test modules.

## Regressions, limitations, and integration

- There are no lost answerable cases in the final development-set run; keep reviewing each new case's retrieved chunk IDs when adding labels.
- Arbitrary misspellings are not auto-corrected. The typo controls are deliberately left as typed and must still abstain when there is no supporting evidence.
- Library location remains an evidence gap in this corpus; the correct behavior is abstention, not inferring the address from a room located inside the library.
- The 38-case development set is small and curated by the implementation author. It is not an independent holdout and does not establish factual answer quality. The mentor should validate against the sealed holdout once.
- No mentor-owned integration patch is needed: `backend/app/retrieval.py` already calls `rewrite` before lexical search and `reject` on candidate hits, and the chat route uses the same `rewrite` for generation. No score-threshold, ranking, schema, or route changes were made.
- PR creation and merge are left to the mentee, per the request. Before opening the PR, stage only the owned files and include this report plus the metrics.
