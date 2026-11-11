# Mentee 4 handoff: precision ranking and evidence sufficiency

## Review status and recommendation

The independent module, 25 source-backed dev cases, adapter, six-way ablations,
pool sweep and integration proposal are ready for review. Nothing is committed,
pushed, merged or active in production. Shared runtime, config, corpus, labels,
API and generation files remain unchanged.

Recommend mentor review of program/catalog reranking with candidate_pool=50 and
all existing selection constraints. Keep new sufficiency checks disabled by
default: they reject some incomplete answers but lower answerable acceptance and
do not improve labeled-unanswerable rejection. A fresh mentor-sealed holdout is
still needed before final runtime integration. This is not a claim that the full
assignment, including PR and merge, is complete.

Historical experiments and earlier environment failures are preserved in
`evaluate/mentee4/development-notes.md`. This report supersedes their status notes.
Full fixture inventory and experiment details are in `evaluate/mentee4/README.md`.

## Baseline, ownership and reproducibility

- Branch: codex/mentee-4-precision-ranking.
- Baseline/current HEAD: f763b1c75302879d25035445b12b5757746b3970; implementation is uncommitted.
- Python 3.12.0, macOS 26.3.2, Apple arm64.
- Corpus: 198 documents, 3,003 passages, 2,998 after existing length filters.
- Corpus SHA-256: f096b8331bc8355d067b590bcde12ff9b4589634f81c91d08098e1e5d879b60c.
- Shared dev question SHA-256: ad2d747edc4d82920feec73aad69f50e477e5a91b4cd724066cf1c41541e87f5 (102 questions, 77 answerable, 25 unanswerable).
- Hard-case SHA-256: 064deb4224fabbfb8f9a38d2ac9ac9ebc5d0ae84611407a4c4a1e8bc8d52ec79 (25 questions, 23 answerable, two underspecified requests).
- No shared test split was evaluated or tuned against. Existing shared dev and new hard cases were reused during development; neither is a holdout.
- Mentor confirmation of the frozen baseline and a separate writable checkout was not established in this session; confirm team coordination before submission.

Owned deliverables:

- backend/app/retrieval_support/precision.py
- backend/tests/test_mentee4_precision.py
- evaluate/mentee4/adapter.py
- evaluate/mentee4/run_experiments.py
- evaluate/mentee4/run_pool_sweep.py
- evaluate/mentee4/hard_cases.json
- evaluate/mentee4/hard_cases.py
- evaluate/mentee4/integration-proposal.patch
- evaluate/mentee4/validate_integration_proposal.py
- evaluate/mentee4/README.md and development-notes.md
- documentation/mentee-tasks/handoff-04.md

Generated JSON reports are ignored by Git under evaluate/runs/mentee-4.
Use fresh report filenames when repeating commands; runners refuse overwrites.

## Implementation rationale and constraints

`rerank(query, candidates)` returns copied dictionaries, preserves IDs/text and
retrieval_score, and adds precision_score. Explicit CS/CE program matches add
0.10, program mismatches subtract 0.10, and explicit disjoint full catalog ranges
subtract 0.10. Unknown scope stays neutral. Ties use chunk ID. Features can be
independently disabled for ablations. No new runtime dependency or service is used.

`evidence_reason(query, hits)` is an additional post-selection heuristic. It checks
co-located catalog/program scope, recognized elective and division quantities in
body text, and narrow paired standing/declaration and eligibility/documents
intents. Different passages may cover different facets. Metadata cannot supply
numeric facts. Explicit exclusion phrases are handled for scope requirements.
None means these additional checks pass, not semantic proof that an answer exists.

The adapter reproduces original BM25/TF-IDF/metadata scores, admits candidates,
reranks before MMR, and enforces positive original-score thresholds, document caps
and token budget before existing/new rejection checks. It never reranks only the
already selected five hits. Candidate logs and evidence labels are diagnostic
only and never influence runtime features. top_k remains 1..8; experiments use 5.

Settings are unchanged: candidate_pool=50, min_score=0.3, max_per_document=5,
context_budget=1,200, diversity_lambda=0.9; all other settings are in each report.
The score adjustments are transparent experimental constants, not probabilities.

## Final dev ablations

