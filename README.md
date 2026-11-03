# GDG-AskUTD

A retrieval-augmented question answering project over public University of Texas
at Dallas (UTD) web pages, catalogs, and policies. The goal is to answer student
questions with cited, grounded passages and to abstain when the corpus does not
contain the answer.

## Quick start

```bash
python -m pip install pypdf          # only needed for PDF extraction
python evaluate/evaluate_chunks.py --query "What does FERPA protect?"
python evaluate/evaluate_chunks.py --config evaluate/config.example.json --split dev --output evaluate/runs/dev.json
cd evaluate && python -m unittest test_evaluate_chunks
```

The evaluator uses only the Python standard library. See
[`evaluate/README.md`](evaluate/README.md) for every setting and the output format.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/data/raw_pdfs/` | Source PDFs printed from UTD pages and catalogs (219 files). |
| `backend/data/raw_text/` | Extracted text, one `docNNN.txt` per document (169 files). |
| `backend/data/chunks/` | Sentence-aligned chunk JSON per document (169 files). |
| `backend/data/doc_sources.json` | PDF filename for each doc added with `add_documents.py` (doc119 onward). |
| `evaluate/` | Retrieval evaluator, benchmark questions, and experiment modules. |
| `documentation/` | Team notes, including how the chunk corpus was merged. |
| `add_documents.py` | Turns new PDFs into numbered text and chunk files. |
| `pdf_to_text.py` | Extracts text from PDFs (pypdf, with PyMuPDF or pypdfium2 fallback). |
| `fill_chunk_counts.py` | Validates chunk JSON and fills `n_sentences` and `token_count`. |
| `rename_raw_text.py` | Renames text files to the `docNNN.txt` convention. |

## Adding documents

Drop the new PDF in `backend/data/raw_pdfs/`, named after its URL (see
`documentation/naming.md`), then run:

```bash
python add_documents.py backend/data/raw_pdfs/<file>.pdf
python evaluate/evaluate_chunks.py --validate-only
```

The script assigns the next `docNNN` id, writes the text and chunk files, and
records the mapping in `doc_sources.json`. Scanned or image-only PDFs need OCR first.

## Current status

- Corpus: 169 documents and about 2,900 chunks. Docs 119 to 169 came from the
  `Ariana-docs` branch (registrar, financial aid, transfer credit, admissions).
- Benchmark: 164 questions (82 dev, 82 test), including 100 added from
  `nandhan-more-questions`. `--validate-only` passes.
- Baseline retrieval (lexical BM25 plus metadata, `config.example.json`, tuned on
  dev only): dev leaderboard 45.8, test 53.2. Abstention on unanswerable
  questions is still 0, which is the main open problem.
- Tests: all evaluator test modules pass. The semantic tests are skipped unless
  the MiniLM models are cached under `~/.cache/huggingface`.
- Not in the repo yet: the web backend. `requirements.txt` lists FastAPI,
  ChromaDB, and Ollama for it.

## Next steps

1. Improve abstention so unanswerable questions return no passages.
2. Build the FastAPI backend and connect an answer generator.
3. Process the remaining original PDFs that have no doc id mapping.
