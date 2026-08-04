"""Blinded human review of learner-facing concept estimates."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.db.models import (
    ConceptRevision,
    CurriculumVersion,
    DiagnosticJudgment,
    LearnerConceptState,
)
from app.services.learner_context import ensure_course_learning_profile

JUDGMENTS = {"insufficient", "not_struggling", "uncertain", "likely_struggling"}
DISAGREEMENT_REASONS = {
    "model_estimate",
    "item_mapping",
    "concept_granularity",
    "insufficient_student_evidence",
    "instructor_disagreement",
}


def _model_judgment(state: str) -> str:
    if state == "insufficient_evidence":
        return "insufficient"
    if state == "likely_struggling":
        return "likely_struggling"
    if state in {"building", "watch"}:
        return "uncertain"
    return "not_struggling"


def cohens_kappa(pairs: Iterable[tuple[str, str]]) -> float | None:
    observations = list(pairs)
    if not observations:
        return None
    labels = {value for pair in observations for value in pair}
    total = len(observations)
    observed = sum(left == right for left, right in observations) / total
    left_counts = Counter(left for left, _ in observations)
    right_counts = Counter(right for _, right in observations)
    expected = sum((left_counts[label] / total) * (right_counts[label] / total) for label in labels)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def agreement_summary(
    pairs: Iterable[tuple[str, str]], *, minimum_sample: int = 20
) -> dict[str, int | float | bool | None]:
    observations = list(pairs)
    total = len(observations)
    agreements = sum(left == right for left, right in observations)
    return {
        "sample_size": total,
        "agreement_count": agreements,
        "raw_agreement": agreements / total if total else None,
        "chance_adjusted_agreement": cohens_kappa(observations),
        "sufficient_sample": total >= minimum_sample,
    }


def _current_context(session: Session, course_id: str, learner_id: str):
    profile = ensure_course_learning_profile(session, learner_id, course_id)
    version = session.query(CurriculumVersion).filter_by(
        course_id=course_id,
        is_current=True,
    ).one_or_none()
    if version is None:
        raise LookupError("published curriculum not found")
    return profile, version


def next_blind_case(course_id: str, learner_id: str, *, reviewer_key: str = "local-owner") -> dict | None:
    session = get_session()
    try:
        profile, version = _current_context(session, course_id, learner_id)
        judged = session.query(DiagnosticJudgment.concept_id).filter_by(
            course_learning_profile_id=profile.id,
            curriculum_version_id=version.id,
            reviewer_key=reviewer_key,
        )
        row = (
            session.query(ConceptRevision, LearnerConceptState)
            .join(
                LearnerConceptState,
                (LearnerConceptState.concept_id == ConceptRevision.concept_id)
                & (LearnerConceptState.curriculum_version_id == version.id)
                & (LearnerConceptState.course_learning_profile_id == profile.id)
                & (LearnerConceptState.state_scope == "concept")
                & (LearnerConceptState.model_version == "transparent-beta-v1"),
            )
            .filter(
                ConceptRevision.curriculum_version_id == version.id,
                ConceptRevision.is_active.is_(True),
                ConceptRevision.review_state != "rejected",
                ~ConceptRevision.concept_id.in_(judged),
            )
            .order_by(ConceptRevision.concept_id)
            .first()
        )
        if row is None:
            return None
        revision, state = row
        # Deliberately excludes readiness, classification, uncertainty, and model version.
        return {
            "concept_id": revision.concept_id,
            "concept_label": revision.label,
            "concept_description_md": revision.description_md,
            "evidence_available": state.distinct_item_count > 0,
        }
    finally:
        session.close()


def submit_judgment(
    course_id: str,
    learner_id: str,
    *,
    concept_id: str,
    judgment: str,
    disagreement_reason: str | None = None,
    notes_md: str | None = None,
    reviewer_key: str = "local-owner",
) -> DiagnosticJudgment:
    if judgment not in JUDGMENTS:
        raise ValueError("unsupported diagnostic judgment")
    if disagreement_reason is not None and disagreement_reason not in DISAGREEMENT_REASONS:
        raise ValueError("unsupported disagreement reason")
    session = get_session()
    try:
        profile, version = _current_context(session, course_id, learner_id)
        state = session.query(LearnerConceptState).filter_by(
            course_learning_profile_id=profile.id,
            curriculum_version_id=version.id,
            concept_id=concept_id,
            state_scope="concept",
            model_version="transparent-beta-v1",
        ).one_or_none()
        if state is None:
            raise LookupError("learner concept state not found")
        expected = _model_judgment(state.status)
        agreement = judgment == expected
        existing = session.query(DiagnosticJudgment).filter_by(
            course_learning_profile_id=profile.id,
            curriculum_version_id=version.id,
            concept_id=concept_id,
            reviewer_key=reviewer_key,
        ).one_or_none()
        if existing is not None:
            raise RuntimeError("concept has already been reviewed for this model snapshot")
        record = DiagnosticJudgment(
            course_id=course_id,
            course_learning_profile_id=profile.id,
            curriculum_version_id=version.id,
            concept_id=concept_id,
            reviewer_key=reviewer_key,
            judgment=judgment,
            disagreement_reason=disagreement_reason,
            notes_md=notes_md,
            model_state=state.status,
            readiness_estimate=state.readiness_estimate,
            evidence_count=state.distinct_item_count,
            model_version=state.model_version,
            state_calculated_at=state.calculated_at,
            agreement=agreement,
        )
        session.add(record)
        session.commit()
        return record
    finally:
        session.close()


def record_disagreement_reason(
    course_id: str,
    judgment_id: str,
    disagreement_reason: str,
) -> DiagnosticJudgment:
    if disagreement_reason not in DISAGREEMENT_REASONS:
        raise ValueError("unsupported disagreement reason")
    session = get_session()
    try:
        record = session.get(DiagnosticJudgment, judgment_id)
        if record is None or record.course_id != course_id:
            raise LookupError("diagnostic judgment not found")
        if record.agreement:
            raise ValueError("an agreement does not accept a disagreement reason")
        record.disagreement_reason = disagreement_reason
        session.commit()
        return record
    finally:
        session.close()


def course_summary(course_id: str, *, minimum_sample: int = 20) -> dict:
    session = get_session()
    try:
        records = session.query(DiagnosticJudgment).filter_by(course_id=course_id).all()
        complete_records = [
            record for record in records if record.agreement or record.disagreement_reason is not None
        ]
        pairs = [
            (record.judgment, _model_judgment(record.model_state))
            for record in complete_records
        ]
        summary = agreement_summary(pairs, minimum_sample=minimum_sample)
        reason_counts = Counter(
            record.disagreement_reason for record in records if record.disagreement_reason is not None
        )
        concept_counts = Counter(record.concept_id for record in records if not record.agreement)
        return {
            **summary,
            "pending_reason_count": len(records) - len(complete_records),
            "disagreement_reasons": dict(sorted(reason_counts.items())),
            "disagreements_by_concept": dict(sorted(concept_counts.items())),
        }
    finally:
        session.close()
