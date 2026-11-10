# Mentee 1 regression fixtures and harness

`cases.json` is a manually verified development regression set for retrieval.
These are development examples, not a sealed holdout. `scripts/mentee1_eval.py`
validates them, runs any retrieval adapter on them (and on the existing
`questions.json` dev split), and compares two runs. Runtime retrieval never reads
these files; only the harness does.

## Commands

Run from the repository root (`py` on Windows, `python` elsewhere):

```sh
python scripts/mentee1_eval.py validate
python scripts/mentee1_eval.py run --adapter production --json evaluate/runs/mentee-1/production.json --markdown evaluate/runs/mentee-1/production.md
python scripts/mentee1_eval.py run --adapter evaluate/mentee1/example_adapters.py:ignore_history --json evaluate/runs/mentee-1/ignore-history.json
python scripts/mentee1_eval.py compare evaluate/runs/mentee-1/production.json evaluate/runs/mentee-1/ignore-history.json --markdown evaluate/runs/mentee-1/compare.md
python scripts/mentee1_eval.py peers --git-ref origin/codex/mentee-2-corpus
```

`run` defaults to suites `mentee1` and `dev`, `--top-k 5`, `--repeat 3` and
`--order id`. Built-in adapters are `production`, `production-no-reject`
(abstention-rule ablation) and `always-abstain` (sanity check). Any
`module:callable` or `path/to/file.py:callable` also works; see
`example_adapters.py`. The test split requires `--allow-test-split` because it is
a used regression set, not a tuning target. Generated output belongs in
`evaluate/runs/`, which Git ignores.

## Case schema (`schema_version` 1)

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Unique, lowercase, `m1-<category>-NN` |
| `category` | yes | `direct_lookup`, `paraphrase`, `abbreviation`, `population_contrast`, `time_contrast`, `compound`, `near_miss`, `unanswerable`, `follow_up` |
| `query` | yes | The student's question as typed |
| `history` | follow_up only | Prior turns, `[{"role": "user" or "assistant", "content": ...}]`, passed to the adapter as `Turn` objects |
| `unanswerable` | yes | `true` when the corpus cannot answer |
| `evidence` | yes | Evidence groups (empty for unanswerable) |
| `requirement` | answerable | Why each group is needed; multi-group text must say all groups are required |
| `distractors` | optional | `{chunk_id, reason}` chunks that look relevant but are the wrong population, time or context |
| `unanswerable_reason` | unanswerable | Why the corpus cannot answer, beyond a keyword miss |
| `absence_checks` | unanswerable | Searches and documents reviewed |
| `nearest_related` | unanswerable | `{chunk_id, reason}` closest related chunks that still do not answer |
| `unsupported_parts` | optional | Parts of an answerable question that the corpus cannot support |
| `notes` | optional | What makes the case hard |

Evidence group: `{"id", "support": [{"chunk_id", "quote"}], "not_equivalent": [{"chunk_id", "reason"}], "note"}`.

- **Groups are AND.** `complete_evidence` requires every group. A case that needs
  two facts has two groups.
- **Support entries are OR.** Each listed chunk alone supports that group for the
  question's population and time. Retrieval is credited only for listed chunk IDs.
- **Quotes are verified.** Each quote (at least three words) must occur in its
  chunk after the evaluator's normalization (case, punctuation and whitespace
  ignored, whole words only).
- **Same words, different meaning.** If a quote also occurs in any unlisted chunk,
  validation fails until that chunk is added as support or listed in
  `not_equivalent` with a reason (for example, another catalog year or the
  graduate catalog). Matching words or numbers alone never earns credit.
- **Follow-ups.** Assistant turns are previous system output and are never
  evidence. Labels describe chunks that support the resolved follow-up question.
  When the corpus cannot support the follow-up (for example, current enrollment),
  the case is unanswerable even if the first turn was answerable.

## Metrics

Per-case quality metrics use the same formulas as `evaluate_chunks.grade()`;
only the support test differs (labeled chunk IDs instead of phrase matching). A
unit test checks parity. The `dev` and `test` suites are graded with the
unchanged `ev.grade()`.

- **Evidence recall**: fraction of required groups covered by some returned chunk.
- **Complete evidence**: 1 when every group is covered, else 0.
- **Reciprocal rank**: 1 / rank of the first returned chunk that supports any group.
- **Context precision**: fraction of returned chunks that support some group.
- **Abstention correctness** (unanswerable only): 1 when nothing is returned.

The report separates these into:

- **Quality**: recall, complete evidence, RR and precision over answerable cases only.
- **Answerability**: false refusal (answerable cases with no passages) and false
  acceptance (unanswerable cases that received passages), reported as counts and rates.
- **Distractors**: cases where a labeled wrong-population or wrong-time chunk
  outranks all evidence.
- **Efficiency**: cold load, warm p50/p95/max over all repetitions, context tokens.
- **Integrity**: budget, document cap, `top_k`, duplicate or unknown IDs, passage
  text not matching the corpus, unsafe/missing/unregistered URLs, invalid scores,
  abstention contract and nondeterministic rankings. Any violation fails `--gate`.

None of these are answer correctness. A retrieved chunk that supports the answer
does not prove that generation used it correctly. Rank scores are recorded raw
and are not probabilities.
