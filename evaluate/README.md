# Retrieval evaluations

Run from the repository root with Python 3.10 or newer. This evaluator uses only
the Python standard library; no pip installs, API keys, or model downloads are
needed.

```powershell
python evaluate/evaluate_chunks.py --config evaluate/config.example.json --split dev --output evaluate/runs/dev.json
python evaluate/evaluate_chunks.py --config evaluate/config.example.json --split test --output evaluate/runs/test.json
```

On Windows, `py` can replace `python` if the Python launcher has an interpreter
installed. If neither works, install Python 3.10+ or use an existing interpreter's
full path. In PowerShell, invoke a quoted executable path with `&`.

The console prints the effective settings, benchmark validation, corpus audit,
and summary. The output JSON also includes corpus/question fingerprints, category
summaries, each question's retrieved chunks and metrics, and an `evidence_covered`
boolean for each required evidence group. Separate output paths keep dev and test reports from
overwriting each other. Generated runs and branch exports are ignored by Git.

## Tune and inspect

```powershell
python evaluate/evaluate_chunks.py --config evaluate/config.example.json --split dev --output evaluate/runs/tuned-dev.json
python evaluate/evaluate_chunks.py --query "What does FERPA protect?"
```

Change settings in a copy of `config.example.json` and pass that file using
`--config`; without the flag the evaluator loads `evaluate/config.example.json`
relative to the script. All setting values live in JSON; the Python class defines
only the schema and validation rules. Config files must include every setting;
missing and unknown keys produce an error instead of falling back to hidden values.
Tune on dev and reserve test for evaluating the final configuration. Test is a
public local split, so this is not a hidden or contamination-proof evaluation.

## Hard benchmark (v2)

The default `questions.json` contains **64 authored questions**, split evenly
between dev and test. Each split contains 24 answerable cases and 8 unanswerable
cases. Of the 48 answerable cases, 46 require multiple evidence groups. Challenges
include:

- Paraphrased situations and policy exceptions, rather than title lookups.
- Multi-part requests requiring two to four evidence groups, including facts
  spread across different documents.
- CS, CE, and SE plan comparisons where the catalog year and major matter.
- Nearby policy facts that cannot establish a personal decision, live balance,
  unspecified course equivalency, or an unpublished future catalog requirement.

Each unanswerable case includes an `unanswerable_reason` for label review. The
original 16-question benchmark is preserved in `questions.starter.json`, usable
with `--questions evaluate/questions.starter.json`. Scores on different question
sets are not directly comparable; check `questions_sha256` before comparing runs.
The scoring weights are unchanged from the starter benchmark.

Evidence is labeled by document scope and normalized phrases rather than chunk
IDs. Each group is one required part of the requested answer. Every group must
be covered for `complete_evidence` credit; retrieving just one correct part is
insufficient. Within a group:

- `doc_id` restricts support to one document, including the correct catalog year.
- `doc_ids` permits explicitly labeled equivalent sources for duplicated policy
  text; use exactly one of `doc_id` and `doc_ids`.
- `all_of` requires every listed phrase in a supporting chunk. This avoids
  awarding a fact based on just a common fragment.
- `any_of` accepts alternative phrasings. If both phrase fields are present,
  every `all_of` phrase and at least one `any_of` phrase must match.

The hard benchmark includes equivalent documents where the same labeled phrases
occur together, except when the question explicitly asks for a particular
catalog year or major. Other paraphrased valid sources may need manual label
review. These are lexical evidence checks, not semantic answer grading; a
different chunking strategy that separates required phrases may also need label
review. No LLM-generated answer is evaluated.

## Validate before scoring

```powershell
python evaluate/evaluate_chunks.py --config evaluate/config.example.json --split dev --validate-only
python evaluate/evaluate_chunks.py --config evaluate/config.example.json --split test --validate-only
```

Validation rejects missing evidence, malformed document scopes, duplicate evidence
groups, and duplicate normalized queries across either split. It also searches
for an oracle selection covering all evidence under the active length filters,
`top_k`, context budget, and per-document cap. `--validate-only` exits with status
1 if any answerable question is infeasible; normal evaluations report those IDs
without suppressing the run. All answerable v2 cases are feasible with the example
config. This oracle ignores ranking, candidate-pool size, and minimum relevance
score: it checks whether the context constraints themselves make success possible,
not whether the retriever will find the evidence. It cannot verify the truth or
completeness of human labels or prove absence of answers to unanswerable cases.

## Metrics

- `evidence_recall`: fraction of labeled evidence groups retrieved.
- `complete_evidence`: whether all labeled evidence groups were retrieved.
- `reciprocal_rank`: reciprocal rank of the first supporting chunk.
- `context_precision`: fraction of retrieved chunks supporting labeled evidence.
- `abstention_correct`: whether an unanswerable question returned zero chunks.
- `estimated_tokens`: context cost estimated as characters divided by four,
  rounded up per chunk, including metadata.
- `leaderboard_score`: 100 times the weighted sum of complete evidence (50%),
  evidence recall (20%), precision (15%), and correct abstention (15%). This is
  null for subsets lacking either answerable or unanswerable questions.

This evaluates offline BM25/TF-IDF retrieval, metadata weighting, and context
selection. It does not evaluate neural embeddings, an API, or generated answers.

## Compare chunking branches

Export a local Git ref without switching branches (choose a fresh destination):

```powershell
python evaluate/evaluate_chunks.py --export-branch HEAD --chunks evaluate/exports/baseline
python evaluate/evaluate_chunks.py --chunks evaluate/exports/baseline --split dev --output evaluate/runs/baseline-dev.json
```

Use `--match-documents OTHER_CHUNK_DIRECTORY` to restrict a run to shared document
IDs. Every labeled evidence group must still be present in the resulting corpus;
if not, review the question set explicitly before comparing scores.

Run evaluator regression checks with:

```powershell
python -m unittest discover -s evaluate -p "test_*.py"
```
