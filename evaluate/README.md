# Retrieval evaluations

Run from the repository root with Python 3.10 or newer. This evaluator uses only
the Python standard library; no pip installs, API keys, or model downloads are
needed.

```powershell
python evaluate/evaluate_chunks.py --split dev --output evaluate/runs/dev.json
python evaluate/evaluate_chunks.py --split test --output evaluate/runs/test.json
```

On Windows, `py` can replace `python` if the Python launcher has an interpreter
installed. If neither works, install Python 3.10+ or use an existing interpreter's
full path. In PowerShell, invoke a quoted executable path with `&`.

The console prints a corpus audit and summary. The output JSON includes settings,
corpus/question fingerprints, category summaries, and each question's retrieved
chunks and metrics. Separate output paths keep dev and test reports from
overwriting each other. Generated runs and branch exports are ignored by Git.

## Tune and inspect

```powershell
python evaluate/evaluate_chunks.py --config evaluate/config.example.json --split dev --output evaluate/runs/tuned-dev.json
python evaluate/evaluate_chunks.py --query "What does FERPA protect?"
```

Change settings in a copy of `config.example.json` and tune on dev. Reserve test
for evaluating the final configuration. Both splits currently contain eight
handwritten starter questions, covering registration, privacy, graduation,
out-of-scope requests, and private information unavailable in the corpus. This
small set covers four documents; extend and review it before treating scores as
representative of the full corpus.

Evidence is labeled by document ID and normalized supporting phrases rather than
chunk IDs, so labels can survive rechunking. A matching phrase establishes
relevance for this lightweight benchmark; it does not prove that every part of an
answer is supported. Review alternative valid sources before interpreting misses:
the evaluator requires the labeled document ID even if another document repeats
the same answer. Unanswerable cases are requests the static corpus cannot resolve.

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
