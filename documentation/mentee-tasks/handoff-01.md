# Handoff 01: retrieval evaluation and regression coverage

Mentee 1. Branch `codex/mentee-1-evaluation`, based on the mentor commit
`f763b1c75302879d25035445b12b5757746b3970` (`git rev-parse HEAD` before any change).
This branch measures retrieval; it changes no runtime retrieval, corpus, config,
existing evaluator or existing benchmark label.

## Summary

- `scripts/mentee1_eval.py` evaluates the production retriever or any candidate
  callable on fixed suites, separates quality from answerability and efficiency,
  checks contract integrity, and compares two runs per query.
- `evaluate/mentee1/cases.json` adds 49 verified development cases (12 unanswerable)
  labeled by real chunk ID and quote, including follow-ups with explicit history.
- Main finding: **production accepts all 12 unanswerable regression cases**, including
  the mentor's example ("How many computer science students are at UTD?" then
  "From those, how many are taking physics right now?"). The existing dev split
  reports 19/25 correct abstentions, but almost all come from rules for private
  records and unavailable years. No ranking-score threshold separates the new cases.

## Changed files

| File | Purpose |
| --- | --- |
| `scripts/mentee1_eval.py` | Harness: `validate`, `run`, `compare`, `peers` |
| `evaluate/mentee1/cases.json` | 49 regression cases, schema version 1 |
| `evaluate/mentee1/README.md` | Schema notes, commands, metric definitions |
| `evaluate/mentee1/example_adapters.py` | Example candidate adapter (history ablation) |
| `backend/tests/test_mentee1_eval.py` | 21 tests (unittest and pytest compatible) |
| `documentation/mentee-tasks/handoff-01.md` | This report |

## Metric definitions

These are the existing `evaluate_chunks.grade()` definitions. They measure whether
retrieval returned supporting passages, **not** whether a generated answer is correct.

- **Evidence recall**: share of required evidence groups covered by at least one returned passage.
- **Complete evidence**: 1 only if every group is covered. The strictest quality signal.
- **Reciprocal rank**: 1 / rank of the first passage that supports any group (0 if none).
- **Context precision**: share of returned passages that support some group.
  Wrong-population or wrong-year passages count against it.
- **Abstention correctness**: for unanswerable questions only, 1 if nothing is returned.

The existing leaderboard (`50% complete + 20% recall + 15% precision + 15% abstention`)
mixes these together. An adapter that always abstains still scores 15.0 on it, and
production's 61.84 dev score hides 6 accepted unanswerable questions. The harness
therefore reports three separate blocks:
- **Quality**: answerable cases only.
- **Answerability**: false refusals on answerable cases and false acceptances on
  unanswerable cases, as counts and rates.
- **Efficiency**: timing and context size.

It reports integrity violations alongside these. The leaderboard is kept only as a
reference number.

## Design and rationale

- **Labels by chunk ID plus verified quote.** Each evidence group lists the exact
  chunk IDs that support it for the question's population and time (OR within a
  group, AND across groups). Every quote must occur in its chunk. If the quote's
  words also occur in any other chunk, validation fails until that chunk is
  classified as an equivalent alternative or as `not_equivalent` with a reason.
  This enforces the requirement that matching a number or keyword is not enough:
  for example, the 2021-22 Computer Engineering PHIN rule appears word for word in
  eight CS and SE plans from other years, and each is explicitly rejected.
- **Distractors.** Cases label misleading chunks (other catalog year, graduate vs
  undergraduate, other 8-week session). The report counts cases where a distractor
  outranks all real evidence.
- **Unanswerable cases document why**, beyond a lexical miss. Each one records the
  searches performed and 1 to 3 nearest related chunks with the reason each does
  not answer.
- **Follow-ups store history explicitly.** Assistant turns are never evidence. When
  a follow-up asks something the corpus cannot support (current enrollment, a
  tuition computation built on a previous answer), the case is unanswerable even
  if the first turn was answerable.
- **No silent metric fork.** Quality formulas reuse the exact `grade()` expressions;
  only the support test differs (chunk IDs instead of phrases). A randomized test
  checks parity against `ev.grade()` over 200 hit lists. The `dev`/`test` suites are
  graded by the unchanged `ev.grade()`, and the harness reproduces
  `scripts/eval_retrieval.py` exactly: same ranked IDs and metrics on all 102 dev
  rows, leaderboard 61.84.
