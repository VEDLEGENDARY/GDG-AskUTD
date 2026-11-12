# Mentee 4: Precision ranking and evidence sufficiency

## Status

Program and catalog scope reranking implemented with a dev-only ablation runner.
Not integrated into production retrieval. Initial dev results are reported below;
the full assignment remains incomplete.

## Changed files

- backend/app/retrieval_support/precision.py
- backend/tests/test_mentee4_precision.py
- documentation/mentee-tasks/handoff-04.md
- evaluate/mentee4/adapter.py
- evaluate/mentee4/run_experiments.py

## Approach

The initial feature identifies explicit Computer Science and Computer
Engineering program names in the question and candidate source title.

For a question requesting exactly one recognized program:
- Matching program: add 0.10 to the precision score.
- Different recognized program: subtract 0.10.
- Unknown or ambiguous program: leave the score unchanged.

The adjustment is experimental and has not been tuned.
Original retrieval scores and passage fields are preserved.
Equal precision scores are ordered by chunk ID.

## Baseline dev results

- Questions SHA-256: ad2d747edc4d82920feec73aad69f50e477e5a91b4cd724066cf1c41541e87f5
- Evidence recall: 0.730519
- Complete evidence: 0.571429
- Context precision: 0.483983
- Reciprocal rank: 0.742424
- Correct abstention: 0.76
- Warm p50: 11.587 ms
- Warm p95: 15.139 ms

## Investigated cases

### Missing candidate: class standing and major declaration

Question ID: nandhan-dev-53-hours-undeclared

Missing passage doc011_p1_c1 ranked 66 with score 0.192614.
It failed both the top-50 cutoff and minimum score of 0.3.
Reranking the existing eligible pool cannot recover this passage.

### Wrong program: CS catalog comparison

Question ID: nandhan-dev-cs-2016-vs-2020-electives

Missing passage doc042_p1_c5 ranked 6 with score 0.453928.
It passed both candidate filters but was not selected.

Selected passages doc031_p1_c5 and doc031_p1_c4 describe
Computer Engineering rather than the requested Computer Science program.

## Validation

Command:
python3 -m pytest backend/tests/test_mentee4_precision.py -q

Result: 4 passed.

Tests cover program preference, unchanged inputs and source fields,
deterministic ties, and explicit comparisons of both programs.

## Remaining work

- Measure feature ablations, regressions, recall, precision and latency.
- Provide a mentor-owned integration proposal.

## Limitations

Only two program names are currently recognized.
Program scope is inferred from source titles.
A matching program does not prove that a passage answers the question.

## Initial reranking experiment

For the CS 2016–2018 versus 2020–2021 comparison, program-scope
reranking removed the two Computer Engineering passages.

However, the required doc042_p1_c5 remained unselected.
The reranked selection included a 2021–2022 CS passage outside
the requested catalog years.

Conclusion: program matching alone did not complete the evidence.

## Adapter parity

The isolated adapter matched production index selection on all
102 development questions with reranking disabled.

Parity failures: 0.

This verifies index-stage parity, not full service parity:
query rewriting and rejection checks still require end-to-end validation.

## Analysis of program-only results

Program-only reranking removed the Computer Engineering passages
from the CS catalog comparison, but did not select the required
doc042_p1_c5.

Instead, the selection included:
- doc038_p1_c1: correct program and catalog, but largely a course list.
- doc021_p1_c1: relevant totals from an unrequested 2021–2022 catalog.

Program matching alone did not complete the evidence.

## Catalog-range extraction

Added extraction of explicit four-digit year ranges, allowing
spaces and common dash characters.

Validation: 5 tests passed before adding catalog scoring.

## Catalog-scope experiment

Added an experimental 0.10 penalty when a candidate title has
explicit catalog ranges that do not overlap the requested ranges.

Unknown catalog scope stays neutral. Program and catalog features
can be disabled independently for ablation experiments.

This compares explicit ranges; it does not establish that a policy
is current or that a passage contains the requested answer.

Ranking results and full-dev impact are pending.

