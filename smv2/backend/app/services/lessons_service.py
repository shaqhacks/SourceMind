"""Lesson generation: job creation/enqueueing and cost/time estimation.
Business logic for the generate_lesson/generate_all_lessons/lesson_estimate
endpoints — routers only do existence/state checks and delegate here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.config import llm_model
from app.db.engine import get_session
from app.db.models import LlmCall, Section
from app.llm.pricing import estimate_cost
from app.services import jobs_service

_RECENT_CALLS_LIMIT = 20
_DEFAULT_ESTIMATE_SECONDS = 30.0
_MAX_TOKENS_ESTIMATE = 4096

# Atomic claim: a single statement, not a read-then-write — two concurrent
# generate_lesson submissions for the same section must not both pass a
# separate "is it already in progress" check before either writes
# lesson_status. force=true bypasses the NOT IN guard entirely.
_CLAIM_LESSON_SQL = text(
    """
    UPDATE sections
    SET lesson_status = 'queued'
    WHERE id = :section_id
    AND (:force OR lesson_status NOT IN ('queued', 'generating'))
    RETURNING id
    """
)


class SectionNotFoundError(ValueError):
    pass


class LessonAlreadyInProgressError(ValueError):
    pass


def start_lesson_generation(section_id: str, force: bool = False) -> str:
    """Atomically claims the section (lesson_status -> 'queued') and
    enqueues its generate_lesson job.

    Raises SectionNotFoundError if the section doesn't exist, or
    LessonAlreadyInProgressError if it's already queued/generating and
    force=False — the router maps these to 404/409 respectively.
    """
    session = get_session()
    try:
        result = session.execute(_CLAIM_LESSON_SQL, {"section_id": section_id, "force": force})
        claimed = result.first() is not None
        session.commit()

        if not claimed:
            section = session.get(Section, section_id)
            if section is None:
                raise SectionNotFoundError(f"section not found: {section_id}")
            raise LessonAlreadyInProgressError(
                f"lesson generation already in progress for section {section_id}"
            )
    finally:
        session.close()

    job = jobs_service.create_job("generate_lesson", {"section_id": section_id})
    return job.id


def start_all_lesson_generations(course_id: str) -> tuple[list[str], int]:
    session = get_session()
    try:
        all_sections = (
            session.query(Section)
            .filter(Section.course_id == course_id)
            .order_by(Section.order_index)
            .all()
        )
        to_generate = [s for s in all_sections if s.lesson_status in ("none", "failed")]
        for s in to_generate:
            s.lesson_status = "queued"
        section_ids = [s.id for s in to_generate]
        skipped = len(all_sections) - len(to_generate)
        session.commit()
    finally:
        session.close()

    job_ids = [jobs_service.create_job("generate_lesson", {"section_id": sid}).id for sid in section_ids]
    return job_ids, skipped


def estimate_lesson(section_id: str) -> dict[str, Any] | None:
    session = get_session()
    try:
        section = session.get(Section, section_id)
        if section is None:
            return None

        recent = (
            session.query(LlmCall)
            .filter(LlmCall.purpose == "lesson")
            .order_by(LlmCall.ts.desc())
            .limit(_RECENT_CALLS_LIMIT)
            .all()
        )
        if recent:
            avg_seconds = sum(c.latency_ms for c in recent) / len(recent) / 1000
            costs = [c.cost_estimate for c in recent if c.cost_estimate is not None]
            avg_cost = sum(costs) / len(costs) if costs else None
            return {
                "est_seconds": avg_seconds,
                "est_cost_usd": avg_cost,
                "based_on_calls": len(recent),
            }

        # Deterministic default when there's no history yet.
        input_tokens_est = max(1, len(section.body_md or "") // 4)
        output_tokens_est = min(input_tokens_est, _MAX_TOKENS_ESTIMATE)
        cost = estimate_cost(llm_model(), input_tokens_est, output_tokens_est)
        return {
            "est_seconds": _DEFAULT_ESTIMATE_SECONDS,
            "est_cost_usd": cost,
            "based_on_calls": 0,
        }
    finally:
        session.close()
