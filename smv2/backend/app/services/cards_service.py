"""Card generation job creation and listing. Business logic for
generate_cards/list_cards — routers only do existence/state checks and
delegate here.
"""

from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Card, Job, Section
from app.services import jobs_service

_ACTIVE_JOB_STATUSES = ("queued", "running")


class SectionNotFoundError(ValueError):
    pass


class CardGenerationAlreadyInProgressError(ValueError):
    pass


def _has_active_generate_cards_job(session, section_id: str) -> bool:
    """No dedicated status column on Section for this (unlike lessons) —
    a job-table scan is an accepted, deliberately lower-stakes TOCTOU here:
    duplicate generate_cards jobs are wasteful, not corrupting, since card
    generation is idempotent (content-addressed cards diff cleanly).
    """
    active_jobs = (
        session.query(Job)
        .filter(Job.type == "generate_cards", Job.status.in_(_ACTIVE_JOB_STATUSES))
        .all()
    )
    return any((j.payload or {}).get("section_id") == section_id for j in active_jobs)


def start_card_generation(section_id: str) -> str:
    session = get_session()
    try:
        section = session.get(Section, section_id)
        if section is None:
            raise SectionNotFoundError(f"section not found: {section_id}")
        if _has_active_generate_cards_job(session, section_id):
            raise CardGenerationAlreadyInProgressError(
                f"card generation already in progress for section {section_id}"
            )
    finally:
        session.close()

    job = jobs_service.create_job("generate_cards", {"section_id": section_id})
    return job.id


def list_cards(section_id: str) -> list[Card] | None:
    session = get_session()
    try:
        section = session.get(Section, section_id)
        if section is None:
            return None
        return (
            session.query(Card)
            .filter(Card.section_id == section_id)
            .order_by(Card.position)
            .all()
        )
    finally:
        session.close()
