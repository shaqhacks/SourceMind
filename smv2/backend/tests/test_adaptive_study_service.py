from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.adaptive_study_service import (
    ConceptCandidate,
    ItemCandidate,
    rank_concepts,
    rank_items,
    select_concepts,
)


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def _concept(
    concept_id: str,
    *,
    status: str,
    readiness: float | None,
    uncertainty: float | None = 0.2,
    forgetting: float = 0.1,
    overdue: int = 0,
) -> ConceptCandidate:
    return ConceptCandidate(
        concept_id=concept_id,
        status=status,
        readiness_estimate=readiness,
        uncertainty=uncertainty,
        forgetting_risk=forgetting,
        curriculum_importance=1.0,
        overdue_count=overdue,
    )


def test_weak_and_overdue_concepts_rank_ahead_of_retained_concepts():
    ordered = rank_concepts(
        [
            _concept("retained", status="retained", readiness=0.9),
            _concept("weak", status="likely_struggling", readiness=0.3),
            _concept("due", status="building", readiness=0.6, overdue=5),
        ]
    )

    assert ordered[0].concept_id == "weak"
    assert ordered[-1].concept_id == "retained"


def test_insufficient_evidence_receives_exploration_capacity():
    selected = select_concepts(
        [
            _concept(f"weak-{i}", status="likely_struggling", readiness=0.2)
            for i in range(5)
        ]
        + [_concept("unknown", status="insufficient_evidence", readiness=None, uncertainty=None)],
        limit=4,
        remediation_fraction=0.5,
    )

    assert "unknown" in {candidate.concept_id for candidate in selected}
    assert sum(candidate.status == "likely_struggling" for candidate in selected) <= 2


def test_concept_ranking_has_deterministic_tie_breaking():
    candidates = [
        _concept("b", status="building", readiness=0.5),
        _concept("a", status="building", readiness=0.5),
    ]

    assert [candidate.concept_id for candidate in rank_concepts(candidates)] == ["a", "b"]


def test_item_selection_prefers_unseen_then_least_recently_seen_items():
    items = [
        ItemCandidate("seen-recent", "c", 2, NOW - timedelta(hours=1), True),
        ItemCandidate("unseen", "c", 0, None, True),
        ItemCandidate("seen-old", "c", 1, NOW - timedelta(days=10), True),
        ItemCandidate("unreviewed", "c", 0, None, False),
    ]

    assert [item.item_id for item in rank_items(items)] == [
        "unseen",
        "seen-old",
        "seen-recent",
    ]
