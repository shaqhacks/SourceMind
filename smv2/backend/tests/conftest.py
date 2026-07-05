from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.engine import dispose_engine
from app.db.init import init_db
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
