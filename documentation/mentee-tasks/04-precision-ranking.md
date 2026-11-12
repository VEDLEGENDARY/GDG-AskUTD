# Mentee 4: Precision ranking and evidence sufficiency

## Your goal

Promote passages that actually answer the question and reject convincing near matches, while maintaining evidence recall. Keep this as an independent module so mentee 5 can optimize the index simultaneously.

## Files you own

- `backend/app/retrieval_support/precision.py` (new)
- `backend/tests/test_mentee4_precision.py` (new)
- `evaluate/mentee4/` (new adapter, fixtures, candidate logs and experiments)
- `documentation/mentee-tasks/handoff-04.md` (new)

Read the index, query service, retrieval config and evaluator. Do not edit `index.py`, `query.py`, `retrieval.py` or shared config.

## Agreed module boundary

Implement `rerank(query: str, candidates: list[dict]) -> list[dict]` and `evidence_reason(query: str, hits: list[dict]) -> str | None`. Input candidates contain `chunk_id`, `doc_id`, `text`, `source_title`, `section_heading`, `retrieval_score`, `estimated_tokens`. Return new dictionaries without mutating inputs, inventing text or adding candidates. Preserve `retrieval_score` unchanged; use `precision_score` for your ranking score. Break ties by chunk ID. `evidence_reason` returns None only when your additional checks pass; existing production checks still apply.

These functions do not perform final context selection. The mentor's integration must rerank the candidate pool BEFORE final MMR/budget selection and apply evidence checks AFTER selection. Never just rerank the existing five selected results and claim candidate-recall gains.

## Work plan

1. Categorize hard negatives: wrong student population, wrong policy year, title-only matches, generic navigation and partial evidence for multi-part questions.
2. Develop explainable content/metadata/phrase features. Keep query-sensitive conditions intact. Do not treat a repeated keyword, document title or year anywhere in a passage set as proof of an answer.
3. Build a standalone adapter in your directory that reproduces baseline candidate scoring, exposes a larger candidate pool to `rerank`, then reapplies existing MMR, document caps, thresholds and token budget. Keep this experiment copy clearly isolated; submit an integration proposal instead of editing the index. Compare it against the production baseline to expose adapter drift.
4. Evaluate with and without reranking and sufficiency checks. New sufficiency checks may increase abstention: show answered precision AND answerable recall, plus false acceptance on unanswerables. Do not tune solely for fewer wrong answers by refusing all questions.
5. Add at least 25 hard cases with source IDs/quotes and explicit hard-negative IDs. Include compound questions needing multiple passages, ambiguous time scope and genuine cross-document evidence.
6. Keep deterministic offline behavior with existing dependencies. An optional neural reranker is a separate experiment, never a required service. Document runtime/model size if explored.

## Acceptance criteria

- Tests prove input immutability, valid IDs, stable ties, unchanged source text and budget-safe adapter results.
- Compare precision@k, complete evidence, recall, MRR, abstention tradeoffs and latency on dev.
- Target a measurable precision gain with at most a 2-percentage-point absolute recall loss; this is a proposed merge gate, not permission to hide regressions. If missed, deliver the evidence and recommendation honestly.

## Handoff to mentor

Provide feature ablations, thresholds, ranked candidate examples and a proposed integration diff showing candidate generation -> rerank -> budgeted selection -> evidence checks. Coordinate the interface with mentee 5 through the mentor; do not edit their branch or files.

## Rules for all five mentees

You are working simultaneously with four others. Start from the SAME mentor-provided commit, which must include the current retrieval and grounding changes. Record its SHA with `git rev-parse HEAD`. Each person uses a separate clone or worktree and branch; never share a writable checkout. Use branch `codex/mentee-N-TOPIC` with your number/topic substituted. The mentor supplies the baseline snapshot before work starts.

Only modify the files assigned below. Reading other files is allowed. If you discover a problem outside your ownership, describe it in your handoff; do not patch it. Do not reformat unrelated files. Do not change frontend, API schemas, generation, prompts, shared dependencies, production config, corpus, or existing benchmark labels unless your assignment explicitly grants ownership. New Python code should run offline with existing dependencies. Optional model-based experiments must remain separate and record model/version/cost; they cannot become a required dependency.

Preserve `retrieve(query, top_k=5, history=None) -> RetrievalResult`, `LexicalIndex.search(query, top_k) -> list[dict]`, `Passage` and citation IDs. Production top_k remains 1..8. Selected results must respect context budget, document caps, positive score thresholds and deterministic tie-breaking. Never invent document text, source URLs, labels or facts. Preserve numbers, negations, eligibility and time scope. Missing evidence must remain an abstention; do not weaken source matching to make scores look better.

