"""Decomposition judge revert-guard (T3).

The LLM self-repair *judge* itself is intentionally NOT built — see
``docs/eval/t3_judge_decision.md`` for the gate evaluation. What ships here is
the safety invariant any future judge must honor: a repaired competency tree is
kept only if it scores at least as high as the original on the eval rubric;
otherwise the original is preserved. This makes self-repair a no-regression
operation by construction, independent of how the repaired tree is produced
(LLM, heuristic, or human edit).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from SourceMind.backend.services.decomposition_eval import score_competency_tree

if TYPE_CHECKING:  # pragma: no cover - typing only
    from SourceMind.backend.services.course_engine import CompetencyTree


def apply_judge_if_improved(
    original: CompetencyTree,
    repaired: CompetencyTree,
) -> tuple[CompetencyTree, bool, str]:
    """Return ``(chosen_tree, kept_repair, reason)``.

    ``repaired`` is kept only when its rubric total is >= the original's;
    otherwise we revert to ``original``. Never persists a regression.
    """
    original_score = score_competency_tree(original)
    repaired_score = score_competency_tree(repaired)
    if repaired_score.total >= original_score.total:
        reason = f"kept repair: {repaired_score.total:.2f} >= original {original_score.total:.2f}"
        return repaired, True, reason
    reason = f"reverted: repair {repaired_score.total:.2f} < original {original_score.total:.2f}"
    return original, False, reason