## Combined program and catalog experiment

Question: nandhan-dev-cs-2016-vs-2020-electives

With program and catalog features enabled, the adapter selected:
- doc042_p1_c4
- doc038_p1_c5
- doc038_p1_c4
- doc038_p1_c1
- doc042_p1_c5

The previously missing doc042_p1_c5 entered the final selection.
All four required supporting passages are now present.

Estimated context increased from 744 to 847 tokens, remaining
within the 1,200-token budget.

The additional course-list passage doc038_p1_c1 remains selected.
This is a single development-case result; full-dev metrics and
per-query regressions have not yet been measured.


## Adapter feature switches (November 11, 2026)

`search` now accepts keyword switches `use_program` and `use_catalog`.
`use_precision=False` retains the original selection behavior. When enabled,
only the requested features contribute to precision_score used by MMR.
Candidate admission still uses unchanged retrieval_score. No production files
or configuration were edited. Candidate pool remains 50, minimum score 0.3,
output top_k 5, context budget 1,200, and the existing document cap applies.

The handoff was moved from documentation/handoff-04.md to the assigned
location documentation/mentee-tasks/handoff-04.md.

## Four-way dev runner

Run from the repository root using the existing environment:

```sh
.venv/bin/python3 -m pytest backend/tests/test_mentee4_precision.py -q
.venv/bin/python3 -m evaluate.mentee4.run_experiments --output evaluate/runs/mentee-4/ablations-dev.json
```

Choose a fresh output filename on subsequent runs; existing reports are never
overwritten. Outputs are restricted to evaluate/runs/mentee-4 and ignored by Git.
The runner uses dev only, no test split, models, downloads, or new dependencies.
It applies production query rewriting (without history), reranks before MMR,
and applies existing rejection checks after selection. No new sufficiency checks
are implemented. Labels are used only for grading, never ranking.

Baseline assertions passed for all 102 queries: exact index hits, final production
chunk IDs, rejection reasons, and retrieval metrics. Every variant checks selected
count, budget, document caps, and original-score admission before rejection.
JSON includes settings, hashes, environment, commit, working-tree status,
per-query IDs/reasons/scores/metrics, changes, regressions, and timings.

Definitions: evidence recall and complete evidence average over answerable
questions; context precision averages each answerable question's supporting-hit
fraction, with abstentions scored zero. It is not fixed-denominator precision@5
when fewer than five passages are returned. Answered complete-evidence precision
is the number of responses with all labeled evidence divided by all accepted
responses, including unanswerables. Answerable acceptance is the fraction of
answerable questions not rejected; complete evidence separately measures full
answerable coverage. False acceptance is accepted unanswerables divided by all
unanswerables. None measures generated-answer factual accuracy.

## Initial measured ablations

| Variant | Evidence recall | Complete evidence | Context precision | MRR | Correct abstention | Score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 0.730519 | 0.571429 | 0.483983 | 0.742424 | 0.760000 | 61.841558 |
| program_only | 0.730519 | 0.571429 | 0.483983 | 0.742424 | 0.760000 | 61.841558 |
| catalog_only | 0.730519 | 0.571429 | 0.483983 | 0.751082 | 0.760000 | 61.841558 |
| combined | 0.733766 | 0.584416 | 0.486580 | 0.751082 | 0.760000 | 62.594805 |

Combined gains versus baseline: evidence recall +0.325 percentage points,
complete evidence +1.299 points, context precision +0.260 points, score +0.753.
No negative per-query deltas on the five reported evidence/abstention metrics
were observed, but this does not establish absence of harmful behavior.
The proposed recall-loss gate is met on this dev run; this is not a merge recommendation.

Program-only changed one query with no aggregate evidence improvement.
Catalog-only changed three queries and improved MRR, without improving recall
or complete evidence. Combining features completed the CS comparison.

Important acceptance risk: dev-hard-ce-calculus-exemption was previously rejected
but now returns five passages with zero labeled evidence covered, in catalog-only
and combined runs. This is a reliability concern even though its evidence metrics
remain zero and the automated metric-regression flag is false. The runner also
explicitly flags this new acceptance without labeled support.