Tune on dev only. The existing test split has already been used during development, so it is a regression set, not an untouched holdout. Do not repeatedly tune against it. Each mentee's new examples live in their own directory; the evaluation owner collects them by reading, not by editing those files. A fresh holdout should be authored and sealed by the mentor before final integration.

### Ownership map

| Mentee | Exclusive area | Main objective |
| --- | --- | --- |
| 1 | New evaluation harness and regression fixtures | Trustworthy measurement |
| 2 | New corpus audit/cleanup proposal tool | Better source quality |
| 3 | `retrieval_support/query.py` and own tests | Better query interpretation |
| 4 | New precision/reranking module | Better evidence selection |
| 5 | `retrieval_support/index.py` and own tests | Faster equivalent search |

The mentor alone integrates new modules into `backend/app/retrieval.py`, changes `backend/retrieval_config.json`, edits shared evaluator code and applies corpus replacements. Mentee 5 must not integrate mentee 4's ranking changes into the index during parallel development. Mentee 4 receives candidate dictionaries through an adapter and does not edit the index. Everyone can finish independently of the others.

### Baseline and reporting

Run from the repository root (Windows: `py`; elsewhere use the available Python interpreter):

```powershell
py -m pytest backend/tests -q
py scripts/eval_retrieval.py --split dev --json evaluate/runs/mentee-N/baseline-dev.json
```

Replace N in commands. Generated runs are ignored by Git; summarize results and include commands in your owned handoff Markdown. Record commit, Python version, machine, corpus hash, settings, query set, cold index load, warmed p50/p95 latency, context size and failures. Use identical conditions for before/after comparisons. Do not claim improved factual answer accuracy based only on retrieval metrics.

Every handoff includes changed files, implementation rationale, reproducible commands, before/after metrics, per-query regressions, ablations, limitations and a precise integration patch proposal in a fenced diff (not applied to shared files). A proposal may legitimately be rejected if its tradeoffs are poor. Do not claim 100% correctness.

### Mentor merge sequence

1. Freeze and share a baseline commit containing these assignments plus the current retrieval work. Keep new runtime work on separate branches.
2. Merge the evaluation harness, then verify and merge the efficiency branch against that frozen baseline. Accept only ranking-equivalent performance changes at this stage.
3. Review the corpus proposal and apply approved stable-ID cleanup separately. Rebuild and remeasure so its effect is isolated.
4. Merge query understanding, then integrate the precision module at the candidate-pool boundary. Test each change alone before combining them. Recalibrate production thresholds only after the score behavior is understood.
5. Run backend tests and the full production retrieval evaluation on the combined result. Use the sealed holdout once for the final decision and report regressions/tradeoffs. Do not assume individually positive changes combine positively.

No mentee must wait for these merges to finish their own independent implementation and report. Shared-file integration belongs to the mentor, not an unassigned sixth contributor.

## Required delivery: create a PR and merge into main

Your assignment includes implementing your changes, opening a pull request against `main`, and merging that PR into `main` after the checks below pass. Do not stop at a local commit or an open PR. This instruction authorizes merging your assignment's owned files; it does not expand your file ownership to shared integration points.

1. Commit only your assigned implementation, tests, fixtures and handoff report to your own branch. Check the staged diff for unrelated changes, secrets and generated output.
2. Push your branch and create a PR targeting `main`. Use a clear title naming your retrieval improvement. Include the problem, approach, owned files, before/after metrics, validation commands/results, regressions and any mentor-owned integration still required. Link your handoff report.
3. Before merging, fetch the latest `main` and update your branch using the repository's normal merge/rebase policy. Resolve conflicts only within your ownership. Coordinate with the mentor if a conflict touches another mentee's work or a shared integration file. Never overwrite their changes or force-push `main`.
4. Rerun your assignment's tests and `py -m pytest backend/tests -q` against the updated branch. Run any additional repository-required checks. Recheck quality/parity measurements if upstream retrieval or corpus changes affect your results. If CI is configured, wait for required checks to pass.
5. Merge the PR into `main` using the repository's allowed merge method after required reviews and branch protections are satisfied. Do not bypass protections, dismiss reviews or merge with failing required checks. If permissions, a required review or an integration dependency prevents merging, leave the concrete PR ready, notify the mentor with its link and the exact blocker, and finish the merge when that blocker is cleared.
6. Verify that the PR is marked merged and its changes are on remote `main`. Report the PR URL, merge commit SHA and final validation results to the mentor. Opening the PR alone is not completion.

All five mentees may develop and open PRs simultaneously. Coordinate merges in the mentor merge sequence above; do not race to merge against an outdated base. Mentees 2 and 4 merge their independently tested tools/modules and reports, while production corpus application and shared runtime wiring remain mentor-owned follow-up work. A merged module must not be described as active in production until that integration is completed and verified.