Metrics use the existing document-scoped phrase labels. They do not measure
factual correctness of generated answers. Recall and complete evidence average
over answerable questions; context precision divides relevant passages by actual
returned passages per answerable question, with abstentions scored zero.

| Dataset / variant | Recall | Complete evidence | Context precision | MRR | Correct abstention | Score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Shared dev / baseline | 0.730519 | 0.571429 | 0.483983 | 0.742424 | 0.760000 | 61.841558 |
| Shared dev / program_only | 0.730519 | 0.571429 | 0.483983 | 0.742424 | 0.760000 | 61.841558 |
| Shared dev / catalog_only | 0.730519 | 0.571429 | 0.483983 | 0.751082 | 0.760000 | 61.841558 |
| Shared dev / combined | 0.733766 | 0.584416 | 0.486580 | 0.751082 | 0.760000 | 62.594805 |
| Shared dev / sufficiency_only | 0.711039 | 0.571429 | 0.460606 | 0.703463 | 0.760000 | 61.101299 |
| Shared dev / combined_sufficiency | 0.720779 | 0.584416 | 0.468398 | 0.712121 | 0.760000 | 62.062338 |
| Hard cases / baseline | 0.760870 | 0.695652 | 0.326087 | 0.702899 | 0.000000 | 54.891304 |
| Hard cases / program_only | 0.782609 | 0.695652 | 0.334783 | 0.740580 | 0.000000 | 55.456522 |
| Hard cases / catalog_only | 0.826087 | 0.782609 | 0.352174 | 0.753623 | 0.000000 | 60.934783 |
| Hard cases / combined | 0.847826 | 0.782609 | 0.360870 | 0.807971 | 0.000000 | 61.500000 |
| Hard cases / sufficiency_only | 0.739130 | 0.695652 | 0.317391 | 0.659420 | 0.000000 | 54.326087 |
| Hard cases / combined_sufficiency | 0.847826 | 0.782609 | 0.360870 | 0.807971 | 0.000000 | 61.500000 |

On shared dev, ranking alone increases context precision by 0.260 percentage
points, recall by 0.325 points, and complete evidence by 1.299 points. Neither
feature alone improves complete evidence; combined features complete the CS
comparison. The proposed ranking precision/recall gate is met on this dev set,
but the gain is small and requires holdout review.

Combined sufficiency loses 1.299 recall points versus ranking alone (0.974 versus
production baseline), within a 2-point loss bound, but reduces context precision.
It preserves 45/77 complete shared-dev responses and 18/23 complete hard-case
responses. Sufficiency-only loses 2.174 recall points on hard cases, exceeding the
proposed gate for that combination. Do not report all feature combinations as passing.

| Dataset / variant | Accepted | Complete evidence among accepted | Answerable acceptance | Unanswerable false acceptance | Mean tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Shared dev / baseline | 79 | 0.556962 | 0.948052 | 0.240000 | 395.324 |
| Shared dev / combined | 80 | 0.562500 | 0.961039 | 0.240000 | 396.608 |
| Shared dev / combined_sufficiency | 76 | 0.592105 | 0.909091 | 0.240000 | 380.304 |
| Hard cases / baseline | 23 | 0.695652 | 0.913043 | 1.000000 | 599.320 |
| Hard cases / combined | 25 | 0.720000 | 1.000000 | 1.000000 | 678.400 |
| Hard cases / combined_sufficiency | 25 | 0.720000 | 1.000000 | 1.000000 | 678.400 |

Complete evidence among accepted responses includes accepted unanswerables in
its denominator. Answerable acceptance counts non-abstentions, not completeness;
complete-evidence coverage is reported separately. Abstention changes should
never be presented as evidence recovery. The two ambiguity cases expect
clarification for a single numeric answer; conditional explanation of both
alternatives could be valid but is not evaluated by this retrieval-only grader.

## Regressions and wrong matches

Ranking-only selected-ID changes on shared dev:

- nandhan-dev-cs-2016-vs-2020-electives: completes evidence by promoting
  doc042_p1_c5 over wrong-program/year near matches.
- dev-hard-cs-year-electives: improves first supporting rank, but remains incomplete.
- dev-hard-ce-calculus-exemption: newly accepted with zero labeled evidence;
  sufficiency rejects it. This is a known ranking-only acceptance risk.
