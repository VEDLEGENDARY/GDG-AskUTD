"""Pytest fixtures for API tests. Tests do not load models or call external services."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.main import create_app


@pytest.fixture
def app():
    storage = Path(__file__).resolve().parents[1] / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=storage) as directory:
        settings = Settings(use_stubs=True, database_path=Path(directory) / "test.db")
        yield create_app(settings)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as test_client:
        yield test_client
