from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.learner_model_evaluation import (
    ScoredOutcome,
    bootstrap_brier_interval,
    calibration_summary,
    evaluate_predictions,
    subgroup_report,
    temporal_split,
)


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def _row(index: int, probability: float, outcome: int, group: str = "A") -> ScoredOutcome:
    return ScoredOutcome(
        predicted_probability=probability,
        outcome=outcome,
        occurred_at=NOW + timedelta(days=index),
        subgroup=group,
    )


def test_temporal_split_never_leaks_future_rows_into_training():
    rows = [_row(i, 0.5, i % 2) for i in range(10)]

    train, evaluation = temporal_split(rows, evaluation_fraction=0.3)

    assert len(train) == 7
    assert len(evaluation) == 3
    assert max(row.occurred_at for row in train) < min(
        row.occurred_at for row in evaluation
    )


def test_metrics_reward_calibrated_correct_predictions():
    good = [_row(0, 0.1, 0), _row(1, 0.9, 1)]
    bad = [_row(0, 0.9, 0), _row(1, 0.1, 1)]

    good_metrics = evaluate_predictions(good)
    bad_metrics = evaluate_predictions(bad)

    assert good_metrics.brier_score < bad_metrics.brier_score
    assert good_metrics.log_loss < bad_metrics.log_loss
    assert calibration_summary(good, bin_count=2)[0].count == 1


def test_bootstrap_interval_and_subgroups_are_deterministic_and_withhold_sparse_groups():
    rows = [
        _row(i, 0.8 if i % 2 else 0.2, i % 2, "large" if i < 8 else "small")
        for i in range(10)
    ]

    first = bootstrap_brier_interval(rows, samples=100, seed=7)
    second = bootstrap_brier_interval(rows, samples=100, seed=7)
    groups = subgroup_report(rows, minimum_group_size=3)

    assert first == second
    assert first.lower <= first.estimate <= first.upper
    assert groups["large"].status == "reported"
    assert groups["small"].status == "insufficient_data"