- dev-hard-same-year-different-major: changes selected IDs without evidence gain.

Sufficiency additionally withholds incomplete selections for class-standing,
CS-year electives, CE-calculus, and same-year/different-major questions. Their
ranking-only evidence recalls were 0.5, 0.25, 0 and 0.25 respectively. No complete
response is lost in the final combined runs, but answerable acceptance falls from
96.104% to 90.909% on shared dev. False acceptance on labeled unanswerables remains
6/25. Both ambiguity cases remain accepted. These unresolved limitations are why
new sufficiency is proposed disabled by default.

The first sufficiency version falsely rejected the fully covered same-year degree
comparison because of arbitrary query-word anchors. It was revised using scoped
quantity patterns and general paraphrase/exclusion tests, without changing labels.
The frozen first-run results and later dev revisions remain in development notes.
Full per-query IDs, scores, reasons and metric deltas are in generated reports.

## Candidate-pool sweep and precision@5

Pools 50, 100, 200 and all 2,998 indexed passages produced identical final IDs and
rejection decisions for every variant on both datasets. Only seven questions
admitted extra candidates at 100, with no added labeled candidate coverage.
Maximum score-eligible counts were 82 on shared dev and 97 on hard cases. Larger
pools therefore provided no benefit; retain 50.

Candidate evidence recall stayed 0.797619 shared dev and 0.913043 hard cases;
candidate complete evidence stayed 0.636364 and 0.869565 respectively. Candidate
coverage is measured before selection and does not imply feasible joint context.

Fixed-denominator precision@5 divides relevant returned passages by five slots
per answerable question (empty slots count zero). It is distinct from context
precision. From the sweep, ranking-only precision@5 is 0.236364 shared dev and
0.234783 hard cases, unchanged across pool limits. All variant values are in JSON.

Missing examples: doc011_p1_c1 ranks 66 at 0.192614, doc075_p1_c17 ranks 54 at
0.268620, doc139_p6_c1 ranks 4 at 0.291064 and doc005_p3_c22 ranks 14 at 0.174065.
They fail original score admission even in a full-index pool. Lowering candidate
admission alone would not authorize final selection below the original 0.3
threshold. Query/scoring recalibration is mentor-owned follow-up work.

## Latency and provenance

Final standard runners measure one warmed request per query/variant in fixed
order; timings exclude grading, parity assertions and diagnostics. Treat small
changes as noise, not a performance win. Cold index loading is recorded separately.

| Dataset / variant | Cold index ms | Warm p50 ms | Warm p95 ms |
| --- | ---: | ---: | ---: |
| Shared dev / baseline | 136.715 | 10.836 | 14.259 |
| Shared dev / combined | 136.715 | 11.171 | 14.526 |
| Shared dev / combined_sufficiency | 136.715 | 10.964 | 14.325 |
| Hard cases / baseline | 138.244 | 10.651 | 15.117 |
| Hard cases / combined | 138.244 | 10.591 | 16.215 |
| Hard cases / combined_sufficiency | 138.244 | 10.540 | 15.594 |

Pool-sweep latency is reconstructed from a reused scoring sample plus selection
and checks; it excludes admission and is not production end-to-end latency.
Do not compare it directly with standard-runner timings. Reports record hashes,
settings, environment, baseline SHA, working-tree status and detailed failures;
the sweep also fingerprints its experiment code. No neural model size/cost applies.

## Validation completed

Only existing CI test packages were installed locally: httpx 0.28.1 (httpcore
1.0.9), NumPy 2.0.2 and ONNX Runtime 1.31.1 plus their dependencies. No requirement
file changed. Starlette emits an httpx deprecation warning but CI still specifies
httpx; this is not an assignment-specific runtime dependency.

