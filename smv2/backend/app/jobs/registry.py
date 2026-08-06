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

from app.db.models import Asset, Course, Job, Section
from app.pipeline.cards_generation import run_card_generation
from app.pipeline.concept_extraction import run_concept_extraction
from app.pipeline.concept_practice_generation import run_concept_practice_generation
from app.pipeline.embedding import run_embed_course
from app.pipeline.generation import run_lesson_generation
from app.pipeline.html_conversion import run_html_conversion
from app.pipeline.ingest import run_ingest
from app.pipeline.practice_extraction import run_practice_extraction
from app.pipeline.quiz_generation import run_test_generation
from app.services import learner_context
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


def _generate_cards_handler(session: Session, job: Job) -> dict[str, Any]:
    section_id = (job.payload or {}).get("section_id")
    if not section_id:
        raise ValueError("generate_cards job payload missing section_id")
    extra = run_card_generation(session, job, section_id)
    return {"section_id": section_id, **extra}


def _generate_test_handler(session: Session, job: Job) -> dict[str, Any]:
    payload = job.payload or {}
    course_id = payload.get("course_id")
    if not course_id:
        raise ValueError("generate_test job payload missing course_id")
    course_learning_profile_id = payload.get("course_learning_profile_id")
    if not course_learning_profile_id:
        course_learning_profile_id = learner_context.ensure_course_learning_profile(
            session, learner_context.LEGACY_LOCAL_LEARNER_ID, course_id
        ).id
    extra = run_test_generation(
        session,
        job,
        course_id,
        payload.get("section_ids"),
        payload.get("chapter_label"),
        course_learning_profile_id=course_learning_profile_id,
    )
    return {"course_id": course_id, **extra}


def _generate_practice_assessment_handler(session: Session, job: Job) -> dict[str, Any]:
    payload = job.payload or {}
    course_id = payload.get("course_id")
    section_id = payload.get("section_id")
    run_id = payload.get("run_id")
    if not course_id:
        raise ValueError("generate_practice_assessment job payload missing course_id")
    if not section_id:
        raise ValueError("generate_practice_assessment job payload missing section_id")
    if not run_id:
        raise ValueError("generate_practice_assessment job payload missing run_id")
    return run_practice_extraction(session, job, course_id, section_id, run_id)


def _concept_extraction_handler(session: Session, job: Job) -> dict[str, Any]:
    payload = job.payload or {}
    course_id = payload.get("course_id")
    curriculum_version_id = payload.get("curriculum_version_id")
    if not course_id:
        raise ValueError("concept_extraction job payload missing course_id")
    if not curriculum_version_id:
        raise ValueError("concept_extraction job payload missing curriculum_version_id")
    return run_concept_extraction(session, job, course_id, curriculum_version_id)


def _concept_practice_generation_handler(
    session: Session, job: Job
) -> dict[str, Any]:
    payload = job.payload or {}
    course_id = payload.get("course_id")
    concept_id = payload.get("concept_id")
    curriculum_version_id = payload.get("curriculum_version_id")
    if not course_id or not concept_id or not curriculum_version_id:
        raise ValueError("concept practice generation job payload is incomplete")
    return run_concept_practice_generation(
        session,
        job,
        course_id,
        concept_id,
        curriculum_version_id,
    )


def _embed_course_handler(session: Session, job: Job) -> dict[str, Any]:
    course_id = (job.payload or {}).get("course_id")
    if not course_id:
        raise ValueError("embed_course job payload missing course_id")
    extra = run_embed_course(session, job, course_id)
    return {"course_id": course_id, **extra}


def _convert_html_handler(session: Session, job: Job) -> dict[str, Any]:
    course_id = (job.payload or {}).get("course_id")
    if not course_id:
        raise ValueError("convert_html job payload missing course_id")
    extra = run_html_conversion(session, job, course_id)
    return {"course_id": course_id, **extra}


JOB_HANDLERS: dict[str, JobHandler] = {
    "noop": _noop_handler,
    "backup": _backup_handler,
    "ingest": _ingest_handler,
    "generate_lesson": _generate_lesson_handler,
    "generate_cards": _generate_cards_handler,
    "generate_test": _generate_test_handler,
    "generate_practice_assessment": _generate_practice_assessment_handler,
    "concept_extraction": _concept_extraction_handler,
    "concept_practice_generation": _concept_practice_generation_handler,
    "embed_course": _embed_course_handler,
    "convert_html": _convert_html_handler,
}

RETRYABLE_JOB_TYPES = frozenset(
    {
        "generate_lesson",
        "generate_cards",
        "generate_test",
        "generate_practice_assessment",
        "concept_extraction",
        "concept_practice_generation",
    }
)

LLM_READINESS_REQUIRED_JOB_TYPES = frozenset(
    {
        "generate_lesson",
        "generate_cards",
        "generate_test",
        "generate_practice_assessment",
        "concept_extraction",
        "concept_practice_generation",
    }
)


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


def _convert_html_on_orphan(session: Session, job: Job) -> None:
    """Mirrors _ingest_on_orphan/_generate_lesson_on_orphan: Asset.html_status
    is a user-visible status the frontend polls, so it must not be left
    stuck on 'converting' after an orphan event. Requeued: leave assets
    already 'converting' as-is, the retry picks them back up. Exhausted:
    flip any still-'converting' asset to 'failed' so the UI stops showing
    a stale spinner for a conversion that will never resume.
    """
    default_on_orphan(session, job)
    if job.status != "failed":
        return
    course_id = (job.payload or {}).get("course_id")
    if not course_id:
        return
    stuck = (
        session.query(Asset)
        .filter(Asset.course_id == course_id, Asset.html_status == "converting")
        .all()
    )
    for asset in stuck:
        asset.html_status = "failed"


ON_ORPHAN_HOOKS: dict[str, OrphanHook] = {
    "noop": default_on_orphan,
    "ingest": _ingest_on_orphan,
    "generate_lesson": _generate_lesson_on_orphan,
    "concept_extraction": default_on_orphan,
    "concept_practice_generation": default_on_orphan,
    "convert_html": _convert_html_on_orphan,
}
