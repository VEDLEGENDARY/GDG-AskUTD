# Mentee 5: Retrieval efficiency with ranking parity

## Your goal

Make the existing production lexical retriever faster and more memory-efficient without changing which passages it returns. Ranking experiments belong to mentee 4.

## Files you own

- `backend/app/retrieval_support/index.py` (existing; sole owner)
- `backend/app/retrieval_support/postings.py` (optional new helper)
- `backend/tests/test_mentee5_efficiency.py` (new)
- `scripts/mentee5_benchmark.py` (new)
- `evaluate/mentee5/` (new development fixtures)
- `documentation/mentee-tasks/handoff-05.md` (new)

Read `evaluate/evaluate_chunks.py`, `backend/app/retrieval.py`, the retrieval config and existing tests. Keep `LexicalIndex(chunks, settings)` and `.search(query, top_k)` compatible. Do not change scoring weights, tokenizer, thresholds, MMR, corpus or shared configuration.

## Work plan

1. Profile cold construction and warm searches independently. Identify tokenization, full corpus scans, query-level calculations repeated per chunk, full sorting and repeated cosine work. Measure before optimizing.
2. Store a baseline reference implementation under `evaluate/mentee5/` from the mentor's exact commit. It is test-only and must never be imported by production. Compare to THIS implementation, not `ev.Retriever`, because production now has coverage and phrase bonuses absent from that older scorer.
3. Hoist query-only calculations outside per-document loops. Consider precomputed postings, metadata lookup, cached norms, sparse dot products and bounded top-candidate selection. Candidate pruning must preserve every chunk that could score above threshold, including metadata-only matches. Unknown terms and zero-score cases need explicit handling.
4. Preserve score values within a documented floating-point tolerance (suggested 1e-9 absolute), ordered IDs exactly, context token counts, document caps and deterministic tie-breaks. Do not prune before computing BM25 normalization unless equivalent results are demonstrated.
5. Avoid unbounded query-result caching and mutable global query state. Prefer immutable index features and request-local variables. If any cache is justified, bound it and specify invalidation; corpus loading/reset remains service-owned.
6. Benchmark fixed dev queries across at least 100 warm runs, with warm-up excluded, and multiple independent processes for cold measurements. Report p50/p95, index construction, peak memory, corpus size and hardware. Include adversarial long/unknown-term queries and concurrent calls to the same index instance.
7. Test a larger synthetic corpus to show scaling; label synthetic timings separately from actual corpus timings. Ensure returned rows do not expose mutable references that corrupt future queries.

## Acceptance criteria

- Exact ordered-ID parity on dev and your stress fixtures, score tolerance met, no budget/cap violations.
- Suggest a target of at least 20% lower warm p95 with no more than 25% memory growth; do not sacrifice correctness to hit it. Report an honest no-improvement result if appropriate.
- Existing backend tests pass. No network, new dependency or generation/UI changes.
- Benchmark script runs independently and produces machine-readable JSON plus concise console output.

## Handoff to mentor

Deliver profiles, parity results, timing/memory results and complexity explanation. Explain where candidate generation could later expose a reranking hook, but do not implement mentee 4's integration. The mentor first verifies parity, then integrates ranking changes and repeats the quality/latency evaluation together.

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
