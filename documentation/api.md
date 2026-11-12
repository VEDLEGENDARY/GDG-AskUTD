# GDG-AskUTD HTTP API

The API listens on `http://localhost:8000`. Install `requirements-runtime.txt`, set
`LLM_PROVIDER=extractive`, then run `python -m uvicorn backend.app.main:app --port 8000`.
Alternatively, `npm run dev:all` starts both the real API and frontend. The browser
uses the frontend's same-origin `/api` proxy. See [DEPLOY.md](DEPLOY.md) for setup.
`USE_STUBS=1` explicitly enables sample development responses; it is not required
to run the app offline.

Every JSON error uses `{"error":{"code":"...","message":"..."}}`. Validation errors
return 422, missing resources return 404, rate limits return 429 with `Retry-After`, and
unexpected server errors return 500 without exposing internal exception details. Responses
include an `X-Request-ID` header. Chat requests are limited to 20 per minute per client by
default; configure this with `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS`.

## `GET /api/health`

Returns API status and corpus/retrieval/LLM status.

```sh
curl http://localhost:8000/api/health
```

## `POST /api/chat`

`question` must contain 1 to 500 characters, `history` may contain up to 6 user/assistant
turns, and `top_k` ranges from 1 to 8 (default 5). Whitespace is trimmed.

```sh
curl -X POST http://localhost:8000/api/chat \
  -H 'content-type: application/json' \
  -d '{"question":"How do I drop a class?","history":[],"top_k":5}'
```

Returns `request_id`, answer text, abstention status, citations and latency. Citation
objects contain `n`, `chunk_id`, `doc_id`, `title`, `section`, `snippet` (up to 240
characters) and `source_url`.

## `POST /api/chat/stream`

The request body is the same as `/api/chat`. The response is Server-Sent Events in this
order: `meta`, `retrieval`, `citations`, `token`, then `done`. The retrieval event
reports selected passage IDs, passage and document counts, elapsed milliseconds,
and status. Citations contain only sources used in the validated answer. Failures
after the stream starts are returned as an `error` event.

```sh
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H 'content-type: application/json' \
  -d '{"question":"How do I drop a class?"}'
```

## `POST /api/feedback`

Submit `rating` as `up` or `down`; `comment` is optional and limited to 1000 characters.
The referenced chat request must exist. Success is 204 with an empty body.

```sh
curl -i -X POST http://localhost:8000/api/feedback \
  -H 'content-type: application/json' \
  -d '{"request_id":"REQUEST_ID_FROM_CHAT","rating":"up","comment":"Helpful"}'
```

## `GET /api/documents`

Returns document IDs, titles, source URLs and chunk counts. It reads
`backend/data/documents.json` when present, otherwise derives the list from the chunk JSON.

```sh
curl http://localhost:8000/api/documents
```

## `GET /api/suggestions`

Returns six starter questions about dropping a class, tuition rebate, transcripts, residency,
transfer credit and the academic calendar.

```sh
curl http://localhost:8000/api/suggestions
```

## Configuration and packaging

Copy `.env.example` to `.env` to configure the provider, model, CORS origins, database and
logging. `docker compose up --build` starts the API with stubs; `docker compose --profile llm
up --build` also starts Ollama. The UI is not served by this API. A separately built UI may
be mounted as static files in a future change using `SERVE_UI_DIR`, which is unset by default.
Run `python -m backend.app.db --export` to print request and feedback analytics as CSV.
