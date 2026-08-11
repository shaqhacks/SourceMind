from __future__ import annotations

import copy
from datetime import timedelta

from conftest import _first_section_id

from app.db.engine import get_session
from app.db.models import Job, utcnow
from app.jobs import registry
from app.jobs.error_envelope import encode_job_error
from app.jobs.registry import LLM_READINESS_REQUIRED_JOB_TYPES
from app.jobs.worker import run_due_jobs_once
from app.llm.completion_control import ProviderCancelledError
from app.security.local_settings import csrf_token
from app.services import jobs_service


def _mutation_headers(token: str | None = None, **overrides: str) -> dict[str, str]:
    headers = {
        "Origin": "http://localhost:3000",
        "Host": "localhost:8000",
    }
    if token is not None:
        headers["X-CSRF-Token"] = token
    headers.update(overrides)
    return headers


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


def test_retry_rejects_historical_payload_with_credential_like_data_without_persisting(
    client, monkeypatch
):
    original_id = _seed_job(
        "generate_lesson",
        {
            "section_id": "section-1",
            "metadata": {"nested": [{"apiKey": "sk-ant-legacy-secret"}]},
        },
    )
    before = client.get(f"/api/jobs/{original_id}").json()
    monkeypatch.setattr(
        "app.services.llm_readiness_service.assert_ready_for_generation",
        lambda: None,
    )

    resp = client.post(f"/api/jobs/{original_id}/retry")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "job payload contains credential-like data"
    assert "sk-ant-legacy-secret" not in resp.text
    assert client.get(f"/api/jobs/{original_id}").json() == before
    jobs = client.get("/api/jobs").json()
    assert [job["id"] for job in jobs] == [original_id]


def test_retry_missing_job_is_404(client):
    resp = client.post("/api/jobs/does-not-exist/retry")

    assert resp.status_code == 404


def test_create_job_rejects_llm_required_type_when_readiness_unavailable_without_persisting(
    client,
):
    resp = client.post(
        "/api/jobs",
        json={"type": "generate_lesson", "payload": {"section_id": "section-1"}},
    )

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["failure_category"] == "missing_credentials"
    assert client.get("/api/jobs").json() == []


def test_create_job_rejects_recursive_credential_like_payload_without_persisting(
    client, monkeypatch
):
    monkeypatch.setattr(
        "app.services.llm_readiness_service.assert_ready_for_generation",
        lambda: None,
    )

    for job_type in sorted(LLM_READINESS_REQUIRED_JOB_TYPES):
        resp = client.post(
            "/api/jobs",
            json={
                "type": job_type,
                "payload": {
                    "course_id": "course-1",
                    "sections": [
                        {"metadata": {"apiKey": "sk-ant-nested-secret"}},
                        {"notes": ["safe", {"token": "bearer-secret"}]},
                    ],
                },
            },
        )

        assert resp.status_code == 422
        assert resp.json()["detail"] == "job payload contains credential-like data"

    assert client.get("/api/jobs").json() == []


