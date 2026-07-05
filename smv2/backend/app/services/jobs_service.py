"""Business logic for job creation/lookup. Routers only do existence checks
and delegate here — this module owns the actual DB work.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from app.db.engine import get_session
from app.db.models import Job
from app.jobs.registry import JOB_HANDLERS

SSE_POLL_INTERVAL_SECONDS = 0.3
SSE_MAX_SECONDS = 600
TERMINAL_JOB_STATUSES = {"succeeded", "failed"}


def create_job(job_type: str, payload: dict[str, Any] | None = None) -> Job:
    if job_type not in JOB_HANDLERS:
        raise ValueError(f"unknown job type: {job_type}")

    session = get_session()
    try:
        job = Job(type=job_type, status="queued", payload=payload)
        session.add(job)
        session.commit()
        return job
    finally:
        session.close()


def get_job(job_id: str) -> Job | None:
    session = get_session()
    try:
        return session.get(Job, job_id)
    finally:
        session.close()


def list_jobs(limit: int = 50) -> list[Job]:
    session = get_session()
    try:
        return (
            session.query(Job)
            .order_by(Job.created_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        session.close()


async def stream_job_events(job_id: str) -> AsyncIterator[str]:
    """Server-sent events for one job's status/progress.

    Polls every SSE_POLL_INTERVAL_SECONDS, emits only on change, and always
    emits the terminal snapshot before closing. SSE_MAX_SECONDS is a hard
    cap so a client that never disconnects can't hold the stream open
    forever against a job that will never reach a terminal status.
    """
    started = time.monotonic()
    last_payload: str | None = None
    while True:
        job = await asyncio.to_thread(get_job, job_id)
        if job is None:
            return

        snapshot = {"id": job.id, "status": job.status, "progress": job.progress}
        payload = json.dumps(snapshot)
        if payload != last_payload:
            yield f"event: update\ndata: {payload}\n\n"
            last_payload = payload

        if job.status in TERMINAL_JOB_STATUSES:
            return
        if time.monotonic() - started > SSE_MAX_SECONDS:
            return

        await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)
