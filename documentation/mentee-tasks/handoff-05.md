# Handoff 05: Retrieval efficiency with ranking parity

Branch `codex/mentee-5-efficiency`, based on mentor commit
`f763b1c75302879d25035445b12b5757746b3970` (`git rev-parse HEAD` before any change).

## Summary

`LexicalIndex.search` used to score every chunk in the corpus for every query. It now visits
only chunks that share at least one query term with their body or their title/heading, using
a precomputed inverted index. Results are bit-identical to the baseline on every query tested
(ordered IDs equal, score difference 0.0, same token counts, caps and budget).

| Real corpus (2,998 indexed chunks, 102 dev queries, 100 warm runs) | Baseline | Optimized | Change |
| --- | --- | --- | --- |
| Warm search p50 | 21.19 ms | 1.85 ms | -91.2% |
| Warm search p95 | 34.46 ms | 4.88 ms | -85.8% |
| Cold index build p50 (5 processes) | 156 ms | 191 ms | +21.9% |
| Index retained memory (tracemalloc) | 16.2 MB | 19.1 MB | +18.0% |
| Index construction peak memory | 16.2 MB | 20.0 MB | +23.4% |
| First search after build | 10.2 ms | 1.3 ms | -87.6% |
| `eval_retrieval.py --split dev` p95 (end to end) | 32.0 ms | 4.0 ms | -87.6% |
| Dev retrieval metrics | identical | identical | 0 per-query changes |

The suggested targets (at least 20% lower warm p95, at most 25% memory growth) are met. The
cost is about 35 ms more one-time index construction, paid once per process by the
`lru_cache` in `retrieval.py`.

## Changed files (all owned by mentee 5)

| File | Change |
| --- | --- |
| `backend/app/retrieval_support/index.py` | Postings-based candidate generation, request-local accumulators, bounded top-candidate selection, incremental MMR redundancy, defensive result rows. Same constructor and `search(query, top_k)` signature; still subclasses `ev.Retriever`, keeps `lengths`, `norms`, `meta`, `costs`. |
| `backend/app/retrieval_support/postings.py` | New. Immutable flat (CSR style) postings: per term chunk positions, BM25 weight, TF-IDF weight; separate metadata postings. |
| `backend/tests/test_mentee5_efficiency.py` | New. 12 parity and safety tests (synthetic and real corpus). |
| `scripts/mentee5_benchmark.py` | New. Parity, warm/cold latency, memory, concurrency and synthetic scaling; JSON plus console. |
| `evaluate/mentee5/baseline_index.py` | New. Verbatim frozen copy of the baseline `LexicalIndex` (class renamed). Test-only. |
| `evaluate/mentee5/stress_queries.json`, `synthetic.py`, `README.md` | New development fixtures. |
| `documentation/mentee-tasks/handoff-05.md` | This report. |

No shared files, config, corpus, labels, tokenizer, weights, thresholds or MMR logic changed.

## Profile (before optimizing)

`cProfile` over the 102 dev queries on the baseline:

- 6.5 s total for 102 searches (about 64 ms each under the profiler, 22 ms without).
- The per-chunk cosine generator (`sum(v*vec.get(t, 0) ...)` for all 2,998 chunks) was 2.1 s
  cumulative, the per-chunk BM25 generator 2.0 s, `dict.get` 0.9 s and `Counter.__missing__`
  0.3 s (4.5 million lookups of query terms absent from a chunk).
- The full `sorted()` of all 2,998 scores was 0.2 s; MMR cosine recomputation 0.27 s.
- Cold construction: 0.29 s profiled, dominated by tokenization (`re.findall`, `tokens`) and
  TF-IDF vector building inside `ev.Retriever.__init__`, which is shared evaluator code and
  was left unchanged.

Conclusion: warm time was almost entirely full-corpus scans for terms that are not in the
chunk. That is what postings remove.

## Implementation and why it is equivalent

1. **Candidate pruning.** A chunk with no query term in its body or metadata has BM25 = 0,
   cosine = 0 and metadata overlap = 0, so its score is exactly `0.0`. The baseline drops it
   with `scores[i] > 0`. Visiting only body-postings union metadata-postings chunks therefore
   cannot remove any result. Metadata-only matches come from the metadata postings and are
   kept (tested with a title-only term).
2. **BM25 normalization before pruning.** `scale = max(bm)` over the corpus. Unvisited chunks
   contribute 0, so the max over visited chunks is the same value. No pruning happens before
   normalization.
3. **Bit-identical sums.** Per-posting BM25 weights use the exact baseline expression
   `idf*tf*(k1+1)/(tf+k1*(1-b+b*len/avg))`. Contributions are collected per chunk in the same
   term order as the baseline (`terms` set order for BM25, `qv` order for cosine) and added
   with builtin `sum()`. This matters: Python 3.12 `sum()` uses compensated float summation, so
   a running `+=` (my first version) matched IDs but differed by up to 1.7e-16 in scores. The
   baseline's skipped zero terms do not change a compensated sum, so results are exact.