def test_create_noop_rejects_recursive_credential_like_payload_without_persisting(client):
    resp = client.post(
        "/api/jobs",
        json={
            "type": "noop",
            "payload": {
                "metadata": [
                    {"label": "safe"},
                    {"headers": {"authorization": "Bearer sk-ant-noop-secret"}},
                ],
            },
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "job payload contains credential-like data"
    assert "sk-ant-noop-secret" not in resp.text
    assert client.get("/api/jobs").json() == []


def test_create_job_preserves_safe_noop_payload(client):
    payload = {"metadata": {"label": "api key concepts", "items": ["tokenization"]}}

    resp = client.post("/api/jobs", json={"type": "noop", "payload": payload})

    assert resp.status_code == 202
    job = resp.json()
    assert job["type"] == "noop"
    assert job["payload"] == payload


def test_cancel_queued_job_is_immediately_terminal(client):
    job = client.post("/api/jobs", json={"type": "noop", "payload": {}}).json()

    response = client.post(f"/api/jobs/{job['id']}/cancel", headers=_mutation_headers(csrf_token()))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancel_requested_at"] is not None
    assert body["retryable"] is False
    assert run_due_jobs_once() is False


def test_cancel_running_job_sets_cooperative_request(client):
    session = get_session()
    try:
        running = Job(
            type="noop",
            status="running",
            lease_until=utcnow() + timedelta(minutes=5),
            attempts=1,
        )
        session.add(running)
        session.commit()
        job_id = running.id
    finally:
        session.close()

    response = client.post(f"/api/jobs/{job_id}/cancel", headers=_mutation_headers(csrf_token()))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["cancel_requested_at"] is not None
    assert jobs_service.is_cancel_requested(job_id) is True


def test_cancel_terminal_job_is_idempotent_and_unchanged(client):
    job_id = _seed_job(
        "noop",
        status="succeeded",
        result={"ok": True},
        progress={"stage": "done"},
        error=None,
        attempts=1,
    )
    before = client.get(f"/api/jobs/{job_id}").json()

    response = client.post(f"/api/jobs/{job_id}/cancel", headers=_mutation_headers(csrf_token()))

    assert response.status_code == 200
    assert response.json() == before


def test_cancel_missing_job_is_404_without_internal_details(client):
    response = client.post("/api/jobs/does-not-exist/cancel", headers=_mutation_headers(csrf_token()))

    assert response.status_code == 404
    assert response.json() == {"detail": "job not found"}


def test_cancel_requires_csrf_token_without_mutating_job(client):
    job = client.post("/api/jobs", json={"type": "noop", "payload": {}}).json()
    before = client.get(f"/api/jobs/{job['id']}").json()

    response = client.post(f"/api/jobs/{job['id']}/cancel", headers=_mutation_headers())

    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    assert client.get(f"/api/jobs/{job['id']}").json() == before


def test_cancel_rejects_invalid_csrf_token_without_mutating_job(client):
    job = client.post("/api/jobs", json={"type": "noop", "payload": {}}).json()
    before = client.get(f"/api/jobs/{job['id']}").json()

    response = client.post(f"/api/jobs/{job['id']}/cancel", headers=_mutation_headers("not-valid"))

    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    assert client.get(f"/api/jobs/{job['id']}").json() == before


def test_cancel_rejects_untrusted_origin_without_mutating_job(client, monkeypatch):
    monkeypatch.setenv("SMV2_CORS_ORIGINS", "http://testserver")
    job = client.post("/api/jobs", json={"type": "noop", "payload": {}}).json()
    before = client.get(f"/api/jobs/{job['id']}").json()

    response = client.post(
        f"/api/jobs/{job['id']}/cancel",
        headers=_mutation_headers(csrf_token(), Origin="https://evil.example"),
    )

    assert response.status_code == 403
    assert "origin" in response.json()["detail"].lower()
    assert client.get(f"/api/jobs/{job['id']}").json() == before


def test_retry_rejects_cancelled_job_without_creating_replacement(client, monkeypatch):
    original_id = _seed_job(
        "generate_lesson",
        {"section_id": "section-1"},
        status="cancelled",
        error=None,
        attempts=1,
    )
    monkeypatch.setattr(
        "app.services.llm_readiness_service.assert_ready_for_generation",
        lambda: None,
    )

    response = client.post(f"/api/jobs/{original_id}/retry")

    assert response.status_code == 409
    assert response.json()["detail"] == "cancelled jobs cannot be retried"
    jobs = client.get("/api/jobs").json()
    assert [job["id"] for job in jobs] == [original_id]
    assert jobs[0]["retryable"] is False


def test_cancelled_queued_lesson_job_allows_explicit_generation_to_create_new_job(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    first = client.post(f"/api/sections/{section_id}/lesson")
    assert first.status_code == 202
    first_job_id = first.json()["job_id"]

    cancel_response = client.post(
        f"/api/jobs/{first_job_id}/cancel",
        headers=_mutation_headers(csrf_token()),
    )
    assert cancel_response.status_code == 200

    second = client.post(f"/api/sections/{section_id}/lesson")

    assert second.status_code == 202
    assert second.json()["job_id"] != first_job_id
    jobs = client.get("/api/jobs").json()
    statuses_by_id = {job["id"]: job["status"] for job in jobs if job["type"] == "generate_lesson"}
    assert statuses_by_id[first_job_id] == "cancelled"
    assert statuses_by_id[second.json()["job_id"]] == "queued"


def test_worker_marks_provider_cancellation_terminal_and_rolls_back_partial_state(
    client, monkeypatch
):
    def _cancel_after_partial_mutation(session, job):
        job.result = {"partial": True}
        job.progress = {"stage": "generating", "pct": 50}
        job.error = "intermediate error"
        raise ProviderCancelledError()

    monkeypatch.setitem(registry.JOB_HANDLERS, "cancel_after_partial", _cancel_after_partial_mutation)
    job = client.post("/api/jobs", json={"type": "cancel_after_partial"}).json()

    assert run_due_jobs_once() is True

    body = client.get(f"/api/jobs/{job['id']}").json()
    assert body["status"] == "cancelled"
    assert body["result"] is None
    assert body["progress"] is None
    assert body["error"] is None
    assert body["error_detail"] is None
    assert body["retryable"] is False
    session = get_session()
    try:
        stored = session.get(Job, job["id"])
        assert stored.lease_until is None
    finally:
        session.close()
