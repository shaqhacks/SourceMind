"""Leakage-safe evaluation helpers for learner-model shadow predictions."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ScoredOutcome:
    predicted_probability: float
    outcome: int
    occurred_at: datetime
    subgroup: str = "all"


@dataclass(frozen=True)
class PredictionMetrics:
    count: int
    brier_score: float
    log_loss: float


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    mean_prediction: float
    observed_rate: float


@dataclass(frozen=True)
class MetricInterval:
    estimate: float
    lower: float
    upper: float


@dataclass(frozen=True)
class SubgroupResult:
    status: str
    metrics: PredictionMetrics | None


def temporal_split(
    rows: list[ScoredOutcome], *, evaluation_fraction: float = 0.2
) -> tuple[list[ScoredOutcome], list[ScoredOutcome]]:
    if not 0 < evaluation_fraction < 1:
        raise ValueError("evaluation_fraction must be between zero and one")
    ordered = sorted(rows, key=lambda row: row.occurred_at)
    evaluation_count = max(1, math.ceil(len(ordered) * evaluation_fraction))
    return ordered[:-evaluation_count], ordered[-evaluation_count:]


def evaluate_predictions(rows: list[ScoredOutcome]) -> PredictionMetrics:
    if not rows:
        raise ValueError("at least one scored outcome is required")
    brier = sum((row.predicted_probability - row.outcome) ** 2 for row in rows) / len(rows)
    epsilon = 1e-12
    log_loss = -sum(
        row.outcome * math.log(min(1 - epsilon, max(epsilon, row.predicted_probability)))
        + (1 - row.outcome)
        * math.log(min(1 - epsilon, max(epsilon, 1 - row.predicted_probability)))
        for row in rows
    ) / len(rows)
    return PredictionMetrics(count=len(rows), brier_score=brier, log_loss=log_loss)


def calibration_summary(
    rows: list[ScoredOutcome], *, bin_count: int = 10
) -> list[CalibrationBin]:
    if bin_count < 1:
        raise ValueError("bin_count must be positive")
    bins: list[list[ScoredOutcome]] = [[] for _ in range(bin_count)]
    for row in rows:
        index = min(bin_count - 1, int(row.predicted_probability * bin_count))
        bins[index].append(row)
    return [
        CalibrationBin(
            lower=index / bin_count,
            upper=(index + 1) / bin_count,
            count=len(bucket),
            mean_prediction=sum(row.predicted_probability for row in bucket) / len(bucket),
            observed_rate=sum(row.outcome for row in bucket) / len(bucket),
        )
        for index, bucket in enumerate(bins)
        if bucket
    ]


def bootstrap_brier_interval(
    rows: list[ScoredOutcome],
    *,
    samples: int = 1000,
    seed: int = 0,
) -> MetricInterval:
    if not rows or samples < 1:
        raise ValueError("rows and positive samples are required")
    rng = random.Random(seed)
    scores = []
    for _ in range(samples):
        sample = [rng.choice(rows) for _ in rows]
        scores.append(evaluate_predictions(sample).brier_score)
    scores.sort()
    lower = scores[int(0.025 * (samples - 1))]
    upper = scores[int(0.975 * (samples - 1))]
    return MetricInterval(
        estimate=evaluate_predictions(rows).brier_score,
        lower=lower,
        upper=upper,
    )


def subgroup_report(
    rows: list[ScoredOutcome], *, minimum_group_size: int
) -> dict[str, SubgroupResult]:
    grouped: dict[str, list[ScoredOutcome]] = {}
    for row in rows:
        grouped.setdefault(row.subgroup, []).append(row)
    return {
        group: (
            SubgroupResult("reported", evaluate_predictions(group_rows))
            if len(group_rows) >= minimum_group_size
            else SubgroupResult("insufficient_data", None)
        )
        for group, group_rows in grouped.items()
    }
