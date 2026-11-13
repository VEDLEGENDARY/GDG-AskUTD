"""Environment-backed application configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional for local development
    load_dotenv = None

ROOT = Path(__file__).resolve().parents[2]
if load_dotenv:
    load_dotenv(ROOT / ".env", override=False)


def _integer(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    llm_provider: str = "ollama"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    use_stubs: bool = False
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://localhost:5173")
    database_path: Path = ROOT / "backend" / "storage" / "askutd.db"
    log_level: str = "INFO"
    rate_limit: int = 20
    rate_window_seconds: int = 60
    serve_ui_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        provider = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
        if provider not in {"gemini", "ollama", "openai_compat", "extractive"}:
            raise ValueError("LLM_PROVIDER must be gemini, ollama, openai_compat, or extractive")
        origins = tuple(x.strip() for x in os.environ.get(
            "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if x.strip())
        ui_dir = os.environ.get("SERVE_UI_DIR", "").strip()
        return cls(
            llm_provider=provider,
            ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", ""),
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_model=os.environ.get("OPENAI_MODEL", ""),
            use_stubs=os.environ.get("USE_STUBS", "0").strip().lower() in {"1", "true", "yes"},
            cors_origins=origins,
            database_path=Path(os.environ.get("DATABASE_PATH", ROOT / "backend" / "storage" / "askutd.db")),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            rate_limit=_integer("RATE_LIMIT_REQUESTS", 20),
            rate_window_seconds=_integer("RATE_LIMIT_WINDOW_SECONDS", 60),
            serve_ui_dir=Path(ui_dir) if ui_dir else None,
        )
