"""FastAPI application factory and HTTP error handling."""
from __future__ import annotations

import logging
import json
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, stubs
from .config import Settings
from .ratelimit import TokenBucketLimiter
from .routes import catalog, chat, feedback, health


class JsonLogFormatter(logging.Formatter):
    """Emit compact structured log records without exposing full chat prompts."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {"time": self.formatTime(record), "level": record.levelname,
                  "logger": record.name, "message": record.getMessage()}
        for key in ("request_id", "method", "path", "status_code", "latency_ms",
                    "abstained", "citation_count", "question_preview"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _load_engines(settings: Settings):
    if settings.use_stubs:
        return stubs, stubs
    try:
        from . import generation, retrieval
        return retrieval, generation
    except ImportError:
        logging.getLogger("askutd").warning("retrieval or generation module unavailable, using stubs")
        return stubs, stubs


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO),
                        handlers=[logging.StreamHandler()], force=True)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(JsonLogFormatter())
    application = FastAPI(title="GDG-AskUTD API", version="1.0.0")
    db.initialize(settings.database_path)
    retrieval, generation = _load_engines(settings)
    application.state.settings = settings
    application.state.db = db
    application.state.retrieval = retrieval
    application.state.generation = generation
    application.state.limiter = TokenBucketLimiter(settings.rate_limit, settings.rate_window_seconds)

    application.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                               allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"],
                               allow_headers=["Content-Type", "Authorization", "X-Request-ID"])

    @application.middleware("http")
    async def request_observability(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", "").strip()[:64] or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logging.getLogger("askutd").info("http request", extra={"request_id": request_id,
            "method": request.method, "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": int((time.perf_counter() - started) * 1000)})
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = first.get("msg", "Request validation failed")
        if location:
            message = f"{location}: {message}"
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error",
                                                                   "message": message}})

    @application.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            error = {"code": exc.detail.get("code", "http_error"),
                     "message": exc.detail.get("message", "Request failed.")}
        else:
            error = {"code": "not_found" if exc.status_code == 404 else "http_error",
                     "message": str(exc.detail)}
        headers = dict(exc.headers or {})
        return JSONResponse(status_code=exc.status_code, content={"error": error}, headers=headers)

    @application.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        logging.getLogger("askutd").exception("unhandled request error", extra={
            "request_id": getattr(request.state, "request_id", "unknown")})
        return JSONResponse(status_code=500, content={"error": {
            "code": "internal_error", "message": "The request could not be completed."}})

    application.include_router(health.router, prefix="/api", tags=["health"])
    application.include_router(chat.router, prefix="/api", tags=["chat"])
    application.include_router(feedback.router, prefix="/api", tags=["feedback"])
    application.include_router(catalog.router, prefix="/api", tags=["catalog"])
    # A future built UI can be mounted here when SERVE_UI_DIR is configured.
    return application


app = create_app()
