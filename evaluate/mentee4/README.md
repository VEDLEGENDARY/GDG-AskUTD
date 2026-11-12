# Mentee 4 source-backed hard cases

This separate development fixture contains 25 newly authored questions: 23
answerable and two underspecified single-answer requests. It was authored after
the initial program/catalog/sufficiency rules and first measured without changing
those rules. It was subsequently reused to revise sufficiency (see below), so it
is development data, not a sealed holdout. Shared questions, corpus and config are unchanged.

## Reproduce

From the repository root, using the existing virtual environment:

```sh
.venv/bin/python3 -m evaluate.mentee4.hard_cases
.venv/bin/python3 -m pytest backend/tests/test_mentee4_precision.py -q
.venv/bin/python3 -m evaluate.mentee4.run_experiments --hard-cases --output evaluate/runs/mentee-4/hard-cases-dev.json
```

Use a fresh output filename on repeat runs. The runner refuses overwriting reports.
Without `--hard-cases`, the runner still evaluates the original shared dev set.

## Fixture format and labeling

`hard_cases.json` is the reviewable source of truth:

- `evidence`: required document-scoped evidence groups, using the existing grader.
- `sources`: group number, exact supporting quote, chunk ID, document ID and title.
- `hard_negatives`: actual corpus passages, exact text, IDs, explanation, and the
  evidence groups they do not establish. These are author-selected challenge
  passages; they are not claimed to appear in every query's candidate pool.
- `unsupported_groups`: a negative may still support another part of the question.
  The junior/declaration case deliberately uses a correct classification passage
  as insufficient evidence for the declaration facet. It must not be labeled
  irrelevant to the whole question.
- `ambiguity_sources`: competing conditional answers for underspecified questions.
  Their passages are valid within their own scopes, but choosing one unique answer
  silently assumes a year or degree. The fixture expects clarification/abstention
  for the requested single answer, not a claim that no relevant documents exist.
  An answer explaining both alternatives could be useful; this retrieval-only
  grader cannot evaluate that behavior. Report these two cases separately.

The validator verifies exact quote membership, document/title identity, evidence
coverage by each quote, negative facet claims, unique IDs/queries, category coverage,
and dev-only split. The CLI also checks oracle feasibility under current index
length filters, top_k, document cap and budget, and query duplicates against shared
dev only. It does not read the shared test split. Automated lexical checks cannot
prove semantic label quality or completeness; mentor review remains appropriate.

## Case inventory

| Case suffix (`mentee4-dev-`) | Category | Supporting chunk IDs | Explicit hard-negative IDs |
| --- | --- | --- | --- |
| cs-old-electives | wrong_program | doc038_p1_c4 | doc031_p1_c4 |
| ce-old-electives | wrong_program | doc031_p1_c4 | doc038_p1_c4 |
| cs-new-division | wrong_year | doc042_p1_c5 | doc038_p1_c5 |
| cs-old-division | wrong_year | doc038_p1_c5 | doc042_p1_c5 |
| elective-year-change | cross_document | doc038_p1_c4, doc042_p1_c4 | doc031_p1_c4 |
| same-year-degree-totals | cross_document | doc038_p1_c5, doc031_p1_c5 | doc042_p1_c5 |
| ce-calculus-and-grades | compound | doc075_p1_c5, doc075_p1_c17 | doc037_p1_c1 |
| cs-prep-and-core | compound | doc042_p1_c1, doc042_p1_c2 | doc042_p1_c5 |
| graduate-nondegree-restriction | wrong_population | doc110_p1_c7 | doc110_p1_c3 |
| undergraduate-nondegree-appointment | wrong_population | doc110_p1_c3 | doc110_p1_c7 |
| graduate-deans-list | wrong_population | doc005_p2_c15 | doc005_p2_c14 |
| incomplete-eligibility-time | compound | doc005_p4_c31, doc005_p4_c32 | doc005_p3_c19 |
| incomplete-extension-reenroll | compound | doc005_p5_c33 | doc005_p4_c32 |
| junior-declaration-cross-source | cross_document | doc011_p1_c1, doc008_p2_c5 | doc011_p1_c1 |
| transfer-evaluation-experience | cross_document | doc006_p4_c8, doc005_p6_c46 | doc183_p4_c1 |
| major-change-core-catalog | scope_exception | doc010_p3_c8 | doc010_p3_c7 |
| transfer-grade-threshold | scope_exception | doc006_p4_c7 | doc005_p4_c27 |
| graduation-application-procedure | navigation | doc010_p1_c2 | doc161_p3_c1 |
| meningitis-required-papers | navigation | doc139_p4_c1 | doc139_p1_c1 |
| meningitis-online-exemption | scope_exception | doc139_p6_c1 | doc139_p2_c1 |
| meningitis-orion-upload | compound | doc139_p5_c1 | doc139_p4_c1 |
| grade-appeal-not-clerical | compound | doc005_p3_c21, doc005_p3_c22 | doc005_p3_c18 |
| major-versus-latin-honors | compound | doc010_p2_c5, doc010_p2_c6 | doc005_p2_c14 |
| unspecified-cs-catalog | ambiguous_time | doc038_p1_c4, doc042_p1_c4 | doc038_p1_c4, doc042_p1_c4 |
| unspecified-engineering-program | ambiguous_program | doc038_p1_c4, doc031_p1_c4 | doc038_p1_c4, doc031_p1_c4 |