- **No label leakage.**
  - Adapters receive only `(query, top_k, history)`; a test spies on the call
    arguments.
  - A test scans `backend/app` to confirm it never references the fixture or
    benchmark files.
  - The test split requires `--allow-test-split`.
- **Reproducibility.** Every report records:
  - inputs: corpus SHA-256 (same fingerprint as `evaluate_chunks.py`), config,
    suite SHA-256s and the git commit with a dirty flag;
  - environment: Python and machine;
  - per case: raw ranked IDs, raw scores (labeled as ranking scores, not
    probabilities), source URLs, abstention reasons and per-repetition latencies.

  Order is fixed (sorted by suite and ID). Rankings come from repetition 1, and
  later repetitions must match exactly or the case is flagged
  `nondeterministic_ranking`. `compare` refuses runs whose corpus, labels or `top_k`
  differ.
- **Integrity checks** on every result:
  - limits: context budget, document cap and `top_k`;
  - passages: duplicate IDs, unknown IDs, and text or doc ID differing from the
    corpus (catches invented text or history injected as evidence);
  - links: unsafe, missing or unregistered URLs;
  - scores and contract: non-positive scores, abstain-with-passages and
    empty-without-abstain;
  - adapter exceptions.
- **Peers are read-only.** `peers` reads `evaluate/mentee2-5/**/*.json` from the
  working tree and from any `--git-ref` via `git show`, without checkout or writes.
  Missing peer directories are fine.

## Reproducible commands

From the repository root (`py` on Windows):

```sh
python -m pytest backend/tests -q
python scripts/eval_retrieval.py --split dev --json evaluate/runs/mentee-1/baseline-dev.json
python scripts/mentee1_eval.py validate
python scripts/mentee1_eval.py run --adapter production --repeat 5 --json evaluate/runs/mentee-1/production.json --markdown evaluate/runs/mentee-1/production.md
python scripts/mentee1_eval.py run --adapter production-no-reject --repeat 5 --json evaluate/runs/mentee-1/production-no-reject.json
python scripts/mentee1_eval.py run --adapter evaluate/mentee1/example_adapters.py:ignore_history --repeat 5 --json evaluate/runs/mentee-1/ignore_history.json
python scripts/mentee1_eval.py run --adapter always-abstain --repeat 5 --json evaluate/runs/mentee-1/always-abstain.json
python scripts/mentee1_eval.py compare evaluate/runs/mentee-1/production.json evaluate/runs/mentee-1/ignore_history.json --markdown evaluate/runs/mentee-1/cmp-ignore_history.md
python scripts/mentee1_eval.py peers --git-ref origin/codex/mentee-2-corpus
```

To compare your own change, write `def retrieve(query, top_k, history)` returning a
`RetrievalResult` or a list of passage dicts, then run it with
`--adapter path/to/file.py:retrieve`. Compare it with the production report.

## Baseline (frozen commit, no changes to runtime)

Environment:
- macOS 26.6.2 arm64 (Apple Silicon), CPython 3.14.3 from a fresh venv with
  `requirements-runtime.txt`, `pytest` and `httpx`.
- The CI-equivalent `unittest` commands also pass on CPython 3.12.14.

Inputs and settings:
- Corpus SHA-256 `aa120d8c...a7db` (3,003 chunks, 198 documents).
- `backend/retrieval_config.json` SHA-256 `f99bcc06...927a`.
- Suites: `questions.json` SHA-256 `ad2d747e...87f5` and `cases.json` SHA-256
  `b85ef102...9236`.
- `top_k` 5, context budget 1,200, document cap 5, order by ID, 5 repetitions
  (755 timed calls).

Tests and baseline reproduction:
- `pytest backend/tests`: 108 passed, 1 skipped (the 87 existing tests plus the 21
  new ones).
- `scripts/eval_retrieval.py --split dev` reproduces `retrieval.md` exactly:
  - leaderboard 61.84, complete evidence 0.5714, recall 0.7305, context precision
    0.4840, abstention 0.76;
  - warm p50/p95 9.25/12.01 ms on this machine.

