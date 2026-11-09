# GDG-AskUTD

AskUTD answers University of Texas at Dallas student questions from official UTD
pages, catalogs and policies. It retrieves the passages that matter, writes a short
answer that cites them with `[n]` markers, and says so plainly when the sources do not
contain the answer instead of guessing.

## Architecture

```
  Browser UI (Vercel)
        |   JSON and Server-Sent Events under /api
        v
  FastAPI app, backend/app (Task 3) ------------> SQLite: requests, feedback
        |
        |-- retrieval.retrieve(question)          (Task 1)
        |       reads backend/data/chunks/*.json and documents.json
        |       returns passages, or abstains when nothing is relevant
        |
        '-- generation.generate_answer(question, passages)   (Task 2)
                Ollama | OpenAI-compatible API | extractive fallback
                returns answer text with [n] citations

  Offline, not in the request path:
    raw_pdfs -> add_documents.py -> raw_text + chunks -> fix_chunks.py -> build_registry.py
    evaluate/evaluate_chunks.py (retrieval benchmark), scripts/eval_e2e.py (full pipeline)
```

## Quick start

Backend (Python 3.12):

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt
LLM_PROVIDER=extractive uvicorn backend.app.main:app --reload --port 8000
curl http://localhost:8000/api/health
```

UI: from the UI folder run `npm install` and `npm run dev`, with the API base URL set
to `http://localhost:8000`. Ollama, hosted models, Docker, hosting and the smoke test
checklist are in [`documentation/DEPLOY.md`](documentation/DEPLOY.md).

Evaluation and tests (standard library plus numpy and onnxruntime for the evaluator
tests; no GPU, keys or model downloads):

```bash
python evaluate/evaluate_chunks.py --validate-only
python evaluate/evaluate_chunks.py --split dev --output evaluate/runs/dev.json
python scripts/eval_e2e.py --split dev --json evaluate/runs/e2e_dev.json
python -m unittest discover -s evaluate -p "test_*.py"
python -m unittest discover -s backend/tests -p "test_*.py"
```

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/app/` | API server, retrieval and generation (Tasks 1 to 3); `types.py` is the shared contract. |
| `backend/data/raw_pdfs/` | Source PDFs printed from UTD pages and catalogs. |
| `backend/data/raw_text/` | Extracted text, one `docNNN.txt` per document (198). |
| `backend/data/chunks/` | Chunk JSON per document (198 docs, 3,003 chunks). |
| `backend/data/documents.json` | Registry: title, source URL, PDF and chunk count per doc. |
| `backend/data/doc_sources.json` | PDF for each doc added with `add_documents.py` (doc119 onward). |
| `backend/tests/` | Offline tests for the data, registry, cleanup and e2e script. |
| `evaluate/` | Retrieval evaluator, benchmark questions (`questions.json`) and experiments. |
| `scripts/` | `build_registry.py`, `audit_corpus.py`, `fix_chunks.py`, `eval_e2e.py`. |
| `documentation/` | Data notes (`data.md`), deployment (`DEPLOY.md`), naming and chunk merge notes. |
| `.github/workflows/ci.yml` | Tests, benchmark validation, em dash and file size checks. |
| `add_documents.py`, `pdf_to_text.py`, `fill_chunk_counts.py` | Turn new PDFs into text and chunks, validate chunk files. |

### Adding documents

Name the PDF after its URL (`documentation/naming.md`), put it in
`backend/data/raw_pdfs/`, then:

```bash
python add_documents.py backend/data/raw_pdfs/<file>.pdf
python scripts/fix_chunks.py --docs <new doc number>   # add a title to TITLES first
python scripts/build_registry.py
python evaluate/evaluate_chunks.py --validate-only
```

## Evaluation

Benchmark: 204 questions (102 dev, 102 test), 25 unanswerable per split. Retrieval
settings are tuned on dev only. Current numbers use the baseline lexical retriever and
the extractive fallback, because the backend modules are not merged yet:

| metric | dev | test |
| --- | --- | --- |
| retrieval leaderboard score | 51.31 | 55.76 |
| complete evidence (answerable) | 0.571 | 0.636 |
| abstained when unanswerable | 0.000 | 0.000 |
| citation validity | 1.000 | 1.000 |
| latency p50 ms | 33 | 33 |

Final numbers with Tasks 1 to 3 merged: to be filled in from
`python scripts/eval_e2e.py --split test` after integration (Day 3 or later). Score
history and metric definitions are in [`documentation/data.md`](documentation/data.md).

## Team and roles

| Area | Owner |
| --- | --- |
| Task 1: retrieval service (`backend/app/retrieval.py`) | to be filled in |
| Task 2: answer generation (`backend/app/generation.py`) | to be filled in |
| Task 3: API server, storage, Docker | to be filled in |
| Task 4: data, benchmark, end-to-end eval, CI, deploy docs | Nandhan |
| UI | to be filled in |

## Known limitations

- The baseline retriever never abstains, so unanswerable questions still get passages;
  abstention has to come from Task 1's threshold or Task 2's generator.
- The corpus is a snapshot of UTD pages around the 2026-2027 academic year. Dates,
  fees and contacts change; answers can be out of date.
- 41 of 198 documents have no source URL: 11 older docs whose PDF could not be matched
  safely, one PDF from a non-UTD host, and 29 pages saved under their title instead of
  their URL. Several engineering URLs are reconstructed from filenames and are low
  confidence (listed in `documentation/data.md`).
- Some text has PDF extraction artifacts such as words glued together.
- The benchmark grades evidence by exact phrases, so a correct passage worded
  differently counts as a miss.
- The assistant has no access to personal records (balances, holds, decisions) and
  should refuse those questions.