Other changed queries: dev-hard-cs-year-electives improves first-support rank;
dev-hard-same-year-different-major changes selected IDs with no evidence metric gain.
Full before/after IDs and metric deltas are in the generated report.

| Variant | Accepted | Complete-evidence precision among accepted | Answerable acceptance | Unanswerable false acceptance | Warm p50 ms | Warm p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 79 | 0.556962 | 0.948052 | 0.240000 | 19.300 | 26.611 |
| program_only | 79 | 0.556962 | 0.948052 | 0.240000 | 18.483 | 24.995 |
| catalog_only | 80 | 0.550000 | 0.961039 | 0.240000 | 18.769 | 24.868 |
| combined | 80 | 0.562500 | 0.961039 | 0.240000 | 18.743 | 24.768 |

Environment: Python 3.12.0, macOS-26.3.2-arm64-arm-64bit.
Baseline HEAD: f763b1c75302879d25035445b12b5757746b3970 with uncommitted assignment changes.
Corpus SHA-256: f096b8331bc8355d067b590bcde12ff9b4589634f81c91d08098e1e5d879b60c.
Question SHA-256: ad2d747edc4d82920feec73aad69f50e477e5a91b4cd724066cf1c41541e87f5.
Cold index load: 231.605 ms.

Timing uses one warm sample per question per variant, fixed order, excluding
parity assertions and grading. Small differences are noise, not evidence of a
speed improvement. Historical baseline timings above are not a controlled
latency comparison to this run.

Validation: 10 focused tests passed, including adapter feature propagation,
source-field preservation, synthetic index parity, budget and document caps.
Full backend command `.venv/bin/python3 -m pytest backend/tests -q` failed during
collection: installed Starlette TestClient requires missing `httpx2`.
No shared dependency file was changed; full-suite validation remains incomplete.

Remaining work includes additional hard cases, evidence sufficiency, explicit
precision@k measurement, expanded candidate-pool experiments, candidate logs,
and a mentor integration proposal. Current scoring recognizes only two spelled-out
program names and explicit full-year ranges; abbreviations and implied time scope
are unresolved. Do not tune repeatedly against these four changed queries alone.

## Evidence sufficiency: initial implementation (November 11, 2026)

Implemented `evidence_reason(query, hits) -> str | None` in precision.py.
It does not mutate hits, invent evidence, or select context. It runs only after
budgeted selection in the experimental runner. Existing production rejection
checks always remain active and take precedence; both reasons are logged.
Production runtime remains unchanged.

Checks, with no labels or question IDs in runtime rules:

- Empty passage bodies fail, even if titles match the query.
- For explicit full-year ranges in catalog/plan/degree questions, every requested
  range must appear in an individual passage context. If exactly one recognized
  program is requested, that program must appear in the same context. A range
  in a CS passage cannot satisfy a CE question using other CE passages.
- Scope can be identified from title or body, but the body must contain at least
  eight whitespace-separated words and match at least one query anchor remaining
  after a fixed set of generic plan words is removed (when any anchors remain).
- Questions explicitly asking for both class standing and major declaration
  require classification terms with numbers and declaration terms with numbers.
- Questions explicitly asking for eligibility and documents require eligibility
  condition language plus document submission language and document terms.
  Different passages/documents may supply different parts.
- Unrecognized intents defer to existing checks; None means these additional
  heuristics passed, not that the question is demonstrably answered.

These are intentionally limited lexical rules. The eight-word minimum and
single-anchor overlap are preliminary heuristics, not calibrated confidence.
No arbitrary splitting on 'and', numeric rule evaluation, semantic entailment,
negation resolution, personal eligibility decision, or comprehensive date-scope
parsing is performed. Multiple mentioned years/programs in one passage can still
mislead scope detection. Eligibility wording may miss valid paraphrases, and
navigation containing longer repeated phrases may pass. Metadata scope plus body
term overlap does not prove that the body answers the requested facet.

