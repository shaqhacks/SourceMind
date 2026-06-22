"""Tests for the judge revert-guard (T3 safety invariant).

The full LLM self-repair judge is SKIPPED by the T3 conditional gate (see
docs/eval/t3_judge_decision.md): the structural rubric already ceilings at 1.0
on every fixture, so no repair can raise the eval score. We still ship the
non-LLM revert-guard that any future judge MUST go through, because the risky
invariant is "keep the repaired tree only if it scores >= the original".
"""

from SourceMind.backend.services.course_engine import CompetencyTree
from SourceMind.backend.services.course_models import CourseCompetency
from SourceMind.backend.services.decomposition_judge import apply_judge_if_improved


def _tree(*comps: CourseCompetency) -> CompetencyTree:
    return CompetencyTree(chapters=[], competencies=list(comps))


def _comp(cid: str, prereqs: list[str] | None = None) -> CourseCompetency:
    return CourseCompetency(id=cid, title=cid, prerequisite_ids=prereqs or [])


GOOD = _tree(_comp("COMP_1"), _comp("COMP_2", ["COMP_1"]), _comp("COMP_3", ["COMP_2"]))
# A cyclic "repair" — strictly worse than GOOD.
BROKEN = _tree(_comp("COMP_1", ["COMP_2"]), _comp("COMP_2", ["COMP_1"]))


def test_reverts_when_repair_is_worse():
    chosen, kept, _reason = apply_judge_if_improved(GOOD, BROKEN)
    assert kept is False
    assert chosen is GOOD


def test_keeps_repair_when_not_worse():
    # Same structure, relabeled order but equally valid (tie) -> kept (>=).
    repaired = _tree(_comp("COMP_1"), _comp("COMP_2", ["COMP_1"]), _comp("COMP_3", ["COMP_2"]))
    chosen, kept, _reason = apply_judge_if_improved(GOOD, repaired)
    assert kept is True
    assert chosen is repaired


def test_reverts_when_repair_improves_nothing_below_a_broken_original():
    # Even if the original is broken, a strictly-better repair is kept.
    chosen, kept, _reason = apply_judge_if_improved(BROKEN, GOOD)
    assert kept is True
    assert chosen is GOOD
