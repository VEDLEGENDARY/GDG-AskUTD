# Running the integrated app

The repository root contains both the Next.js UI and the FastAPI backend.
The browser calls same-origin `/api/*` endpoints; Next.js forwards them to the
server-only `API_BASE_URL`. No provider credentials enter the browser bundle.

## Local development

Use Python 3.12+ and Node.js 22.18+:

```sh
python -m pip install -r requirements-runtime.txt
npm ci
npm run dev:all
```

Open http://localhost:3000. The launcher starts the API on 127.0.0.1:8000,
waits for its health check, then starts Next.js. Ctrl+C stops both. It reads
an optional root `.env` and defaults to `LLM_PROVIDER=extractive`, `USE_STUBS=0`.
If using a virtual environment, set `PYTHON` to its Python executable. On Windows
without an override, the launcher uses `py`; on other platforms it uses `python3`.

For separate terminals:

```sh
# Terminal 1, export LLM_PROVIDER=extractive first.
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# Terminal 2
npm run dev
```

PowerShell environment syntax is `$env:LLM_PROVIDER='extractive'`; POSIX shells
use `export LLM_PROVIDER=extractive`. All commands run from the repository root.
`requirements-runtime.txt` is the small production dependency set for the current
lexical retriever. The larger `requirements.txt` is for optional model experiments.

## Containers

With the Docker engine running:

```sh
docker compose up --build
```

This builds the API and web images, waits for the API to become healthy, and
exposes the UI at http://localhost:3000 and API at http://localhost:8000.
The web build proxies to `http://api:8000` inside the Compose network. The API
image includes chunks, registry, retrieval config and the evaluator module used
by lexical retrieval. SQLite is stored in the `askutd-storage` named volume.

Both default to real retrieval with extractive generation, not sample responses.
`USE_STUBS=1` is an explicit developer override only. Missing real modules fail
startup instead of silently switching the application to stubs.

To enable the optional Ollama service, set `LLM_PROVIDER=ollama` in `.env`, then:

```sh
docker compose --profile llm up --build -d
docker compose exec ollama ollama pull llama3.2:3b
```

The model download is only needed for Ollama. With extractive generation the app
needs no GPU, model, API key, external generation service or network call.

## Configuration

Copy `.env.example` to `.env` if you want to override defaults. Do not commit `.env`.

| Variable | Purpose |
| --- | --- |
| `API_BASE_URL` | Next.js server-side API destination, default `http://127.0.0.1:8000`; set before building a separately hosted frontend |
| `LLM_PROVIDER` | `extractive`, `ollama`, or `openai_compat`; launcher and Compose default to extractive |
| `OLLAMA_HOST`, `OLLAMA_MODEL` | Local Ollama URL/model; Compose sets the service URL automatically |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` | Hosted OpenAI-compatible provider settings, backend only |
| `USE_STUBS` | `0` for the real pipeline; `1` for explicit sample development mode |
| `DATABASE_PATH` | API SQLite path; Compose fixes this to its persistent volume |
| `CORS_ORIGINS` | Used only by clients calling the API directly; browser UI uses the same-origin proxy |
| `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS` | Per-client API request limits |

If starting uvicorn manually without `.env` or shell overrides, its historical
provider default is Ollama. Set `LLM_PROVIDER=extractive` to avoid the remote-model
timeout before fallback. Rebuild Next.js when changing its proxy destination.

## User flow

1. A starter question or the composer sends a validated question plus up to six
   prior user/assistant turns to `/api/chat/stream`.
2. FastAPI retrieves passages, checks whether it should abstain and generates a
   cited answer. SSE events update the text, citation list and completion state.
3. Citation markers jump to the matching source cards. Registry URLs open the
   original source; missing URLs are labeled instead of fabricated.
4. A completed response can receive feedback using its stored request ID. FastAPI
   persists request analytics and feedback in SQLite.
5. Conversations are stored only in this browser, capped at 30 conversations and
   20 exchanges each. They are not cross-device accounts or public share links.
   Copy answer copies text and source links. Errors retain the question and offer
   retry; failed or incomplete answers are excluded from follow-up history.

The collection is a snapshot and answers can be wrong or outdated. Confirm
requirements and dates with the relevant UT Dallas office. Private student
records are unavailable.

## Verification

```sh
npm test
npm run build
python -m pip install httpx numpy onnxruntime
python -m unittest discover -s backend/tests -p 'test_*.py'
python -m unittest discover -s evaluate -p 'test_*.py'
python evaluate/evaluate_chunks.py --validate-only
docker compose config --quiet
```

Browser verification on November 9, 2026 confirmed a drop-class answer with
three linked citations, a graduate-student follow-up, persisted feedback, an
out-of-scope refusal, and restoration of both conversations after reload. API
logs showed successful streaming requests and feedback HTTP 204. Frontend tests
cover chunked SSE, final citation replacement, errors, premature disconnect and
feedback failures. Backend tests exercise real retrieval/generation and SQLite.
The Docker engine was stopped on the verification machine: Compose configuration
was validated, but image builds and container startup were not executed.

The CI workflow installs runtime dependencies, runs the backend/evaluator tests,
validates benchmark labels, and runs frontend tests and a production build.
Do not rerun the held-out retrieval benchmark while changing integration code;
Task 1's frozen test results remain in `documentation/retrieval.md`.