## Sufficiency validation and experiment

```sh
.venv/bin/python3 -m pytest backend/tests/test_mentee4_precision.py -q
.venv/bin/python3 -m evaluate.mentee4.run_experiments --output evaluate/runs/mentee-4/sufficiency-dev.json
```

Result: 16 focused tests passed. Added cases cover empty/title-only evidence,
unrelated program/year combinations, every requested catalog, partial versus
complete paired facets, cross-document support, input immutability, and deferral
for unrecognized intents. Baseline production parity passed all 102 dev cases.
The original four ablations reproduced their previous evidence metrics.
No test-split evaluation or tuning was performed.

The runner now adds sufficiency_only and combined_sufficiency variants to the
original four variants. All variants use identical candidate and selection limits.
No new thresholds were tuned after inspecting these results. Reports refuse
existing output filenames; use a new filename for repeat runs.

| Variant | Evidence recall | Complete evidence | Context precision | MRR | Correct abstention | Score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 0.730519 | 0.571429 | 0.483983 | 0.742424 | 0.760000 | 61.841558 |
| combined | 0.733766 | 0.584416 | 0.486580 | 0.751082 | 0.760000 | 62.594805 |
| sufficiency_only | 0.724026 | 0.571429 | 0.470996 | 0.729437 | 0.760000 | 61.516883 |
| combined_sufficiency | 0.724026 | 0.584416 | 0.470996 | 0.725108 | 0.760000 | 62.166234 |

| Variant | Accepted | Complete-evidence precision among accepted | Answerable acceptance | Unanswerable false acceptance | Warm p50 ms | Warm p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 79 | 0.556962 | 0.948052 | 0.240000 | 11.606 | 17.631 |
| combined | 80 | 0.562500 | 0.961039 | 0.240000 | 11.177 | 15.437 |
| sufficiency_only | 78 | 0.564103 | 0.935065 | 0.240000 | 10.811 | 14.290 |
| combined_sufficiency | 77 | 0.584416 | 0.922078 | 0.240000 | 10.857 | 14.302 |

Combined sufficiency reduces evidence recall by 0.974 percentage points versus
reranking alone, or 0.649 points versus production baseline. Both are within the
proposed 2-point recall-loss bound, but context precision falls below baseline
and unanswerable false acceptance does not improve. This is not evidence that
all acceptance goals are met. Answerable acceptance falls from 94.805% at baseline
to 92.208% (and from 96.104% for reranking alone). No previously complete response
becomes incomplete on this dev set; 45 complete responses remain in combined
sufficiency versus 44 baseline. Accepted-response precision rises partly because
incomplete responses are refused, not because their missing evidence is recovered.

Additional rejections versus combined reranking:

- nandhan-dev-53-hours-undeclared: missing class-standing evidence. Evidence recall
  drops from 0.5 to 0; one valid major-declaration passage is withheld.
- dev-hard-cs-year-electives: no scoped body evidence for 2026-2027. Evidence recall
  drops from 0.25 to 0; some correct evidence is withheld to avoid an incomplete answer.
- dev-hard-ce-calculus-exemption: no CE 2025-2026 body evidence. The newly introduced
  acceptance with zero labeled evidence is rejected. This is an answerable question
  with failed retrieval, not one of the benchmark's labeled unanswerables.

Sufficiency-only adds just the class-standing rejection versus baseline; the
existing checks already reject the other two baseline selections. These per-query
tradeoffs are logged rather than hidden as universal precision improvements.

Recommendation: keep this experimental and review added refusals with the mentor.
Candidate recall improvements are still necessary for these answerable questions.
Next work should expand source-backed hard cases and test paraphrases, partial
facets, and cross-document scope before integrating. Full backend validation is
still incomplete due to the previously reported missing httpx2 dependency.

The sufficiency report records the same corpus and question hashes as the prior
ablation run, Python/machine/settings/commit/working-tree provenance, cold load,
and per-question diagnostics. Timing remains one warm sample per query in fixed
variant order and must not be interpreted as a speed improvement.

