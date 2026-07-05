from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Job
from app.jobs.worker import job_progress


def test_job_progress_updates_progress_and_extends_lease(client):
    session = get_session()
    try:
        job = Job(type="noop", status="running")
        session.add(job)
        session.commit()
        job_id = job.id
    finally:
        session.close()

    session = get_session()
    try:
        job_progress(session, job_id, stage="parsing", pct=42, message="halfway there")
    finally:
        session.close()

    session = get_session()
    try:
        job = session.get(Job, job_id)
        assert job.progress == {"stage": "parsing", "pct": 42, "message": "halfway there"}
        assert job.lease_until is not None
    finally:
        session.close()


def test_job_progress_is_noop_for_missing_job(client):
    session = get_session()
    try:
        # Must not raise even if the job vanished (e.g. deleted concurrently).
        job_progress(session, "does-not-exist", stage="x", pct=0, message="")
    finally:
        session.close()
