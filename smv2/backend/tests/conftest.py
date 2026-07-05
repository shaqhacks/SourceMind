from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.engine import dispose_engine
from app.db.init import init_db
from app.llm.provider import CompletionResult, Provider
from app.main import create_app

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SMV2_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SMV2_WORKER_ENABLED", "0")
    monkeypatch.setenv("SMV2_BACKUPS_ENABLED", "0")
    dispose_engine()
    init_db()

    with TestClient(create_app()) as test_client:
        yield test_client

    dispose_engine()


@pytest.fixture()
def ingest_course(client):
    """Factory fixture: create a course, upload a fixture PDF, start
    ingest, then drive the (test-disabled) worker synchronously.

    Returns a callable(fixture_name, title=...) -> (course_id, upload_resp,
    ingest_resp, claimed_bool).
    """
    from app.jobs.worker import run_due_jobs_once

    def _ingest(fixture_name: str, title: str = "Fixture Course"):
        course_resp = client.post("/api/courses", json={"title": title})
        course_id = course_resp.json()["id"]

        pdf_path = FIXTURES_DIR / fixture_name
        with pdf_path.open("rb") as f:
            upload_resp = client.post(
                f"/api/courses/{course_id}/assets",
                files={"file": (fixture_name, f, "application/pdf")},
            )

        ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
        claimed = run_due_jobs_once()
        return course_id, upload_resp, ingest_resp, claimed

    return _ingest


class StubProvider(Provider):
    """Test double — never touches the network. A real Provider subclass
    (not a duck-typed fake), so complete() still goes through the actual
    concurrency/retry/ledger wrapper; only _complete_impl is faked. Configure
    canned `responses`/`exceptions` (each a list, consumed in order via
    pop(0)) or leave both empty for a default always-succeeds stub.
    """

    def __init__(self, responses=None, exceptions=None):
        self.model_name = "stub-model"
        self.responses = list(responses) if responses else []
        self.exceptions = list(exceptions) if exceptions else []
        self.call_count = 0
        self.received_messages: list[list[dict]] = []
        self.received_systems: list[str | None] = []

    def _complete_impl(self, messages, *, max_tokens, system=None):
        self.call_count += 1
        self.received_messages.append(messages)
        self.received_systems.append(system)
        if self.exceptions:
            exc = self.exceptions.pop(0)
            if exc is not None:
                raise exc
        if self.responses:
            return self.responses.pop(0)
        return CompletionResult(
            text="stub lesson content", input_tokens=100, output_tokens=200, model=self.model_name
        )


@pytest.fixture()
def stub_provider(client, monkeypatch):
    """Monkeypatches get_provider() everywhere it's already been imported
    by name, so no test ever constructs a real Anthropic/Ollama client.
    """
    provider = StubProvider()
    monkeypatch.setattr("app.llm.provider.get_provider", lambda: provider)
    monkeypatch.setattr("app.pipeline.generation.get_provider", lambda: provider)
    return provider
