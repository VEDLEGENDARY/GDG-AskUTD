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
Report paths cannot overwrite the selected inputs or be inside chunk directories.
`--query`, `--validate-only`, and `--export-branch` are separate modes and cannot
be combined.

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

| Setting | Meaning |
| --- | --- |
| `top_k` | Maximum chunks returned per query. |
| `candidate_pool` | Highest-scoring candidates considered for final selection. |
| `bm25_k1` | How much repeated terms contribute to BM25 relevance. |
| `bm25_b` | Strength of BM25 chunk-length normalization, from 0 to 1. |
| `lexical_weight` | BM25 share of text relevance; the rest is TF-IDF cosine. |
| `metadata_weight` | Metadata share of relevance; the rest is text relevance. |
| `diversity_lambda` | Relevance share of selection; lower values favor diversity. |
| `min_score` | Relevance threshold; chunks must also have a positive score. |
| `max_per_document` | Maximum selected chunks from one document. |
| `min_chunk_words` | Minimum whitespace-separated words in an eligible chunk. |
| `max_chunk_words` | Maximum whitespace-separated words in an eligible chunk. |
| `context_budget` | Maximum estimated tokens including titles and headings. |

## Hard benchmark (v2)

Add new question objects below your `// Lokesh questions:` or
`// Shaju questions:` heading in `questions.json`. Keep a comma between question
objects, including the last new question and the next existing question. The
evaluator ignores full-line `//` comments; ordinary JSON tools may flag these
comments because they are an extension to strict JSON. Inline comments are not
supported. The headings do not change a question's `split`.

For example, add an object like this under your heading, with a comma before the
next object. Give it a unique ID and query, select `dev` or `test`, and use phrases
that actually occur in the labeled document:

```json
{
  "id": "lokesh-course-load-contact",
  "query": "Who handles a question about how many credits I am taking?",
  "split": "dev",
  "category": "registration",
  "unanswerable": false,
  "evidence": [
    {"doc_id": "doc109", "all_of": ["records@utdallas.edu"]}
  ]
}
```

For an unanswerable question, set `unanswerable` to `true`, use `evidence: []`,
and add `unanswerable_reason` explaining why the corpus cannot answer it. Do not
make up evidence to force a question into the answerable category. Validate both
splits after editing. Trailing commas are not supported.

Existing questions are grouped in separate **DEV** and **TEST** blocks. The
`--split test` command validates evidence and scores only the TEST questions;
the 32 DEV questions are for tuning and do not contribute to `test.json`.
Likewise, `--split dev` does not validate evidence or score the TEST questions.
Every entry must still declare a valid `split`, and the whole file must parse.
Author headings, question IDs, categories, and ordering do not change retrieval
or per-question scores. The query drives retrieval and the evidence/unanswerable
labels determine grading; categories only group report summaries.

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

Each unanswerable case includes an `unanswerable_reason` for label review.
Scores on different question sets are not directly comparable; check
`questions_sha256` before comparing runs.

Evidence is labeled by document scope and normalized phrases rather than chunk
IDs. Each group is one required part of the requested answer. Every group must
be covered for `complete_evidence` credit; retrieving just one correct part is
insufficient. Within a group:

- `doc_id` restricts support to one document, including the correct catalog year.
- `doc_ids` permits explicitly labeled equivalent sources for duplicated policy
  text; use exactly one of `doc_id` and `doc_ids`.
- `all_of` requires every listed phrase in a supporting chunk. This avoids
  awarding a fact based on just a common fragment. Matching uses normalized
  whole words, so `six` cannot match `sixteen`.
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
groups, unknown evidence fields, duplicate JSON keys, non-JSON numeric constants,
and duplicate normalized queries within the selected split. The regression
checks additionally validate both splits together to catch cross-split duplicates.
Validation also searches for an oracle selection covering all evidence under the active length filters,
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
IDs. Every selected-split evidence group must still be present in the resulting corpus;
if not, review the question set explicitly before comparing scores.

Run evaluator regression checks with:

```powershell
python -m unittest discover -s evaluate -p "test_*.py"
```

Successful runs exit with status 0. Invalid input and infeasible validation exit
with status 1 and a diagnostic; conflicting or invalid command arguments exit
with status 2. Normal scoring still exits 0 when questions are infeasible, with
those IDs explicitly listed in the report. A successful exit does not mean a
perfect retrieval score.
