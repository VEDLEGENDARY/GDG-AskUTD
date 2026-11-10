"""Acceptance tests for the public HTTP API, using only stubs and fakes."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.ratelimit import TokenBucketLimiter
from backend.app.types import Answer, Citation, Passage, RetrievalResult


class ApiTests(unittest.TestCase):
    def setUp(self):
        storage = Path(__file__).resolve().parents[1] / "storage"
        storage.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=storage)
        self.app = create_app(Settings(use_stubs=True, log_level="CRITICAL",
                                       database_path=Path(self.temp.name) / "test.db"))
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_health_reports_stub(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["retriever"], "stub")
        self.assertTrue(response.headers["x-request-id"])

    def test_chat_success_and_feedback(self):
        response = self.client.post("/api/chat", json={"question": "How do I drop a class?"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["request_id"] and body["citations"])
        self.assertEqual(body["citations"][0]["n"], 1)
        self.assertEqual(response.headers["x-request-id"], body["request_id"])
        feedback = self.client.post("/api/feedback", json={
            "request_id": body["request_id"], "rating": "up"})
        self.assertEqual(feedback.status_code, 204)
        self.assertEqual(feedback.content, b"")

    def test_abstain_skips_generation(self):
        with patch.object(self.app.state.generation, "generate_answer",
                          side_effect=AssertionError("generation should be skipped")):
            response = self.client.post("/api/chat", json={"question": "weather today"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["abstained"])
        self.assertEqual(response.json()["citations"], [])

    def test_validation_errors_use_standard_shape(self):
        cases = ({"question": "   "}, {"question": "x" * 501},
                 {"question": "hi", "history": [{"role": "system", "content": "x"}]},
                 {"question": "hi", "history": [{"role": "user", "content": "x"}] * 7})
        for body in cases:
            with self.subTest(body=body):
                response = self.client.post("/api/chat", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(set(response.json()), {"error"})
                self.assertEqual(set(response.json()["error"]), {"code", "message"})

    def test_stream_event_order_and_termination(self):
        response = self.client.post("/api/chat/stream", json={"question": "How do I drop a class?"})
        events = [line[7:] for line in response.text.splitlines() if line.startswith("event: ")]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[:2], ["meta", "citations"])
        self.assertIn("token", events)
        self.assertEqual(events[-1], "done")
        self.assertEqual(response.headers["cache-control"], "no-cache")
        self.assertEqual(response.headers["x-accel-buffering"], "no")

    def test_feedback_unknown_request_is_404(self):
        response = self.client.post("/api/feedback", json={
            "request_id": "missing", "rating": "down"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "request_not_found")

    def test_rate_limit_returns_429_and_retry_after(self):
        self.app.state.limiter = TokenBucketLimiter(1, 60)
        self.assertEqual(self.client.post("/api/chat", json={"question": "first"}).status_code, 200)
        response = self.client.post("/api/chat", json={"question": "second"})
        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.headers.get("retry-after"))
        self.assertEqual(response.json()["error"]["code"], "rate_limit_exceeded")

    def test_documents_and_suggestions(self):
        documents = self.client.get("/api/documents").json()
        suggestions = self.client.get("/api/suggestions").json()
        self.assertTrue(documents)
        self.assertTrue({"doc_id", "title", "source_url", "chunks"} <= documents[0].keys())
        self.assertEqual(len(suggestions), 6)
        self.assertTrue(any("drop a class" in q.lower() for q in suggestions))

    def test_cors_preflight(self):
        response = self.client.options("/api/chat", headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:3000")

    def test_not_found_and_internal_errors_are_shaped(self):
        response = self.client.get("/api/nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(set(response.json()), {"error"})
        with patch.object(self.app.state.retrieval, "retrieve",
                          side_effect=RuntimeError("private detail")):
            with TestClient(self.app, raise_server_exceptions=False) as faulty_client:
                failed = faulty_client.post("/api/chat", json={"question": "cause failure"})
        self.assertEqual(failed.status_code, 500)
        self.assertEqual(failed.json(), {"error": {"code": "internal_error",
                                                     "message": "The request could not be completed."}})

    def test_chat_wires_retrieval_generation_and_history(self):
        calls = {}
        fake_retrieval = type("FakeRetrieval", (), {
            "retrieve": staticmethod(lambda q, k, h: (calls.update(query=q, top_k=k, history=h) or
                RetrievalResult(passages=[Passage("c", "d", "text", "Title", "Section", .9)]))),
            "corpus_stats": staticmethod(lambda: {"documents": 1, "chunks": 1, "retriever": "fake"})})
        citation = Citation(1, "c", "d", "Title", "Section", "text", None)
        fake_generation = type("FakeGeneration", (), {
            "ABSTAIN_TEXT": "unknown", "llm_status": staticmethod(lambda: "fake"),
            "generate_answer": staticmethod(lambda q, p, h: Answer("grounded [1]", [citation]))})
        settings = Settings(use_stubs=True, log_level="CRITICAL",
                            database_path=Path(self.temp.name) / "fake.db")
        with patch("backend.app.main._load_engines", return_value=(fake_retrieval, fake_generation)):
            fake_app = create_app(settings)
        with TestClient(fake_app) as client:
            response = client.post("/api/chat", json={"question": "question", "top_k": 2,
                "history": [{"role": "user", "content": "previous"}]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls["query"], "question")
        self.assertEqual(calls["top_k"], 2)
        self.assertEqual(calls["history"][0].role, "user")

    def test_stream_failure_becomes_error_event(self):
        with patch.object(self.app.state.retrieval, "retrieve",
                          side_effect=RuntimeError("private")):
            response = self.client.post("/api/chat/stream", json={"question": "failure"})
        events = [line[7:] for line in response.text.splitlines() if line.startswith("event: ")]
        payloads = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(events, ["meta", "error"])
        self.assertEqual(payloads[-1]["code"], "internal_error")

    def test_non_stub_app_loads_real_engines(self):
        from backend.app import generation, retrieval
        from backend.app.main import _load_engines
        self.assertEqual(_load_engines(Settings(use_stubs=False)), (retrieval, generation))
        from backend.app import stubs
        self.assertEqual(_load_engines(Settings(use_stubs=True)), (stubs, stubs))


if __name__ == "__main__":
    unittest.main()
