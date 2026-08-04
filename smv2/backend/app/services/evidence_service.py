from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    EvidenceItem,
    EvidenceItemConceptLink,
    LearnerEvidenceEvent,
    RetentionAssignment,
    RetentionProbe,
    ensure_utc,
    utcnow,
)
from app.services import learner_model, learner_model_challengers


def find_item(
    session: Session,
    *,
    item_type: str,
    source_record_id: str,
    source_index: int = -1,
) -> EvidenceItem | None:
    return (
        session.query(EvidenceItem)
        .filter_by(
            item_type=item_type,
            source_record_id=source_record_id,
            source_index=source_index,
        )
        .order_by(EvidenceItem.created_at.desc())
        .first()
    )


def record_event(
    session: Session,
    *,
    course_learning_profile_id: str,
    evidence_item: EvidenceItem,
    channel: str,
    normalized_outcome: float,
    raw_result: dict[str, Any],
    source_event_key: str,
    event_at: datetime | None = None,
    elapsed_ms: int | None = None,
    attempt_id: str | None = None,
    session_id: str | None = None,
    model_version: str = "evidence-v1",
) -> LearnerEvidenceEvent:
    existing = session.query(LearnerEvidenceEvent).filter_by(
        source_event_key=source_event_key
    ).one_or_none()
    if existing is not None:
        return existing
    if not 0 <= normalized_outcome <= 1:
        raise ValueError("normalized outcome must be between 0 and 1")
    mapping = (
        session.query(EvidenceItemConceptLink)
        .filter(
            EvidenceItemConceptLink.evidence_item_id == evidence_item.id,
            EvidenceItemConceptLink.role == "primary",
            EvidenceItemConceptLink.review_state != "rejected",
        )
        .one_or_none()
    )
    occurred_at = ensure_utc(event_at or utcnow())
    prior_query = session.query(LearnerEvidenceEvent).filter(
        LearnerEvidenceEvent.course_learning_profile_id == course_learning_profile_id,
        LearnerEvidenceEvent.event_at < occurred_at,
    )
    if mapping is not None:
        prior_query = prior_query.filter(
            LearnerEvidenceEvent.learning_claim_id == mapping.learning_claim_id
        )
    else:
        prior_query = prior_query.filter(
            LearnerEvidenceEvent.evidence_item_id == evidence_item.id
        )
    prior = prior_query.order_by(LearnerEvidenceEvent.event_at.desc()).first()
    spacing_seconds = None
    if prior is not None:
        spacing_seconds = max(
            0.0, (occurred_at - ensure_utc(prior.event_at)).total_seconds()
        )
    event = LearnerEvidenceEvent(
        course_id=evidence_item.course_id,
        course_learning_profile_id=course_learning_profile_id,
        evidence_item_id=evidence_item.id,
        evidence_mapping_id=mapping.id if mapping is not None else None,
        learning_claim_id=mapping.learning_claim_id if mapping is not None else None,
        curriculum_version_id=(
            mapping.curriculum_version_id if mapping is not None else None
        ),
        channel=channel,
        normalized_outcome=normalized_outcome,
        raw_result=raw_result,
        event_at=occurred_at,
        elapsed_ms=elapsed_ms,
        attempt_id=attempt_id,
        session_id=session_id,
        source_event_key=source_event_key,
        spacing_seconds=spacing_seconds,
        model_version=model_version,
    )
    session.add(event)
    session.flush()
    probe = (
        session.query(RetentionProbe)
        .join(RetentionAssignment, RetentionAssignment.id == RetentionProbe.assignment_id)
        .filter(
            RetentionProbe.evidence_item_id == evidence_item.id,
            RetentionProbe.status == "scheduled",
            RetentionAssignment.course_learning_profile_id == course_learning_profile_id,
        )
        .one_or_none()
    )
    if probe is not None:
        probe.status = "completed"
        probe.outcome_event_id = event.id
        probe.completed_at = occurred_at
    learner_model.rebuild_profile(
        session,
        evidence_item.course_id,
        course_learning_profile_id,
        now=occurred_at,
    )
    learner_model_challengers.run_shadow_models(session, event)
    return event