Additional validation: `.venv/bin/python3 -m pytest backend/tests/test_mentee4_precision.py backend/tests/test_retrieval.py -q` produced 25 passed and 1 failed. The existing API smoke test failed importing TestClient because neither httpx2 nor httpx is installed. This is the same environment dependency blocker, not a passing full-suite result.

## Twenty-five source-backed hard cases

Added evaluate/mentee4/hard_cases.json (25 new dev questions), hard_cases.py
(validator), and README.md (fixture schema, full inventory, reproducible commands,
results and limitations). Added `--hard-cases` to the existing experiment runner;
default shared-dev behavior remains unchanged. Added two fixture validation tests
to the owned test file. No runtime ranking/sufficiency rule changed in this step.

Coverage: two wrong-program, two wrong-year, three wrong-population, seven
compound, four cross-document, three scope-exception, two navigation/topic-only,
one ambiguous-time and one ambiguous-program cases. Every case has real chunk IDs,
document IDs/titles, exact source quotes, and explicit hard negatives. Negative
claims are facet-specific; a partially useful passage is not marked wholly wrong.
Two ambiguous cases require clarification for a unique numeric answer; answering
both alternatives conditionally is not evaluated by this retrieval-only harness.

Validation: all quotes/IDs and scoped evidence/negative claims passed; all 23
answerable cases are oracle-feasible within current filters/caps/budget. No query
duplicates shared dev. Shared test was not inspected. 18 focused tests passed.
Baseline parity passed index selection and production IDs/reasons/metrics on all
25 cases. A small unanswerable set is not representative general abstention evidence.

Commands:

```sh
.venv/bin/python3 -m evaluate.mentee4.hard_cases
.venv/bin/python3 -m pytest backend/tests/test_mentee4_precision.py -q
.venv/bin/python3 -m evaluate.mentee4.run_experiments --hard-cases --output evaluate/runs/mentee-4/hard-cases-dev.json
```

Use a new report name if the output already exists. Reports contain admitted
candidate IDs/scores/ranks, label-based evidence coverage and admitted hard-negative
IDs. Label diagnostics are computed after selection and never affect scoring.

Initial hard-case results (not comparable directly to shared-dev aggregates):

| Variant | Evidence recall | Complete evidence | Context precision | Correct ambiguity abstention |
| --- | ---: | ---: | ---: | ---: |
| baseline | 0.760870 | 0.695652 | 0.326087 | 0.000000 |
| program_only | 0.782609 | 0.695652 | 0.334783 | 0.000000 |
| catalog_only | 0.826087 | 0.782609 | 0.352174 | 0.000000 |
| combined | 0.847826 | 0.782609 | 0.360870 | 0.000000 |
| sufficiency_only | 0.739130 | 0.695652 | 0.317391 | 0.000000 |
| combined_sufficiency | 0.804348 | 0.739130 | 0.343478 | 0.000000 |

Combined ranking improves complete evidence from 16/23 to 18/23. Combined
sufficiency falls to 17/23 because it falsely refuses the fully supported
mentee4-dev-same-year-degree-totals comparison. The generic body-anchor heuristic
misses valid numeric evidence. Relative to ranking alone, sufficiency loses
4.348 recall points, exceeding the proposed 2-point loss gate; relative to
production baseline its recall is still 4.348 points higher. Sufficiency-only
loses 2.174 recall points versus baseline. These comparisons must both be reported.
The false refusal is new evidence against integrating the current sufficiency
heuristic, despite the initially positive shared-dev result.

Every variant accepts both underspecified cases (2/2 false acceptance). No claim
of reliable ambiguity handling is supported. Missing candidate evidence affects
ce-calculus-and-grades, meningitis-online-exemption and grade-appeal-not-clerical;
selection feasibility alone cannot fix admission failures.

See evaluate/mentee4/README.md and the generated report for details. Recommend
keeping sufficiency experimental, reviewing false refusals and broadening
paraphrase testing. This set was authored after the current rules and is dev data,
not a mentor-sealed holdout. Runtime rules were not adjusted during this step.
Full backend testing remains blocked by the previously documented missing HTTP
client dependency. Nothing is integrated into production, committed or pushed.

