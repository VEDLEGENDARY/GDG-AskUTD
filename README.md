# GDG-AskUTD

A retrieval-augmented question answering project over public University of Texas
at Dallas (UTD) web pages, catalogs, and policies. The goal is to answer student
questions with cited, grounded passages and to abstain when the corpus does not
contain the answer.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/data/raw_pdfs/` | Source PDFs printed from UTD web pages and catalogs (219 files). |
| `backend/data/raw_text/` | Plain-text extraction of each source document (118 files, `docNNN.txt`). |
| `backend/data/chunks/` | Semantic chunk JSON per document, with chunk IDs and metadata. |
| `evaluate/` | Retrieval evaluator, benchmark questions, and experiment modules. |
| `documentation/` | Team notes, including how the chunk corpus was merged. |
| `pdf_to_text.py` | Extracts text from `raw_pdfs/` into `raw_text/`. |
| `rename_raw_text.py` | Renames text files to the team naming convention. |
| `fill_chunk_counts.py` | Validates chunk JSON and fills `n_sentences` and `token_count`. |
| `requirements.txt` | Dependencies for the planned web backend and local models. |

## Running the retrieval evaluator

The evaluator uses only the Python standard library.

```bash
python evaluate/evaluate_chunks.py --config evaluate/config.example.json --split dev --output evaluate/runs/dev.json
python evaluate/evaluate_chunks.py --config evaluate/config.example.json --split test --output evaluate/runs/test.json
python evaluate/evaluate_chunks.py --query "What does FERPA protect?"
```

See [`evaluate/README.md`](evaluate/README.md) for every setting, the output
format, and the benchmark rules. Tune on the `dev` split and reserve `test` for
checking the final configuration.

Run the unit tests with:

```bash
cd evaluate && python -m unittest test_evaluate_chunks
```

## Extracting and chunking documents

```bash
python -m pip install pypdf
python pdf_to_text.py                       # PDFs in raw_pdfs/ to raw_text/
python fill_chunk_counts.py backend/data/chunks/doc006_example.json
```

Scanned or image-only PDFs need OCR before extraction.

## Status

- Corpus: 118 documents have text and chunk files. 51 PDFs added from the
  `Ariana-docs` branch do not yet have text or chunks and are not retrieved.
- Benchmark: 164 questions, 82 `dev` and 82 `test`. The validator currently
  reports infeasible questions under the 900-token budget, so
  `--validate-only` exits with status 1.
- Tests: `test_evaluate_chunks` has 4 failures and 1 error that still need
  investigation.

## Contributors

Team project for the UTD AskUTD initiative. See the commit history for individual contributions.
