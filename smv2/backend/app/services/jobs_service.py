"""Business logic for job creation/lookup. Routers only do existence checks
and delegate here — this module owns the actual DB work.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import Job
from app.jobs.registry import JOB_HANDLERS


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
