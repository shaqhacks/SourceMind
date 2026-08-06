"""Card generation job creation and listing, plus direct card
authoring/editing (ADR-023: origin='generated'|'user', content-addressed
edit-as-new-card). Business logic for generate_cards/list_cards/
update_card/delete_card — routers only do existence/state checks and
delegate here.
"""

from __future__ import annotations

from sqlalchemy import update as sa_update

from app.db.engine import get_session
from app.db.identity import card_id_for
from app.db.models import Card, Job, ReviewLog, ReviewState, Section
from app.services import jobs_service, llm_readiness_service

_ACTIVE_JOB_STATUSES = ("queued", "running")


class SectionNotFoundError(ValueError):
    pass


class CardGenerationAlreadyInProgressError(ValueError):
    pass


class CardNotFoundError(ValueError):
    pass


class DuplicateCardError(ValueError):
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
        llm_readiness_service.assert_ready_for_generation()
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


def update_card(card_id: str, front_md: str, back_md: str) -> Card:
    """Content-addressed edit: new front/back text means a NEW id — the
    card-identity law holds for user edits too, not just generation
    (ADR-023). Raises CardNotFoundError if card_id doesn't exist,
    DuplicateCardError if the edited content collides with ANOTHER
    already-existing card in the same section (the section's existing
    dedup law, surfaced as a real error here instead of a silent merge).

    If the new content hashes to the SAME id (a byte-for-byte no-op
    edit), returns the existing card unchanged — nothing to migrate.
    """
    session = get_session()
    try:
        card = session.get(Card, card_id)
        if card is None:
            raise CardNotFoundError(f"card not found: {card_id}")

        new_id = card_id_for(card.section_id, front_md, back_md)
        if new_id == card.id:
            return card

        if session.get(Card, new_id) is not None:
            raise DuplicateCardError(
                f"edited content duplicates an existing card in this section: {new_id}"
            )

        # New card inserted FIRST — review_states/review_logs get
        # repointed at it below, and PRAGMA foreign_keys=ON enforces that
        # FK per-statement, so the target must already exist.
        new_card = Card(
            id=new_id,
            course_id=card.course_id,
            section_id=card.section_id,
            front_md=front_md,
            back_md=back_md,
            position=card.position,
            origin="user",
        )
        session.add(new_card)
        session.flush()

        # Migrate review history old id -> new id (explicit preservation,
        # not a fresh start for the learner's SM-2 progress on this card).
        # Verified empirically that a raw Core UPDATE on ReviewState.card_id
        # (its own primary key) is handled cleanly by SQLite + SQLAlchemy —
        # no ORM identity-map staleness, no insert-copy+delete needed.
        session.execute(sa_update(ReviewState).where(ReviewState.card_id == card.id).values(card_id=new_id))
        session.execute(sa_update(ReviewLog).where(ReviewLog.card_id == card.id).values(card_id=new_id))

        session.delete(card)
        session.commit()
        session.refresh(new_card)
        return new_card
    finally:
        session.close()


def delete_card(card_id: str) -> bool:
    """Cascades ReviewState/ReviewLog on purpose (ON DELETE CASCADE) —
    deleting a card is an explicit, permanent removal of its review
    history along with it, unlike update_card, which migrates that
    history forward onto the edited card's new id instead of losing it.
    """
    session = get_session()
    try:
        card = session.get(Card, card_id)
        if card is None:
            return False
        session.delete(card)
        session.commit()
        return True
    finally:
        session.close()
