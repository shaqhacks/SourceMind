from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.learner_model import EvidenceObservation
from app.services.learner_model_challengers import (
    ChallengerDataGate,
    freeze_evidence,
    predict_bkt,
    predict_das3h,
    predict_pfa,
    run_shadow_models,
)


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
OPEN_GATE = ChallengerDataGate(
    minimum_learners=1,
    minimum_attempts=1,
    minimum_unique_items=1,
    minimum_occasions=1,
    minimum_mapping_review_coverage=0,
    minimum_outcome_prevalence=0,
)


def _event(index: int, outcome: float, *, hours_ago: int = 0) -> EvidenceObservation:
    return EvidenceObservation(
        item_id=f"item-{index}",
        outcome=outcome,
        channel="quiz",
        event_at=NOW - timedelta(hours=hours_ago),
        session_id=f"session-{index}",
        spacing_seconds=hours_ago * 3600 if hours_ago else None,
    )


def test_frozen_snapshot_excludes_future_events_and_is_reproducible():
    events = [_event(1, 0, hours_ago=1), _event(2, 1, hours_ago=-1)]

    first = freeze_evidence(
        events,
        cutoff=NOW,
        learner_count=1,
        mapping_review_coverage=1.0,
    )
    second = freeze_evidence(
        list(reversed(events)),
        cutoff=NOW,
        learner_count=1,
        mapping_review_coverage=1.0,
    )

    assert len(first.events) == 1
    assert first.snapshot_hash == second.snapshot_hash
    assert all(event.event_at <= NOW for event in first.events)


def test_sparse_snapshot_is_withheld_by_every_challenger():
    snapshot = freeze_evidence(
        [_event(1, 1)],
        cutoff=NOW,
        learner_count=1,
        mapping_review_coverage=0.2,
    )

    results = [predict_bkt(snapshot), predict_pfa(snapshot), predict_das3h(snapshot)]

    assert {result.status for result in results} == {"insufficient_data"}
    assert all(result.predicted_probability is None for result in results)


def test_bkt_recovers_after_successes_and_stays_bounded():
    failures = freeze_evidence(
        [_event(i, 0, hours_ago=10 - i) for i in range(3)],
        cutoff=NOW,
        learner_count=1,
        mapping_review_coverage=1,
    )
    recovered = freeze_evidence(
        list(failures.events) + [_event(i + 3, 1, hours_ago=6 - i) for i in range(6)],
        cutoff=NOW,
        learner_count=1,
        mapping_review_coverage=1,
    )

    low = predict_bkt(failures, gate=OPEN_GATE)
    high = predict_bkt(recovered, gate=OPEN_GATE)

    assert 0 <= low.predicted_probability <= 1
    assert high.predicted_probability > low.predicted_probability


def test_pfa_penalizes_failures_and_rewards_successes():
    weak = freeze_evidence(
        [_event(i, 0) for i in range(5)],
        cutoff=NOW,
        learner_count=1,
        mapping_review_coverage=1,
    )
    strong = freeze_evidence(
        [_event(i, 1) for i in range(5)],
        cutoff=NOW,
        learner_count=1,
        mapping_review_coverage=1,
    )

    assert predict_pfa(strong, gate=OPEN_GATE).predicted_probability > predict_pfa(
        weak, gate=OPEN_GATE
    ).predicted_probability


def test_das3h_requires_spacing_then_prefers_recent_spaced_success():
    unspaced = freeze_evidence(
        [_event(i, 1) for i in range(4)],
        cutoff=NOW,
        learner_count=1,
        mapping_review_coverage=1,
    )
    spaced = freeze_evidence(
        [_event(i, 1, hours_ago=(i + 1) * 30) for i in range(4)],
        cutoff=NOW,
        learner_count=1,
        mapping_review_coverage=1,
    )

    assert predict_das3h(unspaced, gate=OPEN_GATE).status == "insufficient_data"
    result = predict_das3h(spaced, gate=OPEN_GATE)
    assert result.status == "predicted"
    assert 0 < result.predicted_probability < 1


def test_shadow_models_persist_same_cutoff_snapshot_without_duplicates(client):
    from app.db.engine import get_session
    from app.db.models import LearnerEvidenceEvent, ShadowLearnerPrediction
    from tests.test_learner_model_rebuild import _seed_projection_fixture

    session = get_session()
    try:
        course, _version, _concept, claim, _section, alice, _bob = _seed_projection_fixture(
            session
        )
        event = (
            session.query(LearnerEvidenceEvent)
            .filter_by(
                course_id=course.id,
                course_learning_profile_id=alice.id,
                learning_claim_id=claim.id,
            )
            .order_by(LearnerEvidenceEvent.event_at.desc())
            .first()
        )
        first = run_shadow_models(session, event)
        second = run_shadow_models(session, event)
        session.commit()

        assert len(first) == len(second) == 3
        assert session.query(ShadowLearnerPrediction).count() == 3
        assert {row.model_name for row in first} == {"bkt", "pfa", "das3h"}
        assert len({row.evidence_snapshot_hash for row in first}) == 1
        assert {row.training_cutoff.replace(tzinfo=timezone.utc) for row in first} == {
            event.event_at.replace(tzinfo=timezone.utc)
        }
        assert {row.status for row in first} == {"insufficient_data"}
    finally:
        session.close()
