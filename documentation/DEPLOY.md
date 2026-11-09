# Deploying GDG-AskUTD

How to run the API and UI locally, with Docker, with Ollama or a hosted
OpenAI-compatible model, and how to put it on free hosting. The HTTP routes are
described in `documentation/api.md` (Task 3).

> Assumptions, to confirm once Task 3 merges: the FastAPI app is
> `backend.app.main:app` and listens on port 8000, the Dockerfile is at the repo root,
> and the UI reads the API base URL from an environment variable. Adjust the commands
> below if Task 3 chose different names.

## Environment variables

All are optional. Put them in a `.env` file (ignored by git) or export them.

| variable | default | meaning |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | `ollama`, `openai_compat` or `extractive` (no LLM, quotes passages) |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2:3b` | Ollama model tag |
| `OPENAI_BASE_URL` | none | base URL of an OpenAI-compatible API, ending in `/v1` |
| `OPENAI_API_KEY` | none | key for that API; never commit it |
| `OPENAI_MODEL` | none | model name at that provider |
| `USE_STUBS` | `0` | `1` serves stub retrieval and answers (UI work without models) |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | comma-separated allowed UI origins |
| `DATABASE_PATH` | `backend/storage/askutd.db` | SQLite file for requests and feedback |
| `LOG_LEVEL` | `INFO` | Python logging level |

## Run locally

Python 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
LLM_PROVIDER=extractive uvicorn backend.app.main:app --reload --port 8000
curl http://localhost:8000/api/health
```

`extractive` needs no model and is the quickest way to check the whole flow. For UI
work without the retrieval stack, use `USE_STUBS=1`.

Run the UI in its own terminal (from the UI folder) with `npm install` and
`npm run dev`, and point it at `http://localhost:8000`. Its dev server origin must be
in `CORS_ORIGINS` (ports 3000 and 5173 are allowed by default).

### With Ollama

```bash
ollama pull llama3.2:3b
ollama serve                       # skip if the Ollama app is already running
LLM_PROVIDER=ollama uvicorn backend.app.main:app --port 8000
```

`/api/health` reports the active model in `llm`. If Ollama is down the API still
answers with the extractive fallback instead of failing.

### With an OpenAI-compatible provider

Any service that implements the OpenAI chat completions API works (for example Groq,
OpenRouter, Together, or a local vLLM or LM Studio server).

```bash
export LLM_PROVIDER=openai_compat
export OPENAI_BASE_URL=https://api.groq.com/openai/v1
export OPENAI_API_KEY=...          # from the provider dashboard
export OPENAI_MODEL=llama-3.1-8b-instant
uvicorn backend.app.main:app --port 8000
```

## Run with Docker

```bash
docker build -t askutd-api .
docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=extractive \
  -v askutd-storage:/app/backend/storage \
  askutd-api
```

The named volume keeps the SQLite database between container restarts. To use Ollama
running on the host, add `-e LLM_PROVIDER=ollama -e OLLAMA_HOST=http://host.docker.internal:11434`
(on Linux also add `--add-host=host.docker.internal:host-gateway`).

## Free hosting

**API on Render** (Docker web service):

1. New, Web Service, connect the GitHub repo, runtime Docker, branch `main`.
2. Set environment variables: `LLM_PROVIDER=openai_compat` plus the three `OPENAI_*`
   values, and `CORS_ORIGINS=https://<your-ui>.vercel.app`.
3. Health check path: `/api/health`.

**API on Fly.io** (alternative): `fly launch` (detects the Dockerfile, internal port
8000), `fly secrets set OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENAI_MODEL=...`,
`fly volumes create askutd_storage --size 1` mounted at `/app/backend/storage`, then
`fly deploy`.

Free tier limits to plan around:

- Ollama does not fit in free instances; use `openai_compat` (or `extractive`).
- Free instances have about 512 MB of RAM. If the retriever loads an embedding model
  plus torch it may not fit; use the lexical retriever there or a larger instance.
- Render free services sleep after about 15 minutes idle (the first request then takes
  up to a minute) and their disk is wiped on every deploy, so feedback in SQLite is lost
  unless you attach a disk. Fly volumes persist.

**UI on Vercel**: import the repo, set the root directory to the UI folder, set the API
base URL variable to the Render or Fly URL, and deploy. Add the Vercel domain (and any
preview domains you use) to `CORS_ORIGINS` on the API.

## Smoke test checklist

Run against the deployed API (replace `$API`), then click through the UI once.

- [ ] `GET $API/api/health` returns `status: ok`, `documents: 198`, about 3,000 `chunks`,
      and the expected `retriever` and `llm`.
- [ ] `GET $API/api/documents` lists 198 documents; URLs open the right UTD pages.
- [ ] `GET $API/api/suggestions` returns 6 questions.
- [ ] `POST $API/api/chat` with "When are Fall 2026 final exams for full-term classes?"
      answers with `[n]` markers that each match a returned citation.
- [ ] `POST $API/api/chat` with "How much do I still owe the Bursar?" abstains.
- [ ] `POST $API/api/chat` with an empty question returns the `{"error": {...}}` shape
      and a 4xx status.
- [ ] `POST $API/api/chat/stream` sends `meta`, `citations`, `token` events and ends
      with `done`.
- [ ] `POST $API/api/feedback` with the `request_id` from a chat returns 204.
- [ ] The UI loads from its real domain with no CORS errors in the browser console.

## Rollback

- Code: revert the bad merge on `main` (`git revert -m 1 <merge-sha>`) and push; both
  hosts redeploy from `main`.
- Faster, without a commit: Render has "Rollback" on any earlier deploy; on Fly run
  `fly releases` and `fly deploy --image <previous image>`; on Vercel open the previous
  deployment and choose "Promote to Production".
- Data: the corpus, registry and benchmark live in git, so reverting the commit restores
  them. Copy the SQLite file (`DATABASE_PATH`) before any deploy that changes its schema.
