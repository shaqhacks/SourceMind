from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.engine import get_session
from app.db.models import Job
from app.jobs import registry
from app.jobs.worker import MAX_ORPHAN_ATTEMPTS, reconcile_interrupted_jobs


def _insert_running_job(attempts: int, job_type: str = "noop") -> str:
    session = get_session()
    try:
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        job = Job(type=job_type, status="running", lease_until=past, attempts=attempts)
        session.add(job)
        session.commit()
        return job.id
    finally:
        session.close()


def _insert_cancel_requested_running_job(attempts: int, job_type: str = "noop") -> str:
    session = get_session()
    try:
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        job = Job(
            type=job_type,
            status="running",
            lease_until=past,
            cancel_requested_at=datetime.now(timezone.utc),
            attempts=attempts,
            progress={"stage": "generating"},
            error="stale error",
        )
        session.add(job)
        session.commit()
        return job.id
    finally:
        session.close()


def test_orphaned_job_under_attempt_limit_is_requeued(client):
    job_id = _insert_running_job(attempts=1)

    reconcile_interrupted_jobs()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.status == "queued"
        assert job.lease_until is None
        assert job.progress is None
    finally:
        session.close()


def test_cancel_requested_orphaned_job_is_cancelled_instead_of_requeued(client):
    job_id = _insert_cancel_requested_running_job(attempts=1)

    reconcile_interrupted_jobs()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.status == "cancelled"
        assert job.lease_until is None
        assert job.error is None
        assert job.progress is None
    finally:
        session.close()


def test_orphaned_job_at_attempt_limit_fails_permanently(client):
    job_id = _insert_running_job(attempts=MAX_ORPHAN_ATTEMPTS)

    reconcile_interrupted_jobs()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.status == "failed"
        assert job.error == "orphaned by restart"
    finally:
        session.close()


def test_queued_job_is_left_untouched_by_reconciler(client):
    session = get_session()
    try:
        job = Job(type="noop", status="queued")
        session.add(job)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    reconcile_interrupted_jobs()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.status == "queued"
    finally:
        session.close()


def test_registered_on_orphan_hook_is_invoked(client, monkeypatch):
    calls: list[str] = []

    def _custom_hook(session, job) -> None:
        calls.append(job.id)
        job.status = "failed"
        job.error = "custom-hook-handled"

    monkeypatch.setitem(registry.ON_ORPHAN_HOOKS, "custom-orphan-type", _custom_hook)
    monkeypatch.setitem(
        registry.JOB_HANDLERS, "custom-orphan-type", lambda session, job: {"ok": True}
    )

    job_id = _insert_running_job(attempts=1, job_type="custom-orphan-type")

    reconcile_interrupted_jobs()

    assert calls == [job_id]
    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.status == "failed"
        assert job.error == "custom-hook-handled"
    finally:
        session.close()