| Production (`top_k` 5) | dev (102) | mentee1 (49) |
| --- | ---: | ---: |
| Evidence recall (answerable) | 0.731 | 0.579 |
| Complete evidence (answerable) | 0.571 | 0.432 |
| Reciprocal rank (answerable) | 0.742 | 0.544 |
| Context precision (answerable) | 0.484 | 0.315 |
| False refusals | 4 / 77 | 0 / 37 |
| False acceptances | 6 / 25 | **12 / 12** |
| Distractor outranks all evidence | not labeled | 10 cases |
| Unanswerable cases returning a labeled nearest-related chunk | not labeled | 5 |
| Mean / max context tokens (answered cases) | 510 / 1,192 | 621 / 1,191 |
| Integrity violations | 0 | 0 |

Efficiency over both suites: cold index load 82.3 ms; warm p50 8.37 ms, p95 12.32 ms,
max 26.64 ms.

### mentee1 per category (production)

| Category | n | Recall | Complete | Precision | False acceptance | Distractor first |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| direct_lookup | 4 | 0.50 | 0.50 | 0.20 | n/a | 2 |
| paraphrase | 4 | **0.00** | **0.00** | 0.00 | n/a | 0 |
| abbreviation | 4 | 1.00 | 1.00 | 0.54 | n/a | 1 |
| population_contrast | 5 | 0.60 | 0.20 | 0.59 | n/a | 1 |
| time_contrast | 5 | 0.82 | 0.60 | 0.32 | n/a | 3 |
| compound | 5 | 0.67 | 0.40 | 0.41 | n/a | 0 |
| near_miss | 5 | 0.40 | 0.20 | 0.21 | n/a | 1 |
| unanswerable | 10 | n/a | n/a | n/a | 10 / 10 | 0 |
| follow_up | 7 (2 unanswerable) | 0.60 | 0.60 | 0.21 | 2 / 2 | 2 |

### Per-query failures worth reading

- **Unanswerable, all accepted.** Several match the mentor's concern about a
  number for the wrong population:
  - `m1-unans-01` returns CS degree-plan chunks for a CS headcount;
  - `m1-unans-03` returns undergraduate plans for a master's question;
  - `m1-unans-09` returns "Suggested Four Year Plan" chunks for a graduation rate
    (top score 0.55, higher than most answerable cases).

  `m1-unans-06` ("spring break in Spring 2027") passes the year rule because 2027
  appears in an unrelated vaccination deadline.
