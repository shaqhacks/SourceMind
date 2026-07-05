"""Durable job worker.

claim_next_job() uses a single atomic UPDATE ... WHERE ... RETURNING
statement (SQLite 3.35+ supports RETURNING) so claiming a job is a single
read-modify-write executed by the database, not a read-then-write race in
Python. Never split this into a SELECT followed by an UPDATE.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import DateTime, bindparam, text
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.db.models import Job, ensure_utc, utcnow
from app.jobs.registry import (
    JOB_HANDLERS,
    MAX_ORPHAN_ATTEMPTS,
    ON_ORPHAN_HOOKS,
    default_on_orphan,
)

LEASE_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.5
ERROR_BACKOFF_SECONDS = 2.0

logger = logging.getLogger(__name__)

_CLAIM_SQL = text(
    """
    UPDATE jobs
    SET status = 'running',
        lease_until = :lease_until,
        attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued'
        ORDER BY created_at
        LIMIT 1
    )
    AND status = 'queued'
    RETURNING id
    """
).bindparams(bindparam("lease_until", type_=DateTime()))


def claim_next_job(session: Session) -> Job | None:
    lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
    result = session.execute(_CLAIM_SQL, {"lease_until": lease_until})
    row = result.first()
    session.commit()
    if row is None:
        return None
    return session.get(Job, row[0])


def job_progress(session: Session, job_id: str, stage: str, pct: float, message: str) -> None:
    """Heartbeat: handlers call this to report progress and renew their lease.

    Renewing the lease here (not just at claim time) means a legitimately
    slow-but-alive job doesn't get mistaken for orphaned mid-run.
    """
    job = session.get(Job, job_id)
    if job is None:
        return
    job.progress = {"stage": stage, "pct": pct, "message": message}
    job.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
    session.commit()


def execute_job(session: Session, job: Job) -> None:
    job_id = job.id
    handler = JOB_HANDLERS.get(job.type)
    if handler is None:
        job.status = "failed"
        job.error = f"unknown job type: {job.type}"
        session.commit()
        return

    try:
        result = handler(session, job)
    except Exception as exc:  # noqa: BLE001 - any handler failure must be persisted
        session.rollback()
        failed_job = session.get(Job, job_id)
        assert failed_job is not None
        failed_job.status = "failed"
        failed_job.error = str(exc)
        session.commit()
        return

    job.status = "succeeded"
    job.result = result
    job.error = None
    session.commit()


def run_due_jobs_once() -> bool:
    """Claim and execute a single due job. Returns True if a job was claimed."""
    session = get_session()
    try:
        job = claim_next_job(session)
        if job is None:
            return False
        execute_job(session, job)
        return True
    finally:
        session.close()


async def worker_loop() -> None:
    """Background task: claim+execute one job at a time, forever.

    Intended to run as an asyncio task started from the app lifespan and
    stopped via task.cancel() on shutdown.
    """
    while True:
        try:
            claimed = await asyncio.to_thread(run_due_jobs_once)
        except Exception:
            # A transient DB error (locked file, disk hiccup) must not kill the
            # loop — jobs would silently stop executing until restart.
            logger.exception("worker: job tick failed; backing off")
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)
            continue
        if not claimed:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def reconcile_interrupted_jobs() -> int:
    """Recover any 'running' job whose lease has expired (e.g. after a restart).

    Each job type can register an ON_ORPHAN_HOOKS entry to customize
    recovery; unregistered types fall back to default_on_orphan, which
    requeues under MAX_ORPHAN_ATTEMPTS and fails permanently after that.
    """
    session = get_session()
    try:
        now = utcnow()
        running_jobs = session.query(Job).filter(Job.status == "running").all()
        count = 0
        for job in running_jobs:
            lease = ensure_utc(job.lease_until)
            if lease is not None and lease < now:
                hook = ON_ORPHAN_HOOKS.get(job.type, default_on_orphan)
                hook(session, job)
                count += 1
        session.commit()
        return count
    finally:
        session.close()