| Check | Result |
| --- | --- |
| pytest backend/tests | 113 passed, 1 live-Ollama test skipped; 420 subtests passed |
| CI unittest backend discovery | 114 tests, OK, 1 live-Ollama skip |
| Focused precision tests | 26 pass and are included in both discovery modes |
| CI evaluator unittest discovery | 63 tests, OK, 8 skipped for absent cached model assets |
| Document tool tests | 5 passed |
| Shared dev benchmark label/oracle validation | 102 valid, no infeasible answerable cases |
| Hard-case quote/ID/negative validation | 25 valid, no infeasible cases or duplicate shared-dev queries |
| Frontend npm test | 4 passed |
| Frontend npm run build | passed outside sandbox; sandbox worker stalled and was interrupted |
| Code/docs em-dash and file-size hygiene | passed |
| Proposal git apply --check | passed; proposal not applied |
| Proposal in-memory index validation | 127 dev cases match baseline/adapter; top_k 1..8 preserved |

CI uses unittest, so the owned test file now exposes function tests through the
standard load_tests hook without requiring pytest. A literal Unicode dash in a
regex was replaced by the equivalent escape to satisfy repository hygiene.
The build-generated next-env.d.ts changes were restored; tracked shared files are
unchanged. Optional skipped model/live-service tests were not replaced by downloads
or external calls. This does not imply required remote CI checks have run.

## Reproducible commands

Run from repository root in the existing virtual environment. Fresh report names
are required if these files already exist.

```sh
.venv/bin/python3 -m pytest backend/tests -q
.venv/bin/python3 -m unittest discover -s backend/tests -p 'test_*.py'
.venv/bin/python3 -m unittest discover -s evaluate -p 'test_*.py'
.venv/bin/python3 -m unittest test_add_documents
.venv/bin/python3 evaluate/evaluate_chunks.py --validate-only
.venv/bin/python3 -m evaluate.mentee4.hard_cases
.venv/bin/python3 -m evaluate.mentee4.run_experiments --output evaluate/runs/mentee-4/final-review-shared-dev.json
.venv/bin/python3 -m evaluate.mentee4.run_experiments --hard-cases --output evaluate/runs/mentee-4/final-review-hard-cases.json
.venv/bin/python3 -m evaluate.mentee4.run_pool_sweep --output evaluate/runs/mentee-4/pool-sweep-dev.json
git apply --check evaluate/mentee4/integration-proposal.patch
.venv/bin/python3 -m evaluate.mentee4.validate_integration_proposal
npm test
npm run build
```

## Mentor integration proposal (not applied)

The following patch is also provided as evaluate/mentee4/integration-proposal.patch.
It applies to the current baseline index/service, not an unseen future efficiency
branch. Mentor must reconcile the callback seam with mentee 5 and follow the
agreed merge order. No mentee-owned index/query/shared config file was edited.

Default two-argument index.search remains backward compatible. The optional
keyword hook exposes the admitted pool before final MMR and uses precision_score
only for ranking; original scores remain unchanged for admission and citations.
Final selection is still performed by the existing index. Existing rejection runs
after selection; optional sufficiency then runs only if existing checks pass.
The proposed sufficiency flag is false by default. Mentor should not enable it
without explicitly accepting the documented refusal tradeoffs and holdout results.

In-memory validation verifies index behavior only. Service changes compile, but
actual integrated API tests are still required after mentor application. Public
retrieve, Passage and citation IDs remain unchanged. No production config change
or larger pool is proposed. Applying this patch would activate reranking; merely
merging this assignment's module does not activate it.