## Validation and initial results

Validation: 25 cases, zero oracle-infeasible answerable cases, zero duplicate
shared-dev queries, 18 focused tests passed. All baseline index selections and
production final IDs/reasons/metrics matched on this dataset.

| Variant | Evidence recall | Complete evidence | Context precision | MRR | Correct ambiguity abstention |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 0.760870 | 0.695652 | 0.326087 | 0.702899 | 0.000000 |
| program_only | 0.782609 | 0.695652 | 0.334783 | 0.740580 | 0.000000 |
| catalog_only | 0.826087 | 0.782609 | 0.352174 | 0.753623 | 0.000000 |
| combined | 0.847826 | 0.782609 | 0.360870 | 0.807971 | 0.000000 |
| sufficiency_only | 0.739130 | 0.695652 | 0.317391 | 0.659420 | 0.000000 |
| combined_sufficiency | 0.804348 | 0.739130 | 0.343478 | 0.764493 | 0.000000 |

These are a different dataset and cannot be compared directly with shared-dev
aggregate scores. No factual generated-answer accuracy is measured. Precision
uses the existing per-answerable-question context metric, not fixed-denominator
precision@5. Abstentions score zero for evidence recall and context precision.

Combined ranking raises complete evidence from 16/23 to 18/23. Adding sufficiency
reduces this to 17/23: it falsely refuses the fully covered same-year-degree-totals
case. The one-anchor body check fails on the query wording even though the correct
numeric evidence is selected. This is a real regression requiring further design,
not permission to add a question-ID exception.

Recall falls 4.348 percentage points versus combined ranking when sufficiency is
added (84.783% to 80.435%), exceeding a 2-point loss gate against ranking alone.
Compared with production baseline, combined sufficiency still improves recall
(76.087% to 80.435%); report both comparisons rather than choosing a flattering one.
Sufficiency-only loses 2.174 points versus baseline, also over the proposed gate.
Both ambiguity cases are accepted by every variant (false acceptance 2/2). These
small-sample results do not estimate general unanswerable performance.

Candidate diagnostics show missing required evidence for ce-calculus-and-grades,
meningitis-online-exemption, and grade-appeal-not-clerical. Oracle feasibility does
not imply those passages pass the candidate pool/score filters. A reranker cannot
recover excluded candidates.

The JSON experiment report includes every eligible candidate's original and
precision scores, precision rank, supported evidence-group indices, candidate
coverage per group, and which authored hard negatives were actually admitted.
These label-based diagnostics are computed after ranking/timing, never used by
runtime scoring or sufficiency checks. Full selected IDs, rejection reasons,
per-query metric changes, provenance and latency are also retained in ignored
`evaluate/runs/mentee-4/` output.

Recommendation: keep sufficiency experimental. Review its false refusal and add
paraphrase tests before recommending integration. Retain the frozen first-run
results when developing later changes. No runtime rules were tuned on these cases
as part of authoring or the initial evaluation.

Fixture SHA-256: `064deb4224fabbfb8f9a38d2ac9ac9ebc5d0ae84611407a4c4a1e8bc8d52ec79`.
Corpus SHA-256: `f096b8331bc8355d067b590bcde12ff9b4589634f81c91d08098e1e5d879b60c`.

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

## Final review update

Production now reranks the admitted postings-based candidate pool before budgeted selection.
See [retrieval documentation](../../documentation/retrieval.md) for the live path and
integrated validation. These experiments remain available for feature comparisons.
