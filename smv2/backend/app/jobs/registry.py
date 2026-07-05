"""Job type -> handler registry, plus per-type orphan-recovery hooks.

Each handler takes (session, job) and returns a JSON-serializable result dict.
Handlers must not commit/rollback the session themselves — the worker owns
the transaction boundary so it can persist success/failure atomically.

ON_ORPHAN_HOOKS lets a job type override how the reconciler recovers a
lease-expired 'running' job; anything not registered here falls back to
default_on_orphan in the reconciler.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import Course, Job, Section
from app.pipeline.generation import run_lesson_generation
from app.pipeline.ingest import run_ingest
from app.services.backup_service import run_backup

JobHandler = Callable[[Session, Job], dict[str, Any]]
OrphanHook = Callable[[Session, Job], None]

MAX_ORPHAN_ATTEMPTS = 3


def _noop_handler(session: Session, job: Job) -> dict[str, Any]:
    return {"ok": True}


def _backup_handler(session: Session, job: Job) -> dict[str, Any]:
    path = run_backup()
    return {"path": str(path)}


def _ingest_handler(session: Session, job: Job) -> dict[str, Any]:
    course_id = (job.payload or {}).get("course_id")
    if not course_id:
        raise ValueError("ingest job payload missing course_id")
    run_ingest(session, job, course_id)
    return {"course_id": course_id}


def _generate_lesson_handler(session: Session, job: Job) -> dict[str, Any]:
    section_id = (job.payload or {}).get("section_id")
    if not section_id:
        raise ValueError("generate_lesson job payload missing section_id")
    extra = run_lesson_generation(session, job, section_id)
    return {"section_id": section_id, **extra}


JOB_HANDLERS: dict[str, JobHandler] = {
    "noop": _noop_handler,
    "backup": _backup_handler,
    "ingest": _ingest_handler,
    "generate_lesson": _generate_lesson_handler,
}


def default_on_orphan(session: Session, job: Job) -> None:
    """Requeue a lease-expired job up to MAX_ORPHAN_ATTEMPTS, then fail it for good."""
    if job.attempts < MAX_ORPHAN_ATTEMPTS:
        job.status = "queued"
        job.lease_until = None
        job.progress = None
    else:
        job.status = "failed"
        job.error = "orphaned by restart"


def _ingest_on_orphan(session: Session, job: Job) -> None:
    """Ingest is idempotent (content-addressed section ids make re-running it
    against the same course produce the same result), so requeuing is safe.
    Also keeps course.status in sync so the UI doesn't show a stale
    'ready'/'ingest_failed' while the job is actually still in flight or has
    been given up on for good.
    """
    default_on_orphan(session, job)
    course_id = (job.payload or {}).get("course_id")
    if not course_id:
        return
    course = session.get(Course, course_id)
    if course is None:
        return
    if job.status == "queued":
        course.status = "ingesting"
    elif job.status == "failed":
        course.status = "ingest_failed"


def _generate_lesson_on_orphan(session: Session, job: Job) -> None:
    """Mirrors _ingest_on_orphan: keep lesson_status in sync with what the
    reconciler actually did to the job, so the UI never shows a stale
    'generating' for a job that's been requeued or given up on.
    """
    default_on_orphan(session, job)
    section_id = (job.payload or {}).get("section_id")
    if not section_id:
        return
    section = session.get(Section, section_id)
    if section is None:
        return
    if job.status == "queued":
        section.lesson_status = "queued"
    elif job.status == "failed":
        section.lesson_status = "failed"


ON_ORPHAN_HOOKS: dict[str, OrphanHook] = {
    "noop": default_on_orphan,
    "ingest": _ingest_on_orphan,
    "generate_lesson": _generate_lesson_on_orphan,
}