```diff
--- a/backend/app/retrieval_support/index.py
+++ b/backend/app/retrieval_support/index.py
@@ -17,8 +17,8 @@
         self.meta = [set(ev.tokens(ev.metadata(row))) for row in self.chunks]
         self.costs = [ev.cost(row) for row in self.chunks]
 
-    def search(self, query: str, top_k: int) -> list[dict]:
-        """Score candidates, then enforce MMR, document cap and token budget."""
+    def search(self, query: str, top_k: int, *, reranker=None) -> list[dict]:
+        """Score candidates, optionally rerank, then select within constraints."""
         s = self.s
         terms = set(ev.tokens(query))
         qv = self.vector(Counter(ev.tokens(query)))
@@ -37,6 +37,23 @@
             scores.append((1-s.metadata_weight)*lexical+s.metadata_weight*meta)
         pool = sorted(range(self.n), key=lambda i: (-scores[i], self.chunks[i]['chunk_id']))[:s.candidate_pool]
         pool = [i for i in pool if scores[i] > 0 and scores[i] >= s.min_score]
+        # Admission always uses original retrieval scores, before reranking.
+        ranking_scores = list(scores)
+        if reranker is not None:
+            candidates = [
+                {**self.chunks[i], 'retrieval_score': scores[i],
+                 'estimated_tokens': self.costs[i]} for i in pool
+            ]
+            ranked = reranker(query, candidates)
+            expected = {self.chunks[i]['chunk_id']: i for i in pool}
+            if (len(ranked) != len(pool)
+                    or {h['chunk_id'] for h in ranked} != set(expected)):
+                raise ValueError('reranker must preserve candidate IDs')
+            for hit in ranked:
+                score = hit['precision_score']
+                if type(score) not in (int, float) or not math.isfinite(score):
+                    raise ValueError('precision_score must be finite')
+                ranking_scores[expected[hit['chunk_id']]] = score
         selected: list[int] = []
         counts: Counter = Counter()
         used = 0
@@ -47,11 +64,12 @@
                 break
             def mmr(i: int) -> float:
                 redundancy = max((ev.cosine(self.vectors[i], self.vectors[j]) for j in selected), default=0)
-                return s.diversity_lambda*scores[i]-(1-s.diversity_lambda)*redundancy
-            best = min(feasible, key=lambda i: (-mmr(i), -scores[i], self.chunks[i]['chunk_id']))
+                return s.diversity_lambda*ranking_scores[i]-(1-s.diversity_lambda)*redundancy
+            best = min(feasible, key=lambda i: (-mmr(i), -ranking_scores[i], self.chunks[i]['chunk_id']))
             selected.append(best)
             pool.remove(best)
             counts[self.chunks[best]['doc_id']] += 1
             used += self.costs[best]
-        return [{**self.chunks[i], 'retrieval_score': scores[i], 'estimated_tokens': self.costs[i]}
+        return [{**self.chunks[i], 'retrieval_score': scores[i], 'estimated_tokens': self.costs[i],
+                 **({'precision_score': ranking_scores[i]} if reranker is not None else {})}
                 for i in selected]
--- a/backend/app/retrieval.py
+++ b/backend/app/retrieval.py
@@ -10,12 +10,15 @@
 from evaluate import evaluate_chunks as ev
 
 from .retrieval_support.index import LexicalIndex
+from .retrieval_support.precision import evidence_reason, rerank
 from .retrieval_support.query import reject, rewrite
 from .types import Passage, RetrievalResult, Turn
 
 ROOT = Path(__file__).resolve().parents[2]
 CONFIG = ROOT / 'backend' / 'retrieval_config.json'
 log = logging.getLogger(__name__)
+# Mentor enables only after reviewing additional refusals and holdout results.
+PRECISION_SUFFICIENCY_ENABLED = False
 
 
 def load_urls(path: Path) -> dict[str, str]:
@@ -53,8 +56,10 @@
     query = rewrite(query.strip()[:2000], history)
     try:
         index, config, urls, _ = _load()
-        hits = index.search(query, top_k)
+        hits = index.search(query, top_k, reranker=rerank)
         reason = reject(query, hits, config)
+        if reason is None and PRECISION_SUFFICIENCY_ENABLED:
+            reason = evidence_reason(query, hits)
         if reason:
             return RetrievalResult(abstain=True, reason=reason)
         return RetrievalResult(passages=[Passage(
```

## Remaining delivery and integration steps

- Confirm baseline/checkout coordination and review the documented tradeoffs.
- Review and commit only the owned files, push the branch, open a PR, satisfy
  reviews/CI, update against main in the mentor sequence, merge and verify remote main.
  None of these publication/merge steps has happened in this session.
- Mentor integrates shared runtime wiring only after coordination and checks;
  use a fresh sealed holdout once for final integration and report regressions.
- Re-run integrated API/retrieval checks after upstream changes; current proposal
  syntax/index parity does not substitute for combined runtime validation.
- Current heuristics recognize only two spelled-out programs and explicit full
  year ranges. Negation parsing, population ranking, general navigation detection,
  general multi-part entailment, ambiguity and score calibration remain limited.
  This implementation/report may be rejected if its modest gains or tradeoffs
  are not acceptable. There is no claim of universal correctness.
