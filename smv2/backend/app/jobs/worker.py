"""Durable job worker.

claim_next_job() uses a single atomic UPDATE ... WHERE ... RETURNING
statement (SQLite 3.35+ supports RETURNING) so claiming a job is a single
read-modify-write executed by the database, not a read-then-write race in
Python. Never split this into a SELECT followed by an UPDATE.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

from sqlalchemy import DateTime, bindparam, text
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.db.models import Job, ensure_utc, utcnow
from app.jobs.error_envelope import encode_job_error
from app.jobs.registry import (
    JOB_HANDLERS,
    ON_ORPHAN_HOOKS,
    default_on_orphan,
)
from app.llm.completion_control import ProviderCancelledError
from app.llm.structured_output import InvalidModelOutputError
from app.services import jobs_service
from app.services.llm_readiness_service import LlmReadinessUnavailableError

LEASE_SECONDS = 60
POLL_INTERVAL_SECONDS = 0.5
ERROR_BACKOFF_SECONDS = 2.0
# reconcile_interrupted_jobs() used to run only once, at app startup. A fast
# restart within a job's lease window meant the claim SQL (status='queued'
# only) could never see that lease-expired 'running' row again — it would
# sit wedged forever until someone restarted the process a second time.
# Running the reconciler periodically from the live loop, not just at
# startup, means a job can also recover without any restart at all.
RECONCILE_INTERVAL_SECONDS = 30.0

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


def job_progress(
    session: Session,
    job_id: str,
    stage: str,
    pct: float | None,
    message: str,
    *,
    elapsed_seconds: int | None = None,
    last_activity_seconds: int | None = None,
) -> None:
    """Heartbeat: handlers call this to report progress and renew their lease.

    Renewing the lease here (not just at claim time) means a legitimately
    slow-but-alive job doesn't get mistaken for orphaned mid-run.
    """
    job = session.get(Job, job_id)
    if job is None:
        return
    progress = {"stage": stage, "pct": pct, "message": message}
    if elapsed_seconds is not None:
        progress["elapsed_seconds"] = elapsed_seconds
    if last_activity_seconds is not None:
        progress["last_activity_seconds"] = last_activity_seconds
    job.progress = progress
    job.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
    session.commit()


def execute_job(session: Session, job: Job) -> None:
    job_id = job.id
    handler = JOB_HANDLERS.get(job.type)
    if handler is None:
        job.status = "failed"
        message = f"unknown job type: {job.type}"
        job.error = encode_job_error(message, {"code": "unknown_job_type", "message": message})
        session.commit()
        return

    try:
        result = handler(session, job)
    except ProviderCancelledError:
        session.rollback()
        cancelled_job = session.get(Job, job_id)
        assert cancelled_job is not None
        cancelled_job.status = "cancelled"
        cancelled_job.result = None
        cancelled_job.progress = None
        cancelled_job.error = None
        cancelled_job.lease_until = None
        jobs_service.restore_cancelled_domain_state_in_session(session, cancelled_job)
        session.commit()
        return
    except LlmReadinessUnavailableError as exc:
        session.rollback()
        failed_job = session.get(Job, job_id)
        assert failed_job is not None
        failed_job.status = "failed"
        message = exc.detail.get("message", "LLM provider is not ready")
        failed_job.error = encode_job_error(
            message,
            {"code": "llm_readiness_unavailable", **exc.detail},
        )
        session.commit()
        return
    except InvalidModelOutputError as exc:
        session.rollback()
        failed_job = session.get(Job, job_id)
        assert failed_job is not None
        failed_job.status = "failed"
        message = exc.error_detail["message"]
        failed_job.error = encode_job_error(message, exc.error_detail)
        session.commit()
        return
    except Exception as exc:  # noqa: BLE001 - any handler failure must be persisted
        session.rollback()
        failed_job = session.get(Job, job_id)
        assert failed_job is not None
        failed_job.status = "failed"
        message = str(exc)
        failed_job.error = encode_job_error(message, {"code": "job_failed", "message": message})
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
    """Background task: claim+execute one job at a time, forever, and
    periodically re-run reconcile_interrupted_jobs() so a job whose lease
    expires while this process is still alive (e.g. it restarted quickly
    within the lease window) recovers without needing a second restart —
    the one-shot startup reconcile alone can't catch that case.

    Intended to run as an asyncio task started from the app lifespan and
    stopped via task.cancel() on shutdown.
    """
    last_reconcile = time.monotonic()
    while True:
        try:
            claimed = await asyncio.to_thread(run_due_jobs_once)
        except Exception:
            # A transient DB error (locked file, disk hiccup) must not kill the
            # loop — jobs would silently stop executing until restart.
            logger.exception("worker: job tick failed; backing off")
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)
            continue

        now = time.monotonic()
        if now - last_reconcile >= RECONCILE_INTERVAL_SECONDS:
            try:
                await asyncio.to_thread(reconcile_interrupted_jobs)
            except Exception:
                logger.exception("worker: periodic reconcile failed; backing off")
            last_reconcile = now

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
                if job.cancel_requested_at is not None:
                    job.status = "cancelled"
                    job.progress = None
                    job.error = None
                    job.lease_until = None
                    jobs_service.restore_cancelled_domain_state_in_session(session, job)
                    count += 1
                    continue
                hook = ON_ORPHAN_HOOKS.get(job.type, default_on_orphan)
                hook(session, job)
                count += 1
        session.commit()
        return count
    finally:
        session.close()
