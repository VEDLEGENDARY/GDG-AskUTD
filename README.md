# GDG-AskUTD

AskUTD answers University of Texas at Dallas student questions from official UTD
pages, catalogs and policies. It retrieves the passages that matter, writes a short
answer that cites them with `[n]` markers, and says so plainly when the sources do not
contain the answer instead of guessing.

## Architecture

```
  Browser UI (Next.js, repository root)
        |   same-origin /api proxy to API_BASE_URL
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
python -m pip install -r requirements-runtime.txt
npm ci
npm run dev:all
```

Open [AskUTD locally](http://localhost:3000). Both servers start together, with real
lexical retrieval and offline extractive answers by default. On Windows, use
`.venv\Scripts\Activate.ps1` to activate the environment; set `PYTHON` to your
virtual environment's Python executable if the launcher does not pick it up.
Requires Node.js 22.18+ and Python 3.12+. No model download or API key is needed.

For the complete container stack, run `docker compose up --build` from this root.
It starts Next.js and the API with persistent SQLite storage. See
[`documentation/DEPLOY.md`](documentation/DEPLOY.md) for separate-server commands,
provider configuration and verification.

Evaluation and tests (standard library plus numpy and onnxruntime for the evaluator
tests; no GPU, keys or model downloads):

```bash
python evaluate/evaluate_chunks.py --validate-only
python evaluate/evaluate_chunks.py --split dev --output evaluate/runs/dev.json
python scripts/eval_e2e.py --split dev --json evaluate/runs/e2e_dev.json
python -m unittest discover -s evaluate -p "test_*.py"
python -m unittest discover -s backend/tests -p "test_*.py"
npm test
npm run build
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
settings are tuned on dev only. All backend modules are merged. Final Task 1
retrieval results use the production lexical service:

| metric | dev | test |
| --- | --- | --- |
| retrieval leaderboard score | 61.84 | 59.71 |
| complete evidence (answerable) | 0.571 | 0.610 |
| abstained when unanswerable | 0.760 | 0.400 |
| latency p95 ms | 62 | 48 |

These are retrieval metrics, not end-to-end answer-quality scores. The test split
was run once with frozen settings. See [`documentation/retrieval.md`](documentation/retrieval.md)
for methodology and [`documentation/data.md`](documentation/data.md) for earlier results.

## Team and roles

| Area | Owner |
| --- | --- |
| Task 1: retrieval service (`backend/app/retrieval.py`) | to be filled in |
| Task 2: answer generation (`backend/app/generation.py`) | to be filled in |
| Task 3: API server, storage, Docker | to be filled in |
| Task 4: data, benchmark, end-to-end eval, CI, deploy docs | Nandhan |
| UI | to be filled in |

## Known limitations

- Retrieval and generation both abstain, but unsupported questions can still receive
  an answer. Test retrieval abstention accuracy is 40%.
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
