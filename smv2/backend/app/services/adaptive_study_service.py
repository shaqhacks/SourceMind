"""Deterministic concept priority and mixed study-item selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func

from app.db.engine import get_session
from app.db.models import (
    Card,
    ConceptRevision,
    ConceptSourceLink,
    CourseLearningProfile,
    CurriculumVersion,
    EvidenceItem,
    EvidenceItemConceptLink,
    LearnerConceptState,
    LearnerEvidenceEvent,
    LearningClaimRevision,
    Job,
    PracticeAnswer,
    PracticeQuestion,
    ReviewState,
    RetentionAssignment,
    RetentionProbe,
    RetentionStudy,
    ensure_utc,
    utcnow,
)
from app.services.jobs_service import create_job_in_session
from app.services import llm_readiness_service


@dataclass(frozen=True)
class ConceptCandidate:
    concept_id: str
    status: str
    readiness_estimate: float | None
    uncertainty: float | None
    forgetting_risk: float
    curriculum_importance: float
    overdue_count: int


@dataclass(frozen=True)
class ItemCandidate:
    item_id: str
    concept_id: str
    seen_count: int
    last_seen_at: datetime | None
    reviewed_mapping: bool


_STATUS_PRIORITY = {
    "likely_struggling": 3.0,
    "building": 1.5,
    "watch": 1.2,
    "insufficient_evidence": 1.0,
    "retained": 0.0,
}


def concept_priority(candidate: ConceptCandidate) -> float:
    performance_gap = (
        0.5
        if candidate.readiness_estimate is None
        else 1 - candidate.readiness_estimate
    )
    diagnostic_confidence = (
        0.25 if candidate.uncertainty is None else max(0.0, 1 - candidate.uncertainty)
    )
    overdue = min(1.0, candidate.overdue_count / 5)
    return (
        _STATUS_PRIORITY.get(candidate.status, 0.5)
        + 0.8 * performance_gap
        + 0.4 * diagnostic_confidence
        + 0.6 * candidate.forgetting_risk
        + 0.2 * candidate.curriculum_importance
        + overdue
    )


def rank_concepts(candidates: list[ConceptCandidate]) -> list[ConceptCandidate]:
    return sorted(candidates, key=lambda item: (-concept_priority(item), item.concept_id))


def select_concepts(
    candidates: list[ConceptCandidate],
    *,
    limit: int,
    remediation_fraction: float = 0.6,
) -> list[ConceptCandidate]:
    if limit <= 0:
        return []
    remediation_cap = max(1, int(limit * remediation_fraction))
    remediation = [
        item for item in rank_concepts(candidates) if item.status == "likely_struggling"
    ][:remediation_cap]
    selected_ids = {item.concept_id for item in remediation}
    coverage = [
        item
        for item in rank_concepts(candidates)
        if item.concept_id not in selected_ids and item.status != "likely_struggling"
    ]
    return (remediation + coverage)[:limit]


def rank_items(items: list[ItemCandidate]) -> list[ItemCandidate]:
    eligible = [item for item in items if item.reviewed_mapping]
    return sorted(
        eligible,
        key=lambda item: (
            item.seen_count > 0,
            item.last_seen_at or datetime.min,
            item.seen_count,
            item.item_id,
        ),
    )


def _reason(status: str, overdue_count: int) -> str:
    if status == "likely_struggling":
        return "targeted_remediation"
    if status == "insufficient_evidence":
        return "evidence_exploration"
    if overdue_count:
        return "due_review"
    return "forgetting_risk"


def get_queue(
    course_id: str,
    learner_id: str,
    *,
    limit: int = 20,
) -> list[dict]:
    session = get_session()
    try:
        now = utcnow()
        profile = session.query(CourseLearningProfile).filter_by(
            course_id=course_id,
            learner_id=learner_id,
        ).one_or_none()
        version = session.query(CurriculumVersion).filter_by(
            course_id=course_id,
            is_current=True,
        ).one_or_none()
        if profile is None or version is None or limit <= 0:
            return []

        active_claims = {
            revision.learning_claim_id: revision.concept_id
            for revision in session.query(LearningClaimRevision)
            .filter(
                LearningClaimRevision.curriculum_version_id == version.id,
                LearningClaimRevision.is_active.is_(True),
                LearningClaimRevision.review_state != "rejected",
            )
            .all()
        }
        active_concepts = {
            revision.concept_id
            for revision in session.query(ConceptRevision)
            .filter(
                ConceptRevision.curriculum_version_id == version.id,
                ConceptRevision.is_active.is_(True),
                ConceptRevision.review_state != "rejected",
            )
            .all()
        }
        valid_source = session.query(ConceptSourceLink.id).filter(
            ConceptSourceLink.curriculum_version_id == version.id,
            ConceptSourceLink.learning_claim_id == EvidenceItemConceptLink.learning_claim_id,
            ConceptSourceLink.stale.is_(False),
            ConceptSourceLink.review_state != "rejected",
        ).exists()
        mapped_rows = (
            session.query(EvidenceItem, EvidenceItemConceptLink)
            .join(
                EvidenceItemConceptLink,
                EvidenceItemConceptLink.evidence_item_id == EvidenceItem.id,
            )
            .filter(
                EvidenceItem.course_id == course_id,
                EvidenceItem.mapping_status == "mapped",
                EvidenceItemConceptLink.curriculum_version_id == version.id,
                EvidenceItemConceptLink.role == "primary",
                EvidenceItemConceptLink.review_state == "verified",
                EvidenceItemConceptLink.learning_claim_id.in_(active_claims),
                valid_source,
            )
            .all()
        )
        item_ids = [item.id for item, _ in mapped_rows]
        exposure_rows = (
            session.query(
                LearnerEvidenceEvent.evidence_item_id,
                func.count(LearnerEvidenceEvent.id),
                func.max(LearnerEvidenceEvent.event_at),
            )
            .filter(
                LearnerEvidenceEvent.course_learning_profile_id == profile.id,
                LearnerEvidenceEvent.evidence_item_id.in_(item_ids),
            )
            .group_by(LearnerEvidenceEvent.evidence_item_id)
            .all()
            if item_ids
            else []
        )
        exposures = {item_id: (count, last_seen) for item_id, count, last_seen in exposure_rows}
        review_states = {
            state.card_id: state
            for state in session.query(ReviewState).filter_by(
                course_learning_profile_id=profile.id,
                course_id=course_id,
            )
        }
        answered_question_ids = {
            row[0]
            for row in session.query(PracticeAnswer.question_id).filter_by(
                learner_key=learner_id,
                course_id=course_id,
            )
        }
        probe_rows = (
            session.query(RetentionProbe)
            .join(RetentionAssignment, RetentionAssignment.id == RetentionProbe.assignment_id)
            .join(RetentionStudy, RetentionStudy.id == RetentionAssignment.study_id)
            .filter(
                RetentionAssignment.course_learning_profile_id == profile.id,
                RetentionStudy.status == "active",
                RetentionProbe.status == "scheduled",
            )
            .all()
        )
        probes_by_item = {probe.evidence_item_id: probe for probe in probe_rows}
        future_probe_ids = {
            probe.evidence_item_id
            for probe in probe_rows
            if ensure_utc(probe.scheduled_for) > now
        }
        due_probe_ids = set(probes_by_item) - future_probe_ids

        mapped_by_concept: dict[str, list[tuple[EvidenceItem, EvidenceItemConceptLink]]] = {}
        overdue_by_concept: dict[str, int] = {}
        for item, mapping in mapped_rows:
            if item.id in future_probe_ids:
                continue
            concept_id = active_claims[mapping.learning_claim_id]
            if concept_id not in active_concepts:
                continue
            if item.item_type == "flashcard":
                review_state = review_states.get(item.source_record_id)
                if review_state is not None and ensure_utc(review_state.due_at) > now:
                    continue
                overdue_by_concept[concept_id] = overdue_by_concept.get(concept_id, 0) + 1
            elif item.item_type == "practice_question":
                if item.source_record_id in answered_question_ids:
                    continue
            else:
                continue
            mapped_by_concept.setdefault(concept_id, []).append((item, mapping))

        states = {
            state.concept_id: state
            for state in session.query(LearnerConceptState).filter_by(
                course_learning_profile_id=profile.id,
                curriculum_version_id=version.id,
                state_scope="concept",
                model_version="transparent-beta-v1",
            )
        }
        study_groups = {
            assignment.concept_id: assignment.study_group
            for assignment in session.query(RetentionAssignment)
            .join(RetentionStudy, RetentionStudy.id == RetentionAssignment.study_id)
            .filter(
                RetentionAssignment.course_learning_profile_id == profile.id,
                RetentionStudy.status == "active",
            )
        }
        candidates = []
        for concept_id in active_concepts:
            if not mapped_by_concept.get(concept_id):
                continue
            state = states.get(concept_id)
            status = state.status if state is not None else "insufficient_evidence"
            # Control assignments receive normal due/coverage review without the
            # targeted-remediation boost. Workload remains capped by the same queue limit.
            if study_groups.get(concept_id) == "baseline_review" and status == "likely_struggling":
                status = "watch"
            candidates.append(
                ConceptCandidate(
                    concept_id=concept_id,
                    status=status,
                    readiness_estimate=(
                        state.readiness_estimate if state is not None else None
                    ),
                    uncertainty=state.uncertainty if state is not None else None,
                    forgetting_risk=state.forgetting_risk if state is not None else 0.0,
                    curriculum_importance=1.0,
                    overdue_count=overdue_by_concept.get(concept_id, 0),
                )
            )

        selected = select_concepts(candidates, limit=limit)
        due_probe_concepts = {
            active_claims[mapping.learning_claim_id]
            for item, mapping in mapped_rows
            if item.id in due_probe_ids and mapping.learning_claim_id in active_claims
        }
        selected = sorted(
            selected,
            key=lambda candidate: (
                candidate.concept_id not in due_probe_concepts,
                -concept_priority(candidate),
                candidate.concept_id,
            ),
        )
        cards = {
            card.id: card
            for card in session.query(Card).filter(
                Card.id.in_(
                    item.source_record_id
                    for item, _ in mapped_rows
                    if item.item_type == "flashcard"
                )
            )
        }
        questions = {
            question.id: question
            for question in session.query(PracticeQuestion).filter(
                PracticeQuestion.id.in_(
                    item.source_record_id
                    for item, _ in mapped_rows
                    if item.item_type == "practice_question"
                )
            )
        }
        activities: list[dict] = []
        for concept in selected:
            item_candidates = [
                ItemCandidate(
                    item_id=item.id,
                    concept_id=concept.concept_id,
                    seen_count=exposures.get(item.id, (0, None))[0],
                    last_seen_at=exposures.get(item.id, (0, None))[1],
                    reviewed_mapping=mapping.review_state == "verified",
                )
                for item, mapping in mapped_by_concept[concept.concept_id]
            ]
            ordered_ids = {candidate.item_id: index for index, candidate in enumerate(rank_items(item_candidates))}
            ordered_rows = sorted(
                mapped_by_concept[concept.concept_id],
                key=lambda row: (row[0].id not in due_probe_ids, ordered_ids[row[0].id]),
            )
            for item, mapping in ordered_rows:
                if len(activities) >= limit:
                    break
                reason = (
                    "retention_probe"
                    if item.id in due_probe_ids
                    else _reason(concept.status, concept.overdue_count)
                )
                if item.item_type == "flashcard" and item.source_record_id in cards:
                    card = cards[item.source_record_id]
                    state = review_states.get(card.id)
                    activities.append(
                        {
                            "activity_type": "flashcard",
                            "activity_id": card.id,
                            "concept_id": concept.concept_id,
                            "learning_claim_id": mapping.learning_claim_id,
                            "reason": reason,
                            "readiness_state": concept.status,
                            "due_at": state.due_at if state is not None else None,
                            "payload": {
                                "card_id": card.id,
                                "section_id": card.section_id,
                                "front_md": card.front_md,
                                "back_md": card.back_md,
                            },
                        }
                    )
                elif item.item_type == "practice_question" and item.source_record_id in questions:
                    question = questions[item.source_record_id]
                    activities.append(
                        {
                            "activity_type": "question",
                            "activity_id": question.id,
                            "concept_id": concept.concept_id,
                            "learning_claim_id": mapping.learning_claim_id,
                            "reason": reason,
                            "readiness_state": concept.status,
                            "due_at": (
                                probes_by_item[item.id].scheduled_for
                                if item.id in due_probe_ids
                                else None
                            ),
                            "payload": {
                                "question_id": question.id,
                                "section_id": question.section_id,
                                "stem_md": question.stem_md,
                                "choices": question.choices,
                                "source_ref": question.source_ref,
                            },
                        }
                    )
            if len(activities) >= limit:
                break
        return activities
    finally:
        session.close()


def start_replenishment(course_id: str, concept_id: str) -> Job:
    session = get_session()
    try:
        version = session.query(CurriculumVersion).filter_by(
            course_id=course_id,
            is_current=True,
        ).one_or_none()
        active = (
            session.query(ConceptRevision.id)
            .filter_by(
                curriculum_version_id=version.id if version is not None else "",
                concept_id=concept_id,
                is_active=True,
            )
            .filter(ConceptRevision.review_state != "rejected")
            .first()
        )
        if version is None or active is None:
            raise ValueError("active concept not found in current curriculum")
        for job in session.query(Job).filter(
            Job.type == "concept_practice_generation",
            Job.status.in_(("queued", "running")),
        ):
            payload = job.payload or {}
            if payload.get("course_id") == course_id and payload.get("concept_id") == concept_id:
                return job
        llm_readiness_service.assert_ready_for_generation()
        job = create_job_in_session(
            session,
            "concept_practice_generation",
            {
                "course_id": course_id,
                "concept_id": concept_id,
                "curriculum_version_id": version.id,
            },
        )
        session.commit()
        return job
    finally:
        session.close()