Hard-case question SHA-256: 064deb4224fabbfb8f9a38d2ac9ac9ebc5d0ae84611407a4c4a1e8bc8d52ec79.

## Revised sufficiency after false-refusal analysis

The first hard-case run exposed a fully supported comparison rejected because
leftover query words such as 'give', 'its' and 'breakdown' were used as required
body anchors. The implementation now removes this arbitrary overlap condition.
Scope checks and explicit quantity facets are separate:

- Required program and year stay together in a substantive passage context.
  Title program metadata takes precedence over incidental program mentions in body.
- A comparison of multiple recognized programs within one catalog requires scope
  evidence for each requested program. Multi-program/multi-year pairings are not
  inferred from a Cartesian product.
- Explicit exclusion phrases ('do not substitute', 'excluding', 'rather than',
  'instead of') remove the named program from sufficiency scope requirements.
  Ranking weights are unchanged. This is limited exclusion parsing, not general
  negation or intent understanding.
- Recognized lower/upper-division and elective quantity requests require numeric
  fact shapes in body text. Titles cannot supply the numbers. Separate passages
  in the same scope can cover different facets; fragments are never concatenated
  to create a fact. Elective patterns allow numeric and common spelled-out values.
- Unknown facet wording defers to existing content checks instead of requiring
  arbitrary question words. Singular/plural catalog/plan/degree forms are recognized.

No question IDs, expected numeric values, or fixture lookups occur in runtime
rules. Existing body-length minimum, paired-facet checks, thresholds, context
constraints, and production rejection checks remain. The quantity patterns do not
verify arithmetic, distinguish every minimum from a total, interpret all table
layouts, or prove semantic completeness. No additional ambiguity policy is added.

Validation: 24 focused tests passed, including new wording variations, separate
scoped fact passages, missing/metadata-only numeric evidence, program comparisons,
explicit excluded programs, and the source-backed false-refusal regression.
Baseline parity passed all 102 shared-dev questions and all 25 hard cases.
Both datasets were rerun after the final exclusion change. Earlier intermediate
v2 reports are exploratory; use the '-sufficiency-revised.json' reports below.

```sh
.venv/bin/python3 -m pytest backend/tests/test_mentee4_precision.py -q
.venv/bin/python3 -m evaluate.mentee4.run_experiments --output evaluate/runs/mentee-4/shared-dev-sufficiency-revised.json
.venv/bin/python3 -m evaluate.mentee4.run_experiments --hard-cases --output evaluate/runs/mentee-4/hard-cases-sufficiency-revised.json
```

Use fresh output names when repeating. The final two dataset runs were concurrent,
so their latency numbers are contention-affected and not a controlled performance
comparison. No speed claim is made. Full backend validation is still blocked by
its previously documented missing HTTP client dependency; it was not claimed passed.

| Dataset / variant | Evidence recall | Complete evidence | Context precision | Complete-evidence precision among accepted | Answerable acceptance |
| --- | ---: | ---: | ---: | ---: | ---: |
| Shared dev / baseline | 0.730519 | 0.571429 | 0.483983 | 0.556962 | 0.948052 |
| Shared dev / combined | 0.733766 | 0.584416 | 0.486580 | 0.562500 | 0.961039 |
| Shared dev / combined_sufficiency | 0.720779 | 0.584416 | 0.468398 | 0.592105 | 0.909091 |
| Hard cases / baseline | 0.760870 | 0.695652 | 0.326087 | 0.695652 | 0.913043 |
| Hard cases / combined | 0.847826 | 0.782609 | 0.360870 | 0.720000 | 1.000000 |
| Hard cases / combined_sufficiency | 0.847826 | 0.782609 | 0.360870 | 0.720000 | 1.000000 |

The fully covered same-year-degree-totals hard case now passes. Combined
sufficiency preserves all 18/23 complete hard-case responses and all 45/77 complete
shared-dev responses from ranking alone. On hard cases it adds no rejection versus
combined ranking; the two ambiguous requests are still accepted (2/2).