- **Follow-ups.**
  - `m1-follow-01` (the mentor's example) returns a class-number registration chunk
    and CS plans instead of abstaining.
  - `m1-follow-05` fails because the rewrite anchors to the latest user turn
    (Bursar drop box) instead of the installment topic two turns back.
  - `m1-follow-06` returns only the undergraduate probation rule. The rewrite carries
    the old population ("undergrad") into the graduate follow-up, so the distractor
    is the only result.
- **Paraphrase.** All 4 cases miss completely. For example, "out-of-state price"
  never reaches "nonresident tuition rate" (`m1-para-01`), and "families making under
  100k" never reaches Comet Promise renewal (`m1-para-02`).
- **Time and population.**
  - `m1-time-04` ranks the 2025-26 plan above the requested 2026-27 plan.
  - `m1-pop-03` (SE 2025-26 hours) returns 2021-22 and 2024-25 SE chunks first.
  - `m1-direct-01` returns the early-fall Testing Center chunk ("Saturday closed")
    instead of the November hours.
- **Near misses.**
  - `m1-near-01` (can I audit CS 3345) returns degree-audit and real estate plan
    chunks.
  - `m1-near-03` (transfer transcript hold) returns advising and registrar FAQ
    chunks.

## Ablations

All are measured against production under identical inputs.

| Candidate | mentee1 complete | mentee1 false acceptance | dev complete | dev false refusal | dev false acceptance | Notes |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| production | 0.432 | 12/12 | 0.571 | 4/77 | 6/25 | baseline |
| `production-no-reject` (no abstention rules) | 0.432 | 12/12 | 0.571 | 0/77 | 25/25 | identical on mentee1; on dev the rules account for all 19 correct abstentions and cause 4 false refusals |
| `ignore_history` | 0.405 | 12/12 | 0.571 | 4/77 | 6/25 | 3 follow-up regressions (`m1-follow-03` loses its evidence; `-04`, `-07` lose precision); dev unchanged because dev has no history |
| `always-abstain` | 0.000 | 0/12 | 0.000 | 77/77 | 0/25 | sanity check: `run --gate` fails it; leaderboard still 15.0 |

**Ranking scores are not a confidence signal.** Accepted unanswerable cases have
top-1 scores from 0.38 to 0.55. On mentee1, 35 of 37 answerable cases score at or
below that maximum; on dev, 69 of 73 do. No threshold on the current score separates
answerable from unanswerable here, so raising `min_top_score` would trade false
acceptances for false refusals almost one for one.

## Peer cases and overlaps

- **Mentee 2** (`origin/codex/mentee-2-corpus`): 8 labels in
  `evaluate/mentee2/fixtures/labels.json`. All are synthetic fixtures (`doc901`,
  `doc902`) outside the production corpus, so there are no overlaps.
- **Mentees 3 to 5**: no branches or fixture directories existed when this report
  was written; rerun `peers` with their refs.
- **Existing `questions.json`**: 4 mentee1 cases share evidence documents and
  related wording with dev questions:
  - `m1-direct-02` with `data-dev-tuition-rebate-rules`;
  - `m1-pop-01` with `dev-hard-hybrid-status`;
  - `m1-time-01` with `dev-hard-cs-year-electives`;
  - `m1-time-03` with `nandhan-dev-fall-full-term-deadlines`.

  None are identical, and none overlap the test split.

## Problems found outside my ownership (not patched)

1. `documentation/retrieval.md` lists benchmark SHA-256 `1bd70731...`; the current
   `evaluate/questions.json` hashes to `ad2d747e...` with the same reported metrics.
   The recorded hash should be updated or the file history checked.
2. `retrieval_support/query.py` `rewrite()` uses only the latest user turn and keeps
   its population words. This fails `m1-follow-05` (topic two turns back) and
   `m1-follow-06` (graduate follow-up retrieves undergraduate rules). Relevant to
   mentee 3.
3. `reject()` rules do not reject any mentee1 unanswerable case. The year rule
   accepts a requested year that appears in unrelated evidence (`m1-unans-06`).
   Population mismatch (graduate question, undergraduate evidence) is not checked.
   Relevant to mentees 3 and 4.
4. Corpus quality (relevant to mentee 2):
   - **Mislabeled:** doc117 "Public Course and Syllabus Information" is a third
     copy of the Fall 2026 calendar with no session labels.
   - **Truncated:** doc160 is the calendar again with dates cut at chunk boundaries
     ("Withdrawal period ends Sept."). doc119 lost its ordinals ("3 installment
     due").
   - **Garbled:** the AP/CLEP/IB charts doc154 to doc157 have truncated course
     numbers. The doc175 and doc190 tables are flattened into single lines.
   - **Duplicated:** the audit-course text appears in both doc142 and doc133. The
     credit-by-exam text appears in doc005, doc006 and doc190. doc086_p1_c4 (SE
     2026-27) is text-identical to doc084_p1_c3 (CS 2026-27).
   - **Junk titles:** doc068 ("0 5 Core Curriculum Assessment UNIV 2020 ...").
     doc004 to doc011 all share the title "2025-2026 Undergraduate Catalog".
     doc076/084/086 put most rows under "MAJOR PREPARATORY REQUIREMENTS".
   - **Incomplete:** doc193 has no p4 chunk, so the NSM advisor list stops at
     "A-C". doc064 (CS 2023-24) has no course rows.

## Recommended merge gates

Run each gate on the same machine and Python, from the frozen baseline commit and
the candidate branch.

1. **Always:**
   - `python -m pytest backend/tests -q` passes;
   - `python scripts/mentee1_eval.py validate` and
     `python evaluate/evaluate_chunks.py --validate-only` exit 0;
   - zero integrity violations in `run` for both suites.
2. **Efficiency (mentee 5):**
   ```sh
   compare base.json cand.json --gate --require-identical-rankings
   ```
   - Rankings must be identical on mentee1 and dev, with no metric delta.
   - Warm p95 must not be worse. Use `--repeat 5` or more and judge noise across
     two runs before using `--max-p95-increase-ms`.
3. **Corpus cleanup (mentee 2):**
   - Rerun `validate` first. Replaced chunk IDs will fail loudly, and labels must be
     re-verified rather than auto-remapped.
   - Then report deltas, isolated from all other changes.
4. **Query and precision (mentees 3 and 4), merged one at a time:**
   - No drop in mentee1 or dev complete evidence.
   - No increase in false acceptance on either suite.
   - False refusals must not increase by more than one case per suite.
   - Every listed per-query regression must be explained in the PR.
   - Changes to `retrieval_config.json` thresholds must come with the ablation table.
5. **Final:**
   - Run the combined branch on mentee1, dev and peer suites.
   - Run the sealed holdout once (mentor only).
   - Report the test split as a regression check, not a tuning target.

Labels are never shown to tuning code. Mentees must not add holdout cases to
`cases.json`.

## Template for the final combined report

```markdown
# Combined retrieval evaluation, <date>
Baseline commit <sha>; combined commit <sha>; machine/Python <...>
Corpus sha <...> (baseline) -> <...> (combined); config sha <...> -> <...>
Suites and shas: mentee1 <...>, dev <...>, peers <list>, holdout <sealed, run once on <date>>

| Change | Merged | Evaluated alone | mentee1 complete | dev complete | False acceptance (m1/dev) | False refusal (m1/dev) | p95 ms |
| baseline | | | | | | | |
| + efficiency (5) | | identical rankings? | | | | | |
| + corpus cleanup (2) | | | | | | | |
| + query understanding (3) | | | | | | | |
| + precision module (4) | | | | | | | |
| combined | | | | | | | |

Per-category table (combined vs baseline), list of per-query regressions with
explanations, integrity violations (must be 0), holdout result (single run), test
split regression check, known limitations. Retrieval metrics only, not answer accuracy.
```

## Integration patch proposal (not applied; mentor-owned files)

The new tests already run under CI's `unittest discover -s backend/tests`. Proposed
CI and documentation additions:

```diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -35,6 +35,9 @@ jobs:
       - name: Validate benchmark labels
         run: python evaluate/evaluate_chunks.py --validate-only
 
+      - name: Validate mentee 1 regression fixtures
+        run: python scripts/mentee1_eval.py validate
+
   frontend:
     runs-on: ubuntu-latest
     steps:
--- a/documentation/retrieval.md
+++ b/documentation/retrieval.md
@@ -91,6 +91,10 @@ The script calls the production function, converts passages back to evaluator
 hits, and uses unchanged `grade()` and `summarize()`. Warm p95 uses nearest rank.
 It also records benchmark SHA-256 and per-question diagnostics in optional JSON.
 
+For regression cases with chunk-level labels, follow-ups, distractors, answerability
+separated from quality, integrity checks and run-to-run comparison, use
+`scripts/mentee1_eval.py` (see `evaluate/mentee1/README.md`).
+
 ## Final results, November 9, 2026
 
 The merged benchmark has 102 questions per split, including 25 unanswerable
```

## Limitations

- **Small, development-only set.** The 49 cases are development examples, not a
  holdout, and 4 to 10 cases per category is small. One case changes a category
  rate by 10 to 25 points. Treat category numbers as diagnostics, not significance
  tests.
- **How the cases were checked.** Cases were drafted with AI assistance. Every
  case was checked by the validator for chunk IDs, quotes and duplicate wording,
  and every case was read in review. Two labels were corrected during review
  (`m1-time-02`, `m1-time-05`).
- **Judgment calls.** Some labels involve interpretation, and the case `notes`
  record them:
  - `m1-follow-04`, `m1-near-04`: doc117 is not treated as equivalent because it
    names no session;
  - `m1-comp-04`: catalog versus financial-aid enrollment status;
  - `m1-para-01`: the 2019 start date is assumed to be the first Texas public term.
- **Unanswerable cases are tied to this corpus version.** Adding a tuition table or
  library hours would make some answerable, and `validate` will not detect that.
  Re-review `unanswerable_reason` whenever documents are added.
- **Credit is strict.** Chunk-ID labels give no credit for an unlisted chunk that
  also answers. The duplicate-wording check reduces this risk but cannot detect
  paraphrased duplicates.
- **Retrieval metrics do not measure answer correctness.** Latency figures are
  specific to this machine.