4. **Top-candidate selection.** `heapq.nsmallest(candidate_pool, ...)` with key
   `(-score, chunk_id, position)` replaces sorting all chunks. The threshold filter keeps a
   prefix of the sorted order, so filtering first then taking the top `candidate_pool` gives
   the same pool, in the same order, with the same stable tie-breaks.
5. **MMR.** Same objective and tie-break key. Max redundancy against the selected set is kept
   per candidate and updated with one cosine per new selection (max is order independent),
   instead of recomputing all pairs each round. Sums of squares are cached with the same
   expression as `ev.cosine`.
6. **State.** All query state is request-local. The index holds only immutable features, so
   concurrent calls on one instance are safe (tested with 8 threads, identical to serial).
   No query-result cache was added. If the `Settings` object is mutated after construction,
   BM25 weights are rebuilt on the next search instead of being served stale.
7. **Returned rows.** Each hit is a fresh dict; nested mutable values are deep-copied, and
   `chunk_id`/`doc_id` used for ranking are snapshotted at build time. Mutating results or the
   caller's chunk dicts cannot corrupt later queries (tested).

Score tolerance: documented as 1e-9 absolute; the observed maximum difference is 0.0 on dev,
stress and synthetic sets.

## Complexity

Let N be indexed chunks, P the total postings (sum of distinct terms per chunk, about 100k
here), q the distinct query terms, and C the chunks sharing a query term.

| | Baseline | Optimized |
| --- | --- | --- |
| Build | O(P) (in `ev.Retriever`) | O(P) plus one more O(P) pass for postings |
| Search scoring | O(N * q) dictionary probes | O(sum of postings lengths of query terms) = O(C * q) at worst |
| Pool selection | O(N log N) sort | O(C log pool) |
| MMR | O(k^2 * pool) cosines | O(k * pool) cosines |
| Extra memory | none | about 20 bytes per posting (int32 position, two float64) plus per-term offsets |

Common query terms still produce large candidate sets, which is why p95 improves less than
p50. Synthetic scaling (below) shows the same: the gain shrinks when the vocabulary is small
and most chunks share common words.

## Parity results

| Set | Queries | Hits compared | ID mismatches | Max score diff |
| --- | --- | --- | --- | --- |
| Real dev split, top_k=8 | 102 | 405 | 0 | 0.0 |
| Stress fixtures, top_k=8 | 12 | 65 | 0 | 0.0 |
| Synthetic 3,000 chunks | 60 | 408 | 0 | 0.0 |
| Synthetic 12,000 chunks | 60 | 419 | 0 | 0.0 |
| `eval_retrieval.py --split dev` | 102 | per-query `chunk_ids` and `reason` | 0 | n/a |

The tests also check top_k 1..8, the prefix property, 13 settings extremes (min_score 0 and 1,
candidate_pool 8 and 3000, max_per_document 1, context_budget 150, lexical/metadata weight 0
and 1, diversity 0 and 1, altered BM25 k1/b), duplicate chunk IDs and tied scores, empty,
stopword-only, punctuation-only and unknown-term queries, and top_k=0.

## Benchmark details

Machine: Windows 11 (10.0.26200), Intel64 Family 6 Model 170 (22 logical CPUs), CPython 3.12.5.
Corpus sha256 `a9df682e64e4d7a2626123541b41bb4003dc3fa578ac02136448506f5d084a7e`
(3,003 chunks loaded, 2,998 after length filters, vocabulary 7,556).
Questions sha256 `1bd70731ab578587a9fbc34940157b62b96ed2b2518b86fb62634d8cb4f20385`, dev split.
Settings: `backend/retrieval_config.json` unchanged (candidate_pool 50, k1 1.5, b 0.75,
lexical 0.5, metadata 0.4, lambda 0.9, min_score 0.3, cap 5, budget 1200), top_k 5 for timing.

Method: one untimed warm-up pass, then 100 timed passes over the 102 dev queries per
implementation (10,200 samples each), alternating implementation order per pass. Cold build
is measured in 5 fresh processes per implementation; memory with `tracemalloc` in a separate
fresh process. Context size is unchanged by construction (average 395.3 estimated tokens on
dev, identical before and after).

Adversarial stress queries (12 queries, 10 runs): p50 14.26 -> 0.75 ms, p95 43.48 -> 4.43 ms.
The worst case is the 200x repeated query (many terms, large candidate set).

