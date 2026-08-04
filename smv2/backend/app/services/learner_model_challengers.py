"""Shadow-only knowledge-tracing challengers over frozen evidence snapshots."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    ConceptSourceLink,
    EvidenceItemConceptLink,
    LearnerEvidenceEvent,
    ShadowLearnerPrediction,
    ensure_utc,
)
from app.services.learner_model import EvidenceObservation


@dataclass(frozen=True)
class ChallengerDataGate:
    minimum_learners: int = 20
    minimum_attempts: int = 100
    minimum_unique_items: int = 10
    minimum_occasions: int = 3
    minimum_mapping_review_coverage: float = 0.8
    minimum_outcome_prevalence: float = 0.1


DEFAULT_GATES = {
    "bkt": ChallengerDataGate(minimum_learners=10, minimum_attempts=50),
    "pfa": ChallengerDataGate(minimum_learners=20, minimum_attempts=100),
    "das3h": ChallengerDataGate(
        minimum_learners=30,
        minimum_attempts=200,
        minimum_unique_items=15,
        minimum_occasions=4,
    ),
}


@dataclass(frozen=True)
class FrozenEvidenceSnapshot:
    events: tuple[EvidenceObservation, ...]
    cutoff: datetime
    learner_count: int
    mapping_review_coverage: float
    snapshot_hash: str


@dataclass(frozen=True)
class ChallengerPrediction:
    model_name: str
    model_version: str
    status: str
    predicted_probability: float | None
    evidence_snapshot_hash: str
    training_cutoff: datetime
    feature_schema_version: str = "learner-evidence-v1"
    prediction_horizon: str = "next_representative_item"
    target_definition: str = "probability of correctness on the next representative claim item"
    reason: str | None = None


def freeze_evidence(
    events: list[EvidenceObservation] | tuple[EvidenceObservation, ...],
    *,
    cutoff: datetime,
    learner_count: int,
    mapping_review_coverage: float,
) -> FrozenEvidenceSnapshot:
    frozen_cutoff = ensure_utc(cutoff)
    assert frozen_cutoff is not None
    eligible = tuple(
        sorted(
            (event for event in events if ensure_utc(event.event_at) <= frozen_cutoff),
            key=lambda event: (
                ensure_utc(event.event_at),
                event.item_id,
                event.session_id or "",
                event.outcome,
            ),
        )
    )
    encoded = json.dumps(
        [
            {
                **asdict(event),
                "event_at": ensure_utc(event.event_at).isoformat(),
            }
            for event in eligible
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return FrozenEvidenceSnapshot(
        events=eligible,
        cutoff=frozen_cutoff,
        learner_count=learner_count,
        mapping_review_coverage=mapping_review_coverage,
        snapshot_hash=hashlib.sha256(encoded.encode()).hexdigest(),
    )


def _gate_reason(snapshot: FrozenEvidenceSnapshot, gate: ChallengerDataGate) -> str | None:
    if snapshot.learner_count < gate.minimum_learners:
        return "minimum_learners"
    if len(snapshot.events) < gate.minimum_attempts:
        return "minimum_attempts"
    if len({event.item_id for event in snapshot.events}) < gate.minimum_unique_items:
        return "minimum_unique_items"
    if (
        len({event.session_id or event.event_at.date().isoformat() for event in snapshot.events})
        < gate.minimum_occasions
    ):
        return "minimum_occasions"
    if snapshot.mapping_review_coverage < gate.minimum_mapping_review_coverage:
        return "minimum_mapping_review_coverage"
    if snapshot.events:
        success_rate = sum(event.outcome for event in snapshot.events) / len(snapshot.events)
        if min(success_rate, 1 - success_rate) < gate.minimum_outcome_prevalence:
            return "minimum_outcome_prevalence"
    return None


def _withheld(
    model_name: str,
    model_version: str,
    snapshot: FrozenEvidenceSnapshot,
    reason: str,
) -> ChallengerPrediction:
    return ChallengerPrediction(
        model_name=model_name,
        model_version=model_version,
        status="insufficient_data",
        predicted_probability=None,
        evidence_snapshot_hash=snapshot.snapshot_hash,
        training_cutoff=snapshot.cutoff,
        reason=reason,
    )


def predict_bkt(
    snapshot: FrozenEvidenceSnapshot,
    *,
    gate: ChallengerDataGate = DEFAULT_GATES["bkt"],
    prior_learned: float = 0.2,
    learn_rate: float = 0.12,
    guess_rate: float = 0.2,
    slip_rate: float = 0.1,
) -> ChallengerPrediction:
    if reason := _gate_reason(snapshot, gate):
        return _withheld("bkt", "bkt-v1", snapshot, reason)
    learned = prior_learned
    for event in snapshot.events:
        correct_probability = learned * (1 - slip_rate) + (1 - learned) * guess_rate
        if event.outcome >= 0.5:
            learned = learned * (1 - slip_rate) / correct_probability
        else:
            incorrect_probability = 1 - correct_probability
            learned = learned * slip_rate / incorrect_probability
        learned = learned + (1 - learned) * learn_rate
    probability = learned * (1 - slip_rate) + (1 - learned) * guess_rate
    return ChallengerPrediction(
        model_name="bkt",
        model_version="bkt-v1",
        status="predicted",
        predicted_probability=max(0.0, min(1.0, probability)),
        evidence_snapshot_hash=snapshot.snapshot_hash,
        training_cutoff=snapshot.cutoff,
    )


def predict_pfa(
    snapshot: FrozenEvidenceSnapshot,
    *,
    gate: ChallengerDataGate = DEFAULT_GATES["pfa"],
    intercept: float = -0.5,
    success_coefficient: float = 0.35,
    failure_coefficient: float = -0.5,
) -> ChallengerPrediction:
    if reason := _gate_reason(snapshot, gate):
        return _withheld("pfa", "pfa-v1", snapshot, reason)
    successes = sum(event.outcome for event in snapshot.events)
    failures = sum(1 - event.outcome for event in snapshot.events)
    logit = intercept + success_coefficient * successes + failure_coefficient * failures
    probability = 1 / (1 + math.exp(-logit))
    return ChallengerPrediction(
        model_name="pfa",
        model_version="pfa-v1",
        status="predicted",
        predicted_probability=probability,
        evidence_snapshot_hash=snapshot.snapshot_hash,
        training_cutoff=snapshot.cutoff,
    )


def predict_das3h(
    snapshot: FrozenEvidenceSnapshot,
    *,
    gate: ChallengerDataGate = DEFAULT_GATES["das3h"],
) -> ChallengerPrediction:
    if reason := _gate_reason(snapshot, gate):
        return _withheld("das3h", "das3h-style-v1", snapshot, reason)
    spaced = [
        event
        for event in snapshot.events
        if event.spacing_seconds is not None and event.spacing_seconds >= 86400
    ]
    if len(spaced) < 2:
        return _withheld("das3h", "das3h-style-v1", snapshot, "minimum_spacing_data")
    windows = ((86400, 0.8), (7 * 86400, 0.5), (30 * 86400, 0.25))
    logit = -0.6
    for window_seconds, coefficient in windows:
        within = [
            event
            for event in snapshot.events
            if 0
            <= (snapshot.cutoff - ensure_utc(event.event_at)).total_seconds()
            <= window_seconds
        ]
        successes = sum(event.outcome for event in within)
        failures = sum(1 - event.outcome for event in within)
        logit += coefficient * math.log1p(successes) - (coefficient + 0.1) * math.log1p(
            failures
        )
    probability = 1 / (1 + math.exp(-logit))
    return ChallengerPrediction(
        model_name="das3h",
        model_version="das3h-style-v1",
        status="predicted",
        predicted_probability=probability,
        evidence_snapshot_hash=snapshot.snapshot_hash,
        training_cutoff=snapshot.cutoff,
    )


def run_shadow_models(
    session: Session, event: LearnerEvidenceEvent
) -> list[ShadowLearnerPrediction]:
    """Record all challengers for one claim without exposing them to production reads."""
    if event.learning_claim_id is None or event.curriculum_version_id is None:
        return []
    cutoff = ensure_utc(event.event_at)
    assert cutoff is not None
    source_is_current = session.query(ConceptSourceLink.id).filter(
        ConceptSourceLink.curriculum_version_id == event.curriculum_version_id,
        ConceptSourceLink.learning_claim_id == event.learning_claim_id,
        ConceptSourceLink.stale.is_(False),
        ConceptSourceLink.review_state != "rejected",
    ).exists()
    rows = (
        session.query(LearnerEvidenceEvent, EvidenceItemConceptLink)
        .join(
            EvidenceItemConceptLink,
            LearnerEvidenceEvent.evidence_mapping_id == EvidenceItemConceptLink.id,
        )
        .filter(
            LearnerEvidenceEvent.course_learning_profile_id
            == event.course_learning_profile_id,
            LearnerEvidenceEvent.learning_claim_id == event.learning_claim_id,
            LearnerEvidenceEvent.curriculum_version_id == event.curriculum_version_id,
            LearnerEvidenceEvent.event_at <= cutoff,
            EvidenceItemConceptLink.role == "primary",
            EvidenceItemConceptLink.review_state != "rejected",
            source_is_current,
        )
        .order_by(LearnerEvidenceEvent.event_at, LearnerEvidenceEvent.id)
        .all()
    )
    observations = [
        EvidenceObservation(
            item_id=evidence.evidence_item_id,
            outcome=evidence.normalized_outcome,
            channel=evidence.channel,
            event_at=evidence.event_at,
            session_id=evidence.session_id
            or evidence.attempt_id
            or evidence.source_event_key,
            mapping_role=mapping.role,
            spacing_seconds=evidence.spacing_seconds,
            elapsed_ms=evidence.elapsed_ms,
            stability_days=(evidence.raw_result or {}).get("interval_days"),
        )
        for evidence, mapping in rows
    ]
    learner_count = (
        session.query(func.count(func.distinct(LearnerEvidenceEvent.course_learning_profile_id)))
        .filter(
            LearnerEvidenceEvent.course_id == event.course_id,
            LearnerEvidenceEvent.learning_claim_id == event.learning_claim_id,
            LearnerEvidenceEvent.event_at <= cutoff,
        )
        .scalar()
        or 0
    )
    review_coverage = (
        sum(mapping.review_state == "verified" for _, mapping in rows) / len(rows)
        if rows
        else 0.0
    )
    snapshot = freeze_evidence(
        observations,
        cutoff=cutoff,
        learner_count=learner_count,
        mapping_review_coverage=review_coverage,
    )
    predictions = (predict_bkt(snapshot), predict_pfa(snapshot), predict_das3h(snapshot))
    stored: list[ShadowLearnerPrediction] = []
    for prediction in predictions:
        existing = session.query(ShadowLearnerPrediction).filter_by(
            course_learning_profile_id=event.course_learning_profile_id,
            learning_claim_id=event.learning_claim_id,
            model_name=prediction.model_name,
            model_version=prediction.model_version,
            evidence_snapshot_hash=prediction.evidence_snapshot_hash,
        ).one_or_none()
        if existing is not None:
            stored.append(existing)
            continue
        row = ShadowLearnerPrediction(
            course_id=event.course_id,
            course_learning_profile_id=event.course_learning_profile_id,
            curriculum_version_id=event.curriculum_version_id,
            learning_claim_id=event.learning_claim_id,
            model_name=prediction.model_name,
            model_version=prediction.model_version,
            status=prediction.status,
            predicted_probability=prediction.predicted_probability,
            evidence_snapshot_hash=prediction.evidence_snapshot_hash,
            training_cutoff=prediction.training_cutoff,
            feature_schema_version=prediction.feature_schema_version,
            prediction_horizon=prediction.prediction_horizon,
            target_definition=prediction.target_definition,
            config_json={
                "gate": asdict(DEFAULT_GATES[prediction.model_name]),
                "reason": prediction.reason,
            },
        )
        session.add(row)
        session.flush()
        stored.append(row)
    return stored
