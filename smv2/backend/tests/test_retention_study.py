from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.retention_study_service import (
    AssignmentCandidate,
    RetentionOutcome,
    assign_balanced_groups,
    summarize_outcomes,
    validate_probe_candidate,
)


def test_assignment_is_reproducible_balanced_and_immutable_by_construction():
    candidates = [
        AssignmentCandidate(profile_id=f"p-{index}", concept_id=f"c-{index}")
        for index in range(7)
    ]

    first = assign_balanced_groups("study-1", candidates, seed="pilot-v1")
    second = assign_balanced_groups("study-1", list(reversed(candidates)), seed="pilot-v1")

    assert first == second
    counts = {group: list(first.values()).count(group) for group in set(first.values())}
    assert abs(counts["adaptive_targeted"] - counts["baseline_review"]) <= 1


def test_retention_probe_must_be_unseen_and_outside_treatment_pool():
    validate_probe_candidate(
        evidence_item_id="probe-1",
        seen_item_ids={"treatment-1"},
        treatment_item_ids={"treatment-1"},
        reviewed_mapping=True,
    )
    with pytest.raises(ValueError, match="unseen"):
        validate_probe_candidate(
            evidence_item_id="treatment-1",
            seen_item_ids={"treatment-1"},
            treatment_item_ids=set(),
            reviewed_mapping=True,
        )
    with pytest.raises(ValueError, match="treatment"):
        validate_probe_candidate(
            evidence_item_id="probe-2",
            seen_item_ids=set(),
            treatment_item_ids={"probe-2"},
            reviewed_mapping=True,
        )


def test_outcome_summary_respects_delay_window_attrition_and_sample_floor():
    assigned = datetime(2026, 1, 1, tzinfo=timezone.utc)
    outcomes = [
        RetentionOutcome("adaptive_targeted", assigned + timedelta(days=8), True, 12),
        RetentionOutcome("baseline_review", assigned + timedelta(days=8), False, 12),
        RetentionOutcome("adaptive_targeted", assigned + timedelta(days=1), True, 10),
        RetentionOutcome("baseline_review", None, None, 10),
    ]

    summary = summarize_outcomes(
        outcomes,
        assigned_at=assigned,
        delay_start=timedelta(days=7),
        delay_end=timedelta(days=14),
        minimum_per_group=5,
    )

    assert summary["eligible_outcomes"] == 2
    assert summary["attrition_count"] == 1
    assert summary["outside_window_count"] == 1
    assert summary["causal_summary_allowed"] is False
    assert summary["workload_by_group"] == {
        "adaptive_targeted": 12,
        "baseline_review": 12,
    }