On shared dev it withholds four previously accepted incomplete selections:
- nandhan-dev-53-hours-undeclared: missing class-standing evidence (prior recall 0.5).
- dev-hard-cs-year-electives: missing elective quantity for 2026-2027 (prior recall 0.25).
- dev-hard-ce-calculus-exemption: missing scoped CE 2025-2026 body evidence (prior recall 0).
- dev-hard-same-year-different-major: missing scoped CS 2025-2026 body evidence (prior recall 0.25).

These are additional refusals on answerable questions, not recovered evidence.
Shared-dev recall loss versus combined ranking is 1.299 percentage points, within
2 points; versus production baseline it is 0.974 points. Context precision remains
below production baseline because withholding partially useful evidence scores
zero. Answerable acceptance falls from 96.104% for combined ranking to 90.909%.
Shared-dev unanswerable false acceptance remains 6/25 (24%).

Sufficiency-only still loses 2.174 recall points versus the hard-case baseline,
so the proposed gate is not universally met across all feature combinations.
Do not summarize this as all acceptance criteria passing. Recommend keeping
sufficiency experimental and giving the mentor both ranking-only and combined
results, including the extra refusals.

This is a development-driven correction: the hard cases were reused to revise
rules and remain dev data, not an untouched holdout. Their queries, quotes and
labels were not modified. A mentor-authored sealed holdout is still needed before
final integration. Shared runtime files, production config, corpus and benchmark
labels remain unchanged. No production integration or PR/merge occurred here.

## Broader candidate-pool experiment

Added `evaluate/mentee4/run_pool_sweep.py` and refactored the isolated adapter
into reusable scoring, admission and selection stages. The default search API
and production behavior remain unchanged. Scoring returns original index-position
and score pairs before admission, enabling diagnostics of excluded passages.
Selection copies input dictionaries and rechecks original positive/minimum scores.
Experimental indexes share read-only cached features but receive copied settings;
no production settings or cached index settings are modified.

```sh
.venv/bin/python3 -m pytest backend/tests/test_mentee4_precision.py -q
.venv/bin/python3 -m evaluate.mentee4.run_pool_sweep --output evaluate/runs/mentee-4/pool-sweep-dev.json
```

Choose a fresh report filename on repeat runs. This evaluates both 102-question
shared dev and the separate 25-case dev set, all six feature combinations, at
candidate limits 50, 100, 200 and the full filtered index (2,998 passages). The
full corpus has 3,003 passages; current length filters exclude five. A full-index
candidate limit still enforces original retrieval_score >= 0.3 and > 0. All runs
retain top_k 5, 1,200 context tokens, document cap 5, and existing rejection checks.
No expanded-pool or lowered-threshold setting was written to production config.

26 focused tests passed. Added tests cover broader admission, a below-threshold
candidate remaining excluded, stable ties/original scores, input immutability,
budget preservation and unchanged source index settings. Index selection parity
passed for every pool on both datasets; production final IDs/reasons matched
baseline pool 50 for every question. Original scoring and all four selection
constraints were asserted. No test split was evaluated.

## Pool-sweep results

All six variants have zero selected-ID or rejection-reason changes when any wider
pool is compared with pool 50 on the same dataset/variant. Candidate evidence
coverage is also unchanged. Wider admission alone provides no measured quality
gain here, including the full filtered index.

