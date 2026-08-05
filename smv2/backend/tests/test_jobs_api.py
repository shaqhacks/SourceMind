from __future__ import annotations

import copy

from app.db.engine import get_session
from app.db.models import Job
from app.jobs.error_envelope import encode_job_error


def _seed_job(
    job_type: str,
    payload: dict | None = None,
    *,
    status: str = "failed",
    result: dict | None = None,
    progress: dict | None = None,
    error: str | None = "provider failed",
    error_detail: dict | None = None,
    attempts: int = 1,
) -> str:
    stored_error = encode_job_error(error or "", error_detail) if error_detail else error
    session = get_session()
    try:
        job = Job(
            type=job_type,
            status=status,
            payload=copy.deepcopy(payload),
            result=copy.deepcopy(result),
            progress=copy.deepcopy(progress),
            error=stored_error,
            attempts=attempts,
        )
        session.add(job)
        session.commit()
        return job.id
    finally:
        session.close()


def test_retry_creates_fresh_queued_job_for_retryable_type_without_mutating_original(
    client, monkeypatch
):
    payload = {"section_id": "section-1", "course_id": "course-1"}
    original_id = _seed_job(
        "generate_lesson",
        payload,
        result={"partial": True},
        progress={"stage": "failed", "pct": 80},
        error="provider failed",
        attempts=2,
    )
    before = client.get(f"/api/jobs/{original_id}").json()
    monkeypatch.setattr(
        "app.services.llm_readiness_service.assert_ready_for_generation",
        lambda: None,
    )

    resp = client.post(f"/api/jobs/{original_id}/retry")

    assert resp.status_code == 202
    retried = resp.json()
    assert retried["id"] != original_id
    assert retried["type"] == "generate_lesson"
    assert retried["retryable"] is True
    assert retried["status"] == "queued"
    assert retried["payload"] == payload
    assert retried["result"] is None
    assert retried["progress"] is None
    assert retried["error"] is None
    assert retried["attempts"] == 0
    assert client.get(f"/api/jobs/{original_id}").json() == before


def test_job_reads_expose_structured_error_detail(client):
    error_detail = {
        "code": "llm_readiness_unavailable",
        "failure_category": "missing_credentials",
        "message": "LLM provider is not ready",
        "remediation": "Add an Anthropic key.",
    }
    original_id = _seed_job(
        "generate_lesson",
        {"section_id": "section-1", "course_id": "course-1"},
        error="Display-only failure",
        error_detail=error_detail,
    )

    single = client.get(f"/api/jobs/{original_id}").json()
    listed = {job["id"]: job for job in client.get("/api/jobs").json()}[original_id]

    assert single["error"] == "Display-only failure"
    assert single["error_detail"] == error_detail
    assert listed["error_detail"] == error_detail


def test_retry_rejects_non_retryable_type_and_preserves_original_job(client):
    original_id = _seed_job(
        "noop",
        {"trace_id": "abc"},
        status="failed",
        result={"ok": False},
        progress={"stage": "failed"},
        error="noop failed",
        attempts=3,
    )
    before = client.get(f"/api/jobs/{original_id}").json()

    resp = client.post(f"/api/jobs/{original_id}/retry")

    assert resp.status_code == 409
    assert client.get(f"/api/jobs/{original_id}").json() == before
    assert before["retryable"] is False
    jobs = client.get("/api/jobs").json()
    assert [job["id"] for job in jobs] == [original_id]


def test_retry_preserves_nested_payload_in_raw_job_reads(client, monkeypatch):
    payload = {
        "course_id": "course-1",
        "section_ids": ["section-1", "section-2"],
        "options": {"chapter_label": "Unit 2", "difficulty": "mixed"},
    }
    original_id = _seed_job("generate_test", payload)
    monkeypatch.setattr(
        "app.services.llm_readiness_service.assert_ready_for_generation",
        lambda: None,
    )

    resp = client.post(f"/api/jobs/{original_id}/retry")

    assert resp.status_code == 202
    retry_id = resp.json()["id"]
    assert client.get(f"/api/jobs/{retry_id}").json()["payload"] == payload
    jobs = client.get("/api/jobs").json()
    jobs_by_id = {job["id"]: job for job in jobs}
    assert jobs_by_id[original_id]["payload"] == payload
    assert jobs_by_id[retry_id]["payload"] == payload


def test_retryable_ai_job_rejects_when_llm_readiness_is_unavailable(client):
    original_id = _seed_job("generate_lesson", {"section_id": "section-1"})
    before = client.get(f"/api/jobs/{original_id}").json()

    resp = client.post(f"/api/jobs/{original_id}/retry")

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["failure_category"] == "missing_credentials"
    assert "ANTHROPIC_API_KEY" in body["detail"]["remediation"]
    assert client.get(f"/api/jobs/{original_id}").json() == before
    jobs = client.get("/api/jobs").json()
    assert [job["id"] for job in jobs] == [original_id]


def test_retry_missing_job_is_404(client):
    resp = client.post("/api/jobs/does-not-exist/retry")

    assert resp.status_code == 404
