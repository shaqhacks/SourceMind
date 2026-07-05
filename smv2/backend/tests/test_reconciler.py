from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.engine import get_session
from app.db.models import Job
from app.jobs.worker import reconcile_interrupted_jobs


def test_reconcile_fails_orphaned_running_job(client):
    session = get_session()
    try:
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        running_job = Job(type="noop", status="running", lease_until=past, attempts=1)
        queued_job = Job(type="noop", status="queued")
        session.add_all([running_job, queued_job])
        session.commit()
        running_id = running_job.id
        queued_id = queued_job.id
    finally:
        session.close()

    reconcile_interrupted_jobs()

    session = get_session()
    try:
        refreshed_running = session.get(Job, running_id)
        refreshed_queued = session.get(Job, queued_id)
        assert refreshed_running.status == "failed"
        assert refreshed_running.error == "orphaned by restart"
        assert refreshed_queued.status == "queued"
    finally:
        session.close()
