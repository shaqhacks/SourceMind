"""Workload-matched delayed-retention study instrumentation.

This module records assignment and probe metadata only. It deliberately does
not claim an intervention effect until each group clears the configured sample
floor and the delayed window has elapsed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.db.engine import get_session
from app.db.models import (
    EvidenceItem,
    EvidenceItemConceptLink,
    LearnerEvidenceEvent,
    RetentionAssignment,
    RetentionProbe,
    RetentionStudy,
    ensure_utc,
    utcnow,
)
from app.services.learner_context import ensure_course_learning_profile


@dataclass(frozen=True, order=True)
class AssignmentCandidate:
    profile_id: str
    concept_id: str


@dataclass(frozen=True)
class RetentionOutcome:
    study_group: str
    completed_at: datetime | None
    correct: bool | None
    workload_count: int


def _assignment_digest(study_id: str, candidate: AssignmentCandidate, seed: str) -> str:
    material = f"{study_id}\0{seed}\0{candidate.profile_id}\0{candidate.concept_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def assign_balanced_groups(
    study_id: str,
    candidates: list[AssignmentCandidate],
    *,
    seed: str,
) -> dict[AssignmentCandidate, str]:
    unique = sorted(set(candidates), key=lambda item: _assignment_digest(study_id, item, seed))
    return {
        candidate: "adaptive_targeted" if index % 2 == 0 else "baseline_review"
        for index, candidate in enumerate(unique)
    }


def validate_probe_candidate(
    *,
    evidence_item_id: str,
    seen_item_ids: set[str],
    treatment_item_ids: set[str],
    reviewed_mapping: bool,
) -> None:
    if evidence_item_id in seen_item_ids:
        raise ValueError("retention probe must be unseen by the learner")
    if evidence_item_id in treatment_item_ids:
        raise ValueError("retention probe cannot reuse a treatment item")
    if not reviewed_mapping:
        raise ValueError("retention probe mapping must be reviewed")


def summarize_outcomes(
    outcomes: list[RetentionOutcome],
    *,
    assigned_at: datetime,
    delay_start: timedelta,
    delay_end: timedelta,
    minimum_per_group: int,
) -> dict:
    assigned_at = ensure_utc(assigned_at)
    assert assigned_at is not None
    window_start = assigned_at + delay_start
    window_end = assigned_at + delay_end
    eligible: list[RetentionOutcome] = []
    attrition = 0
    outside_window = 0
    for outcome in outcomes:
        if outcome.completed_at is None or outcome.correct is None:
            attrition += 1
            continue
        completed = ensure_utc(outcome.completed_at)
        assert completed is not None
        if not window_start <= completed <= window_end:
            outside_window += 1
            continue
        eligible.append(outcome)

    by_group: dict[str, list[RetentionOutcome]] = {
        "adaptive_targeted": [],
        "baseline_review": [],
    }
    for outcome in eligible:
        by_group.setdefault(outcome.study_group, []).append(outcome)
    rates = {
        group: (
            sum(bool(item.correct) for item in rows) / len(rows) if rows else None
        )
        for group, rows in by_group.items()
    }
    workload = {
        group: sum(item.workload_count for item in rows)
        for group, rows in by_group.items()
    }
    sufficient = all(len(by_group[group]) >= minimum_per_group for group in by_group)
    return {
        "eligible_outcomes": len(eligible),
        "attrition_count": attrition,
        "outside_window_count": outside_window,
        "correctness_by_group": rates,
        "workload_by_group": workload,
        "causal_summary_allowed": sufficient,
    }


def create_study(
    course_id: str,
    *,
    name: str,
    assignment_seed: str,
    delay_start_days: int = 7,
    delay_end_days: int = 14,
    minimum_per_group: int = 20,
) -> RetentionStudy:
    if delay_start_days < 1 or delay_end_days < delay_start_days:
        raise ValueError("invalid delayed-retention window")
    if minimum_per_group < 1:
        raise ValueError("minimum_per_group must be positive")
    session = get_session()
    try:
        study = RetentionStudy(
            course_id=course_id,
            name=name,
            status="active",
            assignment_seed=assignment_seed,
            delay_start_days=delay_start_days,
            delay_end_days=delay_end_days,
            minimum_per_group=minimum_per_group,
            config_json={"workload_matching": "equal_activity_target"},
        )
        session.add(study)
        session.commit()
        return study
    finally:
        session.close()


def assign_candidates(
    study_id: str,
    candidates: list[AssignmentCandidate],
    *,
    workload_target: int,
) -> list[RetentionAssignment]:
    if workload_target < 1:
        raise ValueError("workload_target must be positive")
    session = get_session()
    try:
        study = session.get(RetentionStudy, study_id)
        if study is None or study.status != "active":
            raise LookupError("active retention study not found")
        assignments = assign_balanced_groups(study.id, candidates, seed=study.assignment_seed)
        persisted: list[RetentionAssignment] = []
        for candidate, group in assignments.items():
            key = _assignment_digest(study.id, candidate, study.assignment_seed)
            row = session.query(RetentionAssignment).filter_by(assignment_key=key).one_or_none()
            if row is None:
                row = RetentionAssignment(
                    course_id=study.course_id,
                    study_id=study.id,
                    course_learning_profile_id=candidate.profile_id,
                    concept_id=candidate.concept_id,
                    study_group=group,
                    workload_target=workload_target,
                    assignment_key=key,
                )
                session.add(row)
                session.flush()
            persisted.append(row)
        session.commit()
        return persisted
    finally:
        session.close()


def assign_learner(
    study_id: str,
    course_id: str,
    learner_id: str,
    concept_id: str,
    *,
    workload_target: int,
) -> RetentionAssignment:
    session = get_session()
    try:
        profile = ensure_course_learning_profile(session, learner_id, course_id)
        session.commit()
        profile_id = profile.id
    finally:
        session.close()
    return assign_candidates(
        study_id,
        [AssignmentCandidate(profile_id=profile_id, concept_id=concept_id)],
        workload_target=workload_target,
    )[0]


def schedule_probe(
    assignment_id: str,
    learning_claim_id: str,
    *,
    now: datetime | None = None,
) -> RetentionProbe:
    now = ensure_utc(now or utcnow())
    assert now is not None
    session = get_session()
    try:
        assignment = session.get(RetentionAssignment, assignment_id)
        if assignment is None:
            raise LookupError("retention assignment not found")
        study = session.get(RetentionStudy, assignment.study_id)
        assert study is not None
        seen_ids = {
            item_id
            for (item_id,) in session.query(LearnerEvidenceEvent.evidence_item_id).filter_by(
                course_learning_profile_id=assignment.course_learning_profile_id
            )
        }
        treatment_ids = {
            item_id
            for (item_id,) in session.query(LearnerEvidenceEvent.evidence_item_id).filter(
                LearnerEvidenceEvent.course_learning_profile_id
                == assignment.course_learning_profile_id,
                LearnerEvidenceEvent.event_at >= assignment.assigned_at,
            )
        }
        candidates = (
            session.query(EvidenceItem, EvidenceItemConceptLink)
            .join(EvidenceItemConceptLink, EvidenceItemConceptLink.evidence_item_id == EvidenceItem.id)
            .filter(
                EvidenceItem.course_id == assignment.course_id,
                EvidenceItem.item_type.in_(["practice_question", "quiz_question"]),
                EvidenceItemConceptLink.learning_claim_id == learning_claim_id,
                EvidenceItemConceptLink.role == "primary",
                EvidenceItemConceptLink.review_state == "verified",
            )
            .order_by(EvidenceItem.id)
            .all()
        )
        chosen = None
        for item, mapping in candidates:
            try:
                validate_probe_candidate(
                    evidence_item_id=item.id,
                    seen_item_ids=seen_ids,
                    treatment_item_ids=treatment_ids,
                    reviewed_mapping=mapping.review_state == "verified",
                )
            except ValueError:
                continue
            chosen = item
            break
        if chosen is None:
            raise LookupError("no unseen reviewed retention probe is available")
        scheduled_for = now + timedelta(days=study.delay_start_days)
        probe = RetentionProbe(
            course_id=assignment.course_id,
            assignment_id=assignment.id,
            evidence_item_id=chosen.id,
            learning_claim_id=learning_claim_id,
            scheduled_for=scheduled_for,
        )
        session.add(probe)
        session.commit()
        return probe
    finally:
        session.close()


def active_group(profile_id: str, concept_id: str) -> str | None:
    session = get_session()
    try:
        row = (
            session.query(RetentionAssignment)
            .join(RetentionStudy, RetentionStudy.id == RetentionAssignment.study_id)
            .filter(
                RetentionAssignment.course_learning_profile_id == profile_id,
                RetentionAssignment.concept_id == concept_id,
                RetentionStudy.status == "active",
            )
            .order_by(RetentionAssignment.assigned_at.desc())
            .first()
        )
        return row.study_group if row is not None else None
    finally:
        session.close()
