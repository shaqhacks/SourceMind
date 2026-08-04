"""Transparent, deterministic learner-state estimation from evidence events.

The constants in :class:`LearnerModelConfig` are versioned pilot hypotheses.
They are deliberately visible and replaceable; they are not claims of
universal learning thresholds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.models import (
    ConceptRevision,
    ConceptSourceLink,
    CurriculumVersion,
    EvidenceItem,
    EvidenceItemConceptLink,
    LearnerConceptState,
    LearnerEvidenceEvent,
    LearningClaimRevision,
    ensure_utc,
    utcnow,
)


@dataclass(frozen=True)
class LearnerModelConfig:
    version: str = "transparent-beta-v1"
    prior_alpha: float = 1.5
    prior_beta: float = 1.5
    target_readiness: float = 0.67
    credible_z: float = 1.64
    minimum_distinct_items: int = 3
    minimum_distinct_sessions: int = 2
    minimum_effective_evidence: float = 2.0
    review_weight: float = 0.6
    practice_weight: float = 1.0
    quiz_weight: float = 1.0
    repeated_item_exponent: float = 0.5
    success_half_life_days: float = 45.0
    minimum_success_retention: float = 0.25
    slow_response_floor: float = 0.75
    slow_response_seconds: float = 180.0


DEFAULT_CONFIG = LearnerModelConfig()


@dataclass(frozen=True)
class EvidenceObservation:
    item_id: str
    outcome: float
    channel: str
    event_at: datetime
    session_id: str | None = None
    mapping_role: str = "primary"
    spacing_seconds: float | None = None
    elapsed_ms: int | None = None
    stability_days: float | None = None


@dataclass(frozen=True)
class ClaimStateEstimate:
    readiness_estimate: float | None
    quiz_estimate: float | None
    review_estimate: float | None
    lower_bound: float | None
    upper_bound: float | None
    uncertainty: float | None
    effective_evidence_count: float
    distinct_item_count: int
    distinct_session_count: int
    trend: str
    status: str
    forgetting_risk: float
    last_evidence_at: datetime | None
    model_version: str


def _empty_estimate(config: LearnerModelConfig) -> ClaimStateEstimate:
    return ClaimStateEstimate(
        readiness_estimate=None,
        quiz_estimate=None,
        review_estimate=None,
        lower_bound=None,
        upper_bound=None,
        uncertainty=None,
        effective_evidence_count=0.0,
        distinct_item_count=0,
        distinct_session_count=0,
        trend="unknown",
        status="insufficient_evidence",
        forgetting_risk=0.0,
        last_evidence_at=None,
        model_version=config.version,
    )


def _channel_weight(channel: str, config: LearnerModelConfig) -> float:
    return {
        "quiz": config.quiz_weight,
        "practice": config.practice_weight,
        "review": config.review_weight,
    }.get(channel, 0.0)


def _retention(event: EvidenceObservation, now: datetime, config: LearnerModelConfig) -> float:
    if event.outcome <= 0:
        return 1.0
    age_days = max(0.0, (ensure_utc(now) - ensure_utc(event.event_at)).total_seconds() / 86400)
    half_life = max(config.success_half_life_days, event.stability_days or 0.0)
    return max(config.minimum_success_retention, 2 ** (-age_days / half_life))


def _elapsed_weight(event: EvidenceObservation, config: LearnerModelConfig) -> float:
    if event.elapsed_ms is None or event.elapsed_ms <= 0:
        return 1.0
    seconds = event.elapsed_ms / 1000
    if seconds <= config.slow_response_seconds:
        return 1.0
    return max(config.slow_response_floor, config.slow_response_seconds / seconds)


def _posterior(
    observations: Iterable[tuple[EvidenceObservation, float]],
    config: LearnerModelConfig,
) -> tuple[float | None, float, float, float, float]:
    rows = list(observations)
    if not rows:
        return None, config.prior_alpha, config.prior_beta, 0.0, 0.0
    success = sum(weight * event.outcome for event, weight in rows)
    failure = sum(weight * (1 - event.outcome) for event, weight in rows)
    alpha = config.prior_alpha + success
    beta = config.prior_beta + failure
    mean = alpha / (alpha + beta)
    variance = alpha * beta / (((alpha + beta) ** 2) * (alpha + beta + 1))
    return mean, alpha, beta, sum(weight for _, weight in rows), math.sqrt(variance)


def estimate_claim_state(
    events: Iterable[EvidenceObservation],
    now: datetime,
    config: LearnerModelConfig = DEFAULT_CONFIG,
) -> ClaimStateEstimate:
    ordered = sorted(events, key=lambda event: (ensure_utc(event.event_at), event.item_id))
    usable: list[tuple[EvidenceObservation, float]] = []
    occurrences: dict[str, int] = {}
    for event in ordered:
        if event.mapping_role != "primary" and event.outcome < 1.0:
            continue
        base_weight = _channel_weight(event.channel, config)
        if base_weight <= 0:
            continue
        occurrence = occurrences.get(event.item_id, 0) + 1
        occurrences[event.item_id] = occurrence
        repeat_weight = occurrence ** -config.repeated_item_exponent
        evidence_weight = (
            base_weight
            * repeat_weight
            * _retention(event, now, config)
            * _elapsed_weight(event, config)
        )
        usable.append((event, evidence_weight))

    mean, alpha, beta, effective_count, standard_deviation = _posterior(usable, config)
    item_count = len({event.item_id for event, _ in usable})
    session_count = len(
        {
            event.session_id or f"event:{index}"
            for index, (event, _) in enumerate(usable)
        }
    )
    if mean is None:
        return _empty_estimate(config)

    lower = max(0.0, mean - config.credible_z * standard_deviation)
    upper = min(1.0, mean + config.credible_z * standard_deviation)
    quiz_mean, *_ = _posterior(
        ((event, weight) for event, weight in usable if event.channel == "quiz"), config
    )
    review_mean, *_ = _posterior(
        ((event, weight) for event, weight in usable if event.channel == "review"), config
    )
    enough_evidence = (
        item_count >= config.minimum_distinct_items
        and session_count >= config.minimum_distinct_sessions
        and effective_count >= config.minimum_effective_evidence
    )
    if not enough_evidence:
        status = "insufficient_evidence"
    elif upper < config.target_readiness:
        status = "likely_struggling"
    elif lower >= config.target_readiness:
        status = "retained"
    elif mean < config.target_readiness:
        status = "building"
    else:
        status = "watch"

    weighted_sequence = [(event.event_at, event.outcome, weight) for event, weight in usable]
    midpoint = len(weighted_sequence) // 2
    if midpoint == 0:
        trend = "unknown"
    else:
        earlier = weighted_sequence[:midpoint]
        later = weighted_sequence[midpoint:]
        earlier_mean = sum(outcome * weight for _, outcome, weight in earlier) / sum(
            weight for _, _, weight in earlier
        )
        later_mean = sum(outcome * weight for _, outcome, weight in later) / sum(
            weight for _, _, weight in later
        )
        delta = later_mean - earlier_mean
        trend = "improving" if delta >= 0.15 else "declining" if delta <= -0.15 else "stable"

    last_at = max(ensure_utc(event.event_at) for event, _ in usable)
    age_days = max(0.0, (ensure_utc(now) - last_at).total_seconds() / 86400)
    max_stability = max((event.stability_days or 0.0) for event, _ in usable)
    memory_days = max(config.success_half_life_days, max_stability)
    forgetting_risk = 1 - 2 ** (-age_days / memory_days)

    return ClaimStateEstimate(
        readiness_estimate=mean,
        quiz_estimate=quiz_mean,
        review_estimate=review_mean,
        lower_bound=lower,
        upper_bound=upper,
        uncertainty=upper - lower,
        effective_evidence_count=effective_count,
        distinct_item_count=item_count,
        distinct_session_count=session_count,
        trend=trend,
        status=status,
        forgetting_risk=forgetting_risk,
        last_evidence_at=last_at,
        model_version=config.version,
    )


def roll_up_concept(
    claim_states: dict[str, ClaimStateEstimate],
    claim_importance: dict[str, float] | None = None,
    config: LearnerModelConfig = DEFAULT_CONFIG,
) -> ClaimStateEstimate:
    """Roll claim projections into a concept without treating unknown as zero."""
    importance = claim_importance or {}
    known = [
        (claim_id, state, max(0.0, importance.get(claim_id, 1.0)))
        for claim_id, state in claim_states.items()
        if state.readiness_estimate is not None
    ]
    total_weight = sum(weight for _, _, weight in known)
    if not known or total_weight <= 0:
        return _empty_estimate(config)

    def weighted(field: str) -> float | None:
        available = [
            (getattr(state, field), weight)
            for _, state, weight in known
            if getattr(state, field) is not None
        ]
        denominator = sum(weight for _, weight in available)
        if denominator <= 0:
            return None
        return sum(value * weight for value, weight in available) / denominator

    readiness = weighted("readiness_estimate")
    lower = weighted("lower_bound")
    upper = weighted("upper_bound")
    assert readiness is not None and lower is not None and upper is not None
    enough_evidence = (
        sum(state.distinct_item_count for _, state, _ in known)
        >= config.minimum_distinct_items
        and sum(state.distinct_session_count for _, state, _ in known)
        >= config.minimum_distinct_sessions
        and sum(state.effective_evidence_count for _, state, _ in known)
        >= config.minimum_effective_evidence
    )
    if not enough_evidence:
        status = "insufficient_evidence"
    elif upper < config.target_readiness:
        status = "likely_struggling"
    elif lower >= config.target_readiness:
        status = "retained"
    elif readiness < config.target_readiness:
        status = "building"
    else:
        status = "watch"
    trend_scores = {"declining": -1, "stable": 0, "improving": 1}
    trend_total = sum(trend_scores.get(state.trend, 0) * weight for _, state, weight in known)
    trend = "improving" if trend_total > 0 else "declining" if trend_total < 0 else "stable"
    last_values = [state.last_evidence_at for _, state, _ in known if state.last_evidence_at]
    return ClaimStateEstimate(
        readiness_estimate=readiness,
        quiz_estimate=weighted("quiz_estimate"),
        review_estimate=weighted("review_estimate"),
        lower_bound=lower,
        upper_bound=upper,
        uncertainty=upper - lower,
        effective_evidence_count=sum(state.effective_evidence_count for _, state, _ in known),
        distinct_item_count=sum(state.distinct_item_count for _, state, _ in known),
        distinct_session_count=sum(state.distinct_session_count for _, state, _ in known),
        trend=trend,
        status=status,
        forgetting_risk=weighted("forgetting_risk") or 0.0,
        last_evidence_at=max(last_values) if last_values else None,
        model_version=config.version,
    )


def _write_projection(
    session: Session,
    *,
    course_id: str,
    course_learning_profile_id: str,
    curriculum_version_id: str,
    concept_id: str,
    learning_claim_id: str | None,
    estimate: ClaimStateEstimate,
    calculated_through: datetime,
) -> LearnerConceptState:
    state_scope = "claim" if learning_claim_id is not None else "concept"
    state_key = f"{state_scope}:{learning_claim_id or concept_id}"
    row = session.query(LearnerConceptState).filter_by(
        course_learning_profile_id=course_learning_profile_id,
        curriculum_version_id=curriculum_version_id,
        state_key=state_key,
        model_version=estimate.model_version,
    ).one_or_none()
    if row is None:
        row = LearnerConceptState(
            course_id=course_id,
            course_learning_profile_id=course_learning_profile_id,
            curriculum_version_id=curriculum_version_id,
            concept_id=concept_id,
            learning_claim_id=learning_claim_id,
            state_scope=state_scope,
            state_key=state_key,
            model_version=estimate.model_version,
            calculated_through=calculated_through,
        )
        session.add(row)
    row.readiness_estimate = estimate.readiness_estimate
    row.quiz_estimate = estimate.quiz_estimate
    row.review_estimate = estimate.review_estimate
    row.lower_bound = estimate.lower_bound
    row.upper_bound = estimate.upper_bound
    row.uncertainty = estimate.uncertainty
    row.effective_evidence_count = estimate.effective_evidence_count
    row.distinct_item_count = estimate.distinct_item_count
    row.distinct_session_count = estimate.distinct_session_count
    row.trend = estimate.trend
    row.status = estimate.status
    row.forgetting_risk = estimate.forgetting_risk
    row.last_evidence_at = estimate.last_evidence_at
    row.calculated_through = calculated_through
    row.calculated_at = utcnow()
    session.flush()
    return row


def rebuild_profile(
    session: Session,
    course_id: str,
    course_learning_profile_id: str,
    *,
    now: datetime | None = None,
    config: LearnerModelConfig = DEFAULT_CONFIG,
) -> list[LearnerConceptState]:
    """Deterministically rebuild current-curriculum claim and concept projections."""
    cutoff = ensure_utc(now or utcnow())
    assert cutoff is not None
    version = session.query(CurriculumVersion).filter_by(
        course_id=course_id,
        is_current=True,
    ).one_or_none()
    if version is None:
        return []

    concept_revisions = session.query(ConceptRevision).filter(
        ConceptRevision.curriculum_version_id == version.id,
        ConceptRevision.is_active.is_(True),
        ConceptRevision.review_state != "rejected",
    ).all()
    active_concept_ids = {revision.concept_id for revision in concept_revisions}
    claim_revisions = session.query(LearningClaimRevision).filter(
        LearningClaimRevision.curriculum_version_id == version.id,
        LearningClaimRevision.is_active.is_(True),
        LearningClaimRevision.review_state != "rejected",
        LearningClaimRevision.concept_id.in_(active_concept_ids),
    ).all()

    valid_source_exists = session.query(ConceptSourceLink.id).filter(
        ConceptSourceLink.curriculum_version_id == version.id,
        ConceptSourceLink.learning_claim_id == EvidenceItemConceptLink.learning_claim_id,
        ConceptSourceLink.stale.is_(False),
        ConceptSourceLink.review_state != "rejected",
    ).exists()
    evidence_rows = (
        session.query(LearnerEvidenceEvent, EvidenceItemConceptLink)
        .join(
            EvidenceItemConceptLink,
            LearnerEvidenceEvent.evidence_mapping_id == EvidenceItemConceptLink.id,
        )
        .join(EvidenceItem, LearnerEvidenceEvent.evidence_item_id == EvidenceItem.id)
        .filter(
            LearnerEvidenceEvent.course_id == course_id,
            LearnerEvidenceEvent.course_learning_profile_id == course_learning_profile_id,
            LearnerEvidenceEvent.event_at <= cutoff,
            EvidenceItem.mapping_status == "mapped",
            EvidenceItemConceptLink.curriculum_version_id == version.id,
            EvidenceItemConceptLink.role == "primary",
            EvidenceItemConceptLink.review_state != "rejected",
            valid_source_exists,
        )
        .order_by(LearnerEvidenceEvent.event_at, LearnerEvidenceEvent.id)
        .all()
    )
    events_by_claim: dict[str, list[EvidenceObservation]] = {}
    for event, mapping in evidence_rows:
        raw = event.raw_result or {}
        events_by_claim.setdefault(mapping.learning_claim_id, []).append(
            EvidenceObservation(
                item_id=event.evidence_item_id,
                outcome=event.normalized_outcome,
                channel=event.channel,
                event_at=event.event_at,
                session_id=event.session_id or event.attempt_id or event.source_event_key,
                mapping_role=mapping.role,
                spacing_seconds=event.spacing_seconds,
                elapsed_ms=event.elapsed_ms,
                stability_days=raw.get("interval_days"),
            )
        )

    claims_by_concept: dict[str, dict[str, ClaimStateEstimate]] = {
        concept_id: {} for concept_id in active_concept_ids
    }
    rows: list[LearnerConceptState] = []
    for revision in claim_revisions:
        estimate = estimate_claim_state(
            events_by_claim.get(revision.learning_claim_id, []), cutoff, config
        )
        claims_by_concept.setdefault(revision.concept_id, {})[
            revision.learning_claim_id
        ] = estimate
        rows.append(
            _write_projection(
                session,
                course_id=course_id,
                course_learning_profile_id=course_learning_profile_id,
                curriculum_version_id=version.id,
                concept_id=revision.concept_id,
                learning_claim_id=revision.learning_claim_id,
                estimate=estimate,
                calculated_through=cutoff,
            )
        )
    for concept_id in sorted(active_concept_ids):
        estimate = roll_up_concept(claims_by_concept.get(concept_id, {}), config=config)
        rows.append(
            _write_projection(
                session,
                course_id=course_id,
                course_learning_profile_id=course_learning_profile_id,
                curriculum_version_id=version.id,
                concept_id=concept_id,
                learning_claim_id=None,
                estimate=estimate,
                calculated_through=cutoff,
            )
        )
    return rows
