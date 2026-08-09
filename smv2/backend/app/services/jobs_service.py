"""Business logic for job creation/lookup. Routers only do existence checks
and delegate here — this module owns the actual DB work.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from typing import Any, AsyncIterator

from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.db.models import Job, Section, utcnow
from app.jobs.registry import (
    JOB_HANDLERS,
    LLM_READINESS_REQUIRED_JOB_TYPES,
    RETRYABLE_JOB_TYPES,
)
from app.services import llm_readiness_service

SSE_POLL_INTERVAL_SECONDS = 0.3
SSE_MAX_SECONDS = 1860
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled"}
_CREDENTIAL_PAYLOAD_ERROR = "job payload contains credential-like data"
_CREDENTIAL_KEY_RE = re.compile(
    r"(api[_-]?key|apikey|token|secret|password|credential|authorization|ollama[_-]?base[_-]?url)",
    re.IGNORECASE,
)
_CREDENTIAL_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]+|bearer\s+[A-Za-z0-9._-]+)",
    re.IGNORECASE,
)


class JobNotRetryableError(ValueError):
    pass


def restore_cancelled_domain_state_in_session(session: Session, job: Job) -> None:
    if job.type != "generate_lesson":
        return
    section_id = (job.payload or {}).get("section_id")
    if not section_id:
        return
    section = session.get(Section, section_id)
    if section is None:
        return
    section.lesson_status = "ready" if section.lesson_md else "none"


def create_job_in_session(session: Session, job_type: str, payload: dict[str, Any] | None = None) -> Job:
    """Same as create_job, but adds the Job row to the CALLER's session
    instead of opening its own — for callers that need the job creation to
    land in the SAME commit as another state change (e.g. a lesson_status
    claim), so a crash between "claim committed" and "job created" can
    never wedge that state with no job that will ever clear it. The caller
    is responsible for committing.
    """
    if job_type not in JOB_HANDLERS:
        raise ValueError(f"unknown job type: {job_type}")
    if payload_contains_credential_like_data(payload):
        raise ValueError(_CREDENTIAL_PAYLOAD_ERROR)
    if job_type in LLM_READINESS_REQUIRED_JOB_TYPES:
        llm_readiness_service.assert_ready_for_generation()
    job = Job(type=job_type, status="queued", payload=payload)
    session.add(job)
    return job


def create_job(job_type: str, payload: dict[str, Any] | None = None) -> Job:
    session = get_session()
    try:
        job = create_job_in_session(session, job_type, payload)
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


def payload_contains_credential_like_data(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and _CREDENTIAL_KEY_RE.search(key):
                return True
            if payload_contains_credential_like_data(nested):
                return True
        return False
    if isinstance(value, list | tuple):
        return any(payload_contains_credential_like_data(item) for item in value)
    if isinstance(value, str):
        return bool(_CREDENTIAL_VALUE_RE.search(value))
    return False


def retry_job(job_id: str) -> Job:
    session = get_session()
    try:
        original = session.get(Job, job_id)
        if original is None:
            raise LookupError(f"job not found: {job_id}")
        if original.status == "cancelled":
            raise JobNotRetryableError("cancelled jobs cannot be retried")
        if original.type not in RETRYABLE_JOB_TYPES:
            raise JobNotRetryableError(f"job type is not retryable: {original.type}")
        if original.type in LLM_READINESS_REQUIRED_JOB_TYPES:
            llm_readiness_service.assert_ready_for_generation()
        payload = copy.deepcopy(original.payload)
        if payload_contains_credential_like_data(payload):
            raise JobNotRetryableError(_CREDENTIAL_PAYLOAD_ERROR)

        job = Job(
            type=original.type,
            status="queued",
            payload=payload,
        )
        session.add(job)
        session.commit()
        return job
    finally:
        session.close()


def cancel_job(job_id: str) -> Job:
    session = get_session()
    try:
        now = utcnow()

        queued_id = session.execute(
            sa_update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(
                status="cancelled",
                cancel_requested_at=func.coalesce(Job.cancel_requested_at, now),
                error=None,
                lease_until=None,
            )
            .returning(Job.id)
        ).scalar_one_or_none()
        if queued_id is not None:
            job = session.get(Job, queued_id)
            assert job is not None
            restore_cancelled_domain_state_in_session(session, job)
            session.commit()
            return job

        running_id = session.execute(
            sa_update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(cancel_requested_at=func.coalesce(Job.cancel_requested_at, now))
            .returning(Job.id)
        ).scalar_one_or_none()
        if running_id is not None:
            session.commit()
            job = session.get(Job, running_id)
            assert job is not None
            return job

        session.expire_all()
        job = session.get(Job, job_id)
        if job is None:
            raise LookupError(f"job not found: {job_id}")
        return job
    finally:
        session.close()


def is_cancel_requested(job_id: str) -> bool:
    session = get_session()
    try:
        job = session.get(Job, job_id)
        return job is not None and job.cancel_requested_at is not None
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
