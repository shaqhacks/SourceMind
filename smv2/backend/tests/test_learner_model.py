from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.learner_model import (
    EvidenceObservation,
    estimate_claim_state,
    roll_up_concept,
)


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _event(
    item: str,
    outcome: float,
    *,
    days_ago: float = 0,
    channel: str = "quiz",
    session: str | None = None,
    role: str = "primary",
) -> EvidenceObservation:
    return EvidenceObservation(
        item_id=item,
        outcome=outcome,
        channel=channel,
        event_at=NOW - timedelta(days=days_ago),
        session_id=session or f"session-{item}-{days_ago}",
        mapping_role=role,
    )


def test_no_evidence_is_unknown_not_zero():
    state = estimate_claim_state([], NOW)

    assert state.readiness_estimate is None
    assert state.status == "insufficient_evidence"
    assert state.effective_evidence_count == 0


def test_one_correct_answer_never_means_one_hundred_percent_readiness():
    state = estimate_claim_state([_event("item-1", 1.0)], NOW)

    assert state.readiness_estimate is not None
    assert state.readiness_estimate < 1.0
    assert state.status == "insufficient_evidence"
    assert state.uncertainty > 0


def test_repeated_same_item_cramming_is_discounted_against_varied_items():
    repeated = estimate_claim_state(
        [_event("same", 1.0, days_ago=i / 24, session=f"s{i}") for i in range(4)],
        NOW,
    )
    varied = estimate_claim_state(
        [_event(f"item-{i}", 1.0, days_ago=i, session=f"s{i}") for i in range(4)],
        NOW,
    )

    assert repeated.effective_evidence_count < varied.effective_evidence_count
    assert repeated.status == "insufficient_evidence"
    assert varied.readiness_estimate > repeated.readiness_estimate


def test_multiple_spaced_failures_are_classified_as_likely_struggling():
    state = estimate_claim_state(
        [_event(f"item-{i}", 0.0, days_ago=14 - i * 5, session=f"s{i}") for i in range(4)],
        NOW,
    )

    assert state.distinct_item_count == 4
    assert state.distinct_session_count == 4
    assert state.status == "likely_struggling"
    assert state.upper_bound < 0.67


def test_quiz_and_review_signals_are_reported_separately():
    state = estimate_claim_state(
        [
            _event("quiz-1", 0.0, days_ago=5, channel="quiz", session="q1"),
            _event("quiz-2", 1.0, days_ago=3, channel="quiz", session="q2"),
            _event("card-1", 1.0, days_ago=2, channel="review", session="r1"),
            _event("card-2", 1.0, days_ago=1, channel="review", session="r2"),
        ],
        NOW,
    )

    assert state.quiz_estimate is not None
    assert state.review_estimate is not None
    assert state.review_estimate > state.quiz_estimate


def test_delayed_varied_success_recovers_estimate_and_positive_trend():
    earlier = [_event("old-1", 0.0, days_ago=20), _event("old-2", 0.0, days_ago=15)]
    recovered = estimate_claim_state(
        earlier
        + [
            _event("new-1", 1.0, days_ago=5),
            _event("new-2", 1.0, days_ago=1),
        ],
        NOW,
    )
    before = estimate_claim_state(earlier, NOW)

    assert recovered.readiness_estimate > before.readiness_estimate
    assert recovered.trend == "improving"


def test_stale_success_has_more_forgetting_risk_than_recent_success():
    old = estimate_claim_state(
        [_event(f"item-{i}", 1.0, days_ago=120 + i, session=f"s{i}") for i in range(3)],
        NOW,
    )
    recent = estimate_claim_state(
        [_event(f"item-{i}", 1.0, days_ago=i, session=f"s{i}") for i in range(3)],
        NOW,
    )

    assert old.forgetting_risk > recent.forgetting_risk
    assert old.readiness_estimate < recent.readiness_estimate


def test_supporting_mapping_never_adds_negative_evidence():
    primary_only = estimate_claim_state([_event("p", 1.0)], NOW)
    with_supporting_failure = estimate_claim_state(
        [_event("p", 1.0), _event("s", 0.0, role="supporting")], NOW
    )

    assert with_supporting_failure.readiness_estimate == primary_only.readiness_estimate
    assert with_supporting_failure.effective_evidence_count == primary_only.effective_evidence_count


def test_concept_rollup_keeps_unknown_claims_unknown_and_uses_importance_weights():
    unknown = estimate_claim_state([], NOW)
    strong = estimate_claim_state(
        [_event(f"strong-{i}", 1.0, days_ago=i, session=f"s{i}") for i in range(8)],
        NOW,
    )
    weak = estimate_claim_state(
        [_event(f"weak-{i}", 0.0, days_ago=i, session=f"w{i}") for i in range(8)],
        NOW,
    )

    all_unknown = roll_up_concept({"unknown": unknown})
    weighted = roll_up_concept(
        {"strong": strong, "weak": weak},
        claim_importance={"strong": 3.0, "weak": 1.0},
    )

    assert all_unknown.readiness_estimate is None
    assert all_unknown.status == "insufficient_evidence"
    assert weighted.readiness_estimate > 0.5
    assert weighted.distinct_item_count == 16
