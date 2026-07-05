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

    def __init__(self, responses=None, exceptions=None, embed_responses=None, embed_exception=None):
        self.model_name = "stub-model"
        self.responses = list(responses) if responses else []
        self.exceptions = list(exceptions) if exceptions else []
        self.call_count = 0
        self.received_messages: list[list[dict]] = []
        self.received_systems: list[str | None] = []
        # embed(): embed_responses, if given, is returned verbatim on every
        # call; embed_exception, if given, is raised every call (e.g. a
        # NotSupportedError stand-in). Otherwise a default fixed vector.
        self.embed_responses = embed_responses
        self.embed_exception = embed_exception
        self.embed_call_count = 0
        self.received_embed_texts: list[list[str]] = []

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

    def _embed_impl(self, texts):
        self.embed_call_count += 1
        self.received_embed_texts.append(list(texts))
        if self.embed_exception is not None:
            raise self.embed_exception
        if self.embed_responses is not None:
            return self.embed_responses
        return [[0.1, 0.2, 0.3] for _ in texts]


# Every module that does `from app.llm.provider import get_provider` binds
# its OWN name for it at import time — patching app.llm.provider.get_provider
# alone would not affect those already-bound references, so every call site
# needs its own patch target here.
_GET_PROVIDER_PATCH_TARGETS = (
    "app.llm.provider.get_provider",
    "app.pipeline.generation.get_provider",
    "app.pipeline.cards_generation.get_provider",
    "app.pipeline.quiz_generation.get_provider",
    "app.pipeline.embedding.get_provider",
    "app.pipeline.retrieval.get_provider",
    "app.services.chat_service.get_provider",
)


@pytest.fixture()
def stub_provider(client, monkeypatch):
    """Monkeypatches get_provider() everywhere it's already been imported
    by name, so no test ever constructs a real Anthropic/Ollama client.
    """
    provider = StubProvider()
    for target in _GET_PROVIDER_PATCH_TARGETS:
        monkeypatch.setattr(target, lambda: provider)
    return provider
