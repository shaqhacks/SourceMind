from __future__ import annotations

from datetime import timedelta

from app.db.engine import get_session
from app.db.models import Job, utcnow
from app.jobs.worker import claim_next_job
from app.jobs.worker import run_due_jobs_once
from app.services import jobs_service


def _queued_job(job_type: str, created_offset_seconds: int, payload: dict | None = None) -> Job:
    return Job(
        type=job_type,
        status="queued",
        payload=payload or {},
        created_at=utcnow() + timedelta(seconds=created_offset_seconds),
    )


def test_worker_claims_each_queued_job_exactly_once(client):
    resp1 = client.post("/api/jobs", json={"type": "noop"})
    resp2 = client.post("/api/jobs", json={"type": "noop"})
    job_id_1 = resp1.json()["id"]
    job_id_2 = resp2.json()["id"]

    assert run_due_jobs_once() is True
    assert run_due_jobs_once() is True
    assert run_due_jobs_once() is False

    for job_id in (job_id_1, job_id_2):
        body = client.get(f"/api/jobs/{job_id}").json()
        assert body["status"] == "succeeded"
        assert body["attempts"] == 1


def test_cancel_queued_job_does_not_overwrite_concurrent_worker_claim(client, monkeypatch):
    job = client.post("/api/jobs", json={"type": "noop", "payload": {}}).json()
    interleaved = {"claimed": False}

    def _claim_before_cancel_write():
        if not interleaved["claimed"]:
            interleaved["claimed"] = True
            session = get_session()
            try:
                claimed = claim_next_job(session)
                assert claimed is not None
                assert claimed.id == job["id"]
                assert claimed.status == "running"
            finally:
                session.close()
        return utcnow()

    monkeypatch.setattr(jobs_service, "utcnow", _claim_before_cancel_write)

    cancelled = jobs_service.cancel_job(job["id"])

    assert cancelled.status == "running"
    assert cancelled.cancel_requested_at is not None
    session = get_session()
    try:
        stored = session.get(Job, job["id"])
        assert stored.status == "running"
        assert stored.cancel_requested_at is not None
        assert stored.lease_until is not None
    finally:
        session.close()


def test_worker_claims_generate_test_before_older_practice_jobs(client):
    session = get_session()
    try:
        older_practice = _queued_job(
            "generate_practice_assessment",
            -30,
            {"course_id": "course-1", "section_id": "practice-1", "run_id": "run-1"},
        )
        test_job = _queued_job(
            "generate_test",
            0,
            {"course_id": "course-1", "section_ids": ["content-1"], "chapter_label": "Chapter 1"},
        )
        session.add_all([older_practice, test_job])
        session.commit()

        claimed = claim_next_job(session)

        assert claimed is not None
        assert claimed.id == test_job.id
        assert claimed.type == "generate_test"
        assert claimed.status == "running"
    finally:
        session.close()


def test_worker_preserves_fifo_inside_same_priority_class(client):
    session = get_session()
    try:
        first = _queued_job("generate_practice_assessment", -30, {"section_id": "practice-1"})
        second = _queued_job("generate_practice_assessment", -10, {"section_id": "practice-2"})
        session.add_all([first, second])
        session.commit()

        claimed = claim_next_job(session)

        assert claimed is not None
        assert claimed.id == first.id
        assert claimed.type == "generate_practice_assessment"
    finally:
        session.close()