Concurrency: 510 searches on 8 threads against one shared instance, results identical to
serial execution. (CPython's GIL means threads do not speed up this CPU-bound code.)

**Synthetic corpora (not real corpus timings):**

| SYNTHETIC | Warm p50 | Warm p95 | Build p50 | Index memory |
| --- | --- | --- | --- | --- |
| 3,000 chunks | 19.49 -> 4.94 ms | 38.22 -> 14.64 ms | 157 -> 179 ms | 12.6 -> 14.6 MB (+16%) |
| 12,000 chunks | 62.68 -> 25.29 ms | 141.93 -> 76.03 ms | 555 -> 674 ms | 50.2 -> 58.3 MB (+16%) |

The synthetic vocabulary is deliberately small (about 90 words), so most chunks share query
terms; it is a harder case for pruning than the real corpus.

## Ablations

| Variant | Warm p95 | Memory | Build | Notes |
| --- | --- | --- | --- | --- |
| Postings with running `+=` sums | similar | similar | similar | IDs equal, scores off by up to 1.7e-16. Rejected. |
| One `array` per term per field | 4.27 ms (-87.0%) | +29.7% | +43% | Fails the 25% memory target. |
| Flat arrays, TF-IDF looked up in `vectors` dicts | 5.92 ms (-79.1%, 10 runs) | +12.7% | +26% | Smallest memory, slower search. |
| **Flat arrays with TF-IDF weights (final)** | 4.88 ms (-85.8%) | +18.0% | +22% | Chosen balance. |

## Reproduce

```powershell
git rev-parse HEAD
py -m unittest discover -s backend/tests -p "test_*.py"
py -m unittest backend.tests.test_mentee5_efficiency -v
py scripts/mentee5_benchmark.py --json evaluate/runs/mentee-5/benchmark.json
py scripts/eval_retrieval.py --split dev --json evaluate/runs/mentee-5/after-dev.json
```

The "before" eval was produced by running `scripts/eval_retrieval.py` in a process where
`backend.app.retrieval.LexicalIndex` was replaced by `evaluate.mentee5.baseline_index.BaselineLexicalIndex`
(no files edited). The benchmark always measures both implementations under identical
conditions in the same run.

Validation on this branch: backend suite 100 tests OK (1 skipped, as before; 88 existing plus
12 new). `evaluate/evaluate_chunks.py --validate-only` OK. Evaluator `unittest` discovery has 4
import errors locally only because `onnxruntime` is not installed on this machine (CI installs
it); those modules are unrelated to this change. `pytest` is not installed locally, so the
suite was run with `unittest`, which is what CI uses.

## Reranking hook (not implemented)

The natural boundary for mentee 4 is right after `pool = heapq.nsmallest(...)` in
`LexicalIndex.search`: at that point the pool holds at most `candidate_pool` chunk positions
with their final lexical scores, before MMR, document caps and the token budget. A future
mentor-owned change could split `search` into `candidates(query) -> list[dict]` (scored pool
rows) and `select(candidates, top_k)` (MMR, caps, budget), and let an adapter reorder or
rescore candidates in between. Because pruning only drops exact-zero scores, any reranker that
works on the pool sees the same candidates it would have seen with the full scan.

## Integration patch proposal (not applied)

No shared file needs to change: `retrieval.py` already constructs `LexicalIndex(chunks,
settings)` and calls `.search(query, top_k)`. The only proposal is the optional hook above,
which belongs to the mentor and mentee 4 integration step:

```diff
--- a/backend/app/retrieval_support/index.py
+++ b/backend/app/retrieval_support/index.py
@@ def search(self, query: str, top_k: int) -> list[dict]:
-        pool = heapq.nsmallest(s.candidate_pool, threshold_ok, key=lambda i: (-scores[i], ids[i], i))
+        pool = heapq.nsmallest(s.candidate_pool, threshold_ok, key=lambda i: (-scores[i], ids[i], i))
+        if self.rerank is not None:  # mentor-owned adapter, default None keeps parity
+            pool, scores = self.rerank(query, [self._row(i, scores[i]) for i in pool], pool, scores)
```

## Problems noticed outside my ownership (not patched)

1. The assignment says production has "coverage and phrase bonuses" absent from
   `ev.Retriever`. At `f763b1c` the production `index.py` has neither; it differs from
   `ev.Retriever` only by caching and an algebraically equivalent BM25 form. The baseline copy
   here is the code that actually exists at that commit.
2. Production BM25 sums iterate a `set` of query terms, whose order depends on string hash
   randomization (`PYTHONHASHSEED`). Scores can therefore differ in the last bit between
   processes, and an exact tie could in theory order differently across restarts.
   `ev.Retriever` uses `sorted(terms)`. I preserved the production behavior for parity; the
   mentor may want to switch to sorted order in a separate, measured change.
3. `ev.Retriever.__init__` (shared evaluator code) dominates cold build time through
   tokenization. Caching tokenized chunks there could cut cold start, but it is not mine to
   edit.

## Limitations

- Timings are from one Windows laptop; absolute numbers will differ on CI or servers.
- Cold build is about 35 ms slower; this is a one-time cost per process.
- Common-term queries still visit many chunks, so p95 gains are smaller than p50 gains.
- Parity is shown on dev, stress and synthetic sets, not proven for every possible input.
  The equivalence argument above plus the tests make a regression unlikely, but this is not a
  claim of 100% correctness.
- Retrieval metrics are unchanged by design; no claim is made about answer accuracy.
