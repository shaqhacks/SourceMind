"""Tests for the decomposition eval harness (T2).

The harness scores a CompetencyTree on four structural criteria — no cycles,
genuine prerequisites, cold-start roots, correct ordering — and compares the
automated score against human-graded ground truth recorded with the fixtures.
"""

import pytest

from SourceMind.backend.services.course_engine import CompetencyTree, CourseEngine
from SourceMind.backend.services.course_models import CourseCompetency
from SourceMind.backend.services.decomposition_eval import (
    RubricScore,
    load_eval_sources,
    run_eval,
    score_competency_tree,
)


def _tree(*competencies: CourseCompetency) -> CompetencyTree:
    return CompetencyTree(chapters=[], competencies=list(competencies))


def _comp(comp_id: str, prereqs: list[str] | None = None) -> CourseCompetency:
    return CourseCompetency(id=comp_id, title=comp_id, prerequisite_ids=prereqs or [])


def test_clean_linear_chain_scores_perfect():
    tree = _tree(
        _comp("COMP_1"),
        _comp("COMP_2", ["COMP_1"]),
        _comp("COMP_3", ["COMP_2"]),
    )

    score = score_competency_tree(tree)

    assert isinstance(score, RubricScore)
    assert score.acyclic == 1.0
    assert score.genuine_prerequisites == 1.0
    assert score.cold_start_roots == 1.0
    assert score.correct_ordering == 1.0
    assert score.total == 1.0
    assert score.passed is True


def test_cycle_is_detected_and_fails():
    tree = _tree(
        _comp("COMP_1", ["COMP_2"]),
        _comp("COMP_2", ["COMP_1"]),
    )

    score = score_competency_tree(tree)

    assert score.acyclic == 0.0
    assert score.passed is False
    assert any("cycle" in note.lower() for note in score.notes)


def test_forward_reference_breaks_ordering_and_genuineness():
    # COMP_1 depends on a competency that appears AFTER it: not a cycle, but
    # neither correctly ordered nor a genuine (earlier) prerequisite.
    tree = _tree(
        _comp("COMP_1", ["COMP_2"]),
        _comp("COMP_2"),
    )

    score = score_competency_tree(tree)

    assert score.acyclic == 1.0
    assert score.genuine_prerequisites == 0.0
    assert score.correct_ordering == pytest.approx(0.5)
    assert score.cold_start_roots == 1.0


def test_all_isolated_nodes_have_no_cold_start_spine():
    # Every node is a root => there is no learning spine / ordering at all.
    tree = _tree(_comp("COMP_1"), _comp("COMP_2"), _comp("COMP_3"))

    score = score_competency_tree(tree)

    assert score.cold_start_roots == 0.0
    assert score.passed is False


def test_missing_prerequisite_target_is_not_genuine():
    tree = _tree(
        _comp("COMP_1"),
        _comp("COMP_2", ["COMP_404"]),  # references a competency that doesn't exist
    )

    score = score_competency_tree(tree)

    assert score.genuine_prerequisites == 0.0
    assert any("COMP_404" in note for note in score.notes)


def test_single_node_tree_is_trivially_valid():
    score = score_competency_tree(_tree(_comp("COMP_1")))

    assert score.cold_start_roots == 1.0
    assert score.genuine_prerequisites == 1.0
    assert score.correct_ordering == 1.0


def test_empty_tree_scores_zero_and_fails():
    score = score_competency_tree(_tree())

    assert score.total == 0.0
    assert score.passed is False


# --- Fixture corpus (>=5 sources, >=3 domains, >=3 source types, one messy) ---


def test_fixture_corpus_meets_coverage_requirements():
    sources = load_eval_sources()

    assert len(sources) >= 5
    assert len({s.domain for s in sources}) >= 3
    assert len({s.source_type for s in sources}) >= 3
    assert sum(1 for s in sources if s.messy) >= 1
    for source in sources:
        assert source.raw_text.strip(), f"{source.id} has empty raw_text"
        assert "passed" in source.ground_truth


def test_run_eval_scores_every_source_and_records_ground_truth_agreement():
    engine = CourseEngine()
    sources = load_eval_sources()

    results = run_eval(engine, sources)

    assert len(results) == len(sources)
    for result in results:
        assert isinstance(result.harness_score, RubricScore)
        # Ground truth is authoritative: the harness must agree with the
        # human-graded pass/fail verdict on these curated fixtures.
        assert result.harness_score.passed == result.ground_truth["passed"], (
            f"{result.source_id}: harness disagreed with ground truth"
        )


def test_run_eval_can_record_scores_to_disk(tmp_path):
    from SourceMind.backend.services.decomposition_eval import record_eval

    engine = CourseEngine()
    results = run_eval(engine, load_eval_sources())
    out_path = tmp_path / "scores.json"

    record_eval(results, out_path)

    assert out_path.exists()
    import json

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["source_count"] == len(results)
    assert len(payload["results"]) == len(results)
    assert all("harness_score" in row and "ground_truth" in row for row in payload["results"])