| Dataset | Pool limit | Mean admitted | Max admitted | Candidate evidence recall | Candidate complete evidence | Ranking-only final recall | Ranking-only complete evidence | Ranking-only precision@5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| shared_dev | 50 | 7.392 | 50 | 0.797619 | 0.636364 | 0.733766 | 0.584416 | 0.236364 |
| shared_dev | 100 | 8.167 | 82 | 0.797619 | 0.636364 | 0.733766 | 0.584416 | 0.236364 |
| shared_dev | 200 | 8.167 | 82 | 0.797619 | 0.636364 | 0.733766 | 0.584416 | 0.236364 |
| shared_dev | 2998 | 8.167 | 82 | 0.797619 | 0.636364 | 0.733766 | 0.584416 | 0.236364 |
| hard_cases | 50 | 20.680 | 50 | 0.913043 | 0.869565 | 0.847826 | 0.782609 | 0.234783 |
| hard_cases | 100 | 23.600 | 97 | 0.913043 | 0.869565 | 0.847826 | 0.782609 | 0.234783 |
| hard_cases | 200 | 23.600 | 97 | 0.913043 | 0.869565 | 0.847826 | 0.782609 | 0.234783 |
| hard_cases | 2998 | 23.600 | 97 | 0.913043 | 0.869565 | 0.847826 | 0.782609 | 0.234783 |

Precision@5 uses a fixed denominator of five slots per answerable question,
counting unfilled slots and abstentions as zero. This is intentionally different
from existing context precision, which divides by returned hit count. Relevant
passages are defined by document-scoped benchmark evidence, not generated-answer
correctness. Candidate recall averages evidence-group coverage over answerable
questions before MMR, budget selection and rejection. Candidate complete evidence
checks all groups present, not whether the admitted set can jointly fit the budget.

Pool 100 admits extra passages for three shared-dev queries:
nandhan-dev-cs-2016-vs-2020-electives, dev-hard-same-year-different-major, and
dev-hard-next-policy. It does so for four hard-case queries: ce-old-electives,
same-year-degree-totals, cs-prep-and-core, and unspecified-engineering-program
(all with mentee4-dev- prefix). None gains labeled candidate coverage or changes
final selection. Across these queries the maximum score-eligible population is
82 on shared dev and 97 on hard cases; pools above 100 admit nothing additional.

## Why the missing evidence remains missing

The sweep logs every labeled supporting passage's original rank and score, plus
admitted IDs, coverage and count at each pool size. These diagnostics are produced
after retrieval and timing and do not influence scoring.

| Example | Supporting chunk | Original rank | Original score | Admission failure |
| --- | --- | ---: | ---: | --- |
| Shared-dev standing | doc011_p1_c1 | 66 | 0.192614 | score and pool-50 cutoff |
| Hard-case CE grade rules | doc075_p1_c17 | 54 | 0.268620 | score and pool-50 cutoff |
| Hard-case online-only exemption | doc139_p6_c1 | 4 | 0.291064 | score threshold |
| Hard-case grade appeal policy | doc005_p3_c22 | 14 | 0.174065 | score threshold |

Increasing the pool to include a passage's rank does not override the 0.3 score
threshold. Lowering only candidate admission would still leave these passages
ineligible for final selection under the current production threshold contract.
Do not claim that this experiment recovered them or silently bypass the final
threshold. Score calibration/query-scoring changes require mentor coordination.

## Measurement limits and recommendation

All pool/variant selections reuse one original scoring pass per query, because
pool size does not affect the scoring formula. The report records scoring time
and selection/check time separately; its reconstructed latency excludes admission,
parity checks, grading and label diagnostics. It is not production end-to-end
latency and is not directly comparable with earlier runner timings. Each query
has only one scoring sample, variants run in fixed order, and no speed win is
claimed. The experiment runs the two datasets sequentially in one process.

The JSON report includes corpus/question hashes, platform/Python/settings,
commit/working-tree status, source-file hashes, cold index-load time, all variants'
metrics/latencies, candidate diagnostics and per-query differences against pool 50.
Retain the generated report locally; results are summarized here because runs are
ignored by Git. The full backend suite remains blocked by its previously reported
missing HTTP client dependency; these focused results do not replace full validation.

Recommendation: retain candidate_pool=50 for now. The wider pool adds candidates
without a quality benefit on these dev sets. Address scoring/admission limitations
with the mentor before proposing a threshold or shared-index change. Sufficiency
and ambiguity limitations documented earlier remain unresolved. No corpus,
shared config, runtime integration, dependency, benchmark label, commit or push
was changed as part of this experiment.
