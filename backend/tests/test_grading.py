"""Pure unit tests for backend/services/grading.py."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from SourceMind.backend.services.grading import PASS_THRESHOLD, grade_course_quizzes, grade_quiz

SAMPLE_QUIZ = [
    {"q": "Q1", "options": ["A", "B", "C", "D"], "answer": 0, "explain": "A is right."},
    {"q": "Q2", "options": ["A", "B", "C", "D"], "answer": 1, "explain": "B is right."},
    {"q": "Q3", "options": ["A", "B", "C", "D"], "answer": 2, "explain": "C is right."},
    {"q": "Q4", "options": ["A", "B", "C", "D"], "answer": 3, "explain": "D is right."},
]

TEN_QUIZ = [
    {"q": f"Q{i}", "options": ["A", "B"], "answer": 0, "explain": ""}
    for i in range(10)
]


class TestGradeQuizScoresAndPasses:
    """Test grade_quiz scoring, pass/fail, and edge cases."""

    def test_all_correct(self):
        result = grade_quiz(SAMPLE_QUIZ, [0, 1, 2, 3])
        assert result["correct"] == 4
        assert result["total"] == 4
        assert result["score"] == 1.0
        assert result["passed"] is True

    def test_all_wrong(self):
        result = grade_quiz(SAMPLE_QUIZ, [1, 0, 0, 0])
        assert result["correct"] == 0
        assert result["total"] == 4
        assert result["score"] == 0.0
        assert result["passed"] is False

    def test_partial_score_below_threshold(self):
        # 2/4 = 0.5 — below PASS_THRESHOLD (0.7 default)
        result = grade_quiz(SAMPLE_QUIZ, [0, 1, 0, 0])
        assert result["correct"] == 2
        assert result["score"] == pytest.approx(0.5)
        assert result["passed"] is False

    def test_partial_score_at_threshold(self):
        # Need score >= 0.7; with 4 items: 3/4 = 0.75 >= 0.7 → passes
        result = grade_quiz(SAMPLE_QUIZ, [0, 1, 2, 0])
        assert result["correct"] == 3
        assert result["score"] == pytest.approx(0.75)
        assert result["passed"] is True

    def test_missing_answers_treated_wrong(self):
        # Only 2 answers for 4 questions → items 2 and 3 wrong
        result = grade_quiz(SAMPLE_QUIZ, [0, 1])
        assert result["correct"] == 2
        assert result["total"] == 4
        assert result["score"] == pytest.approx(0.5)
        # your_index for missing items is None
        assert result["results"][2]["your_index"] is None
        assert result["results"][3]["your_index"] is None
        assert result["results"][2]["correct"] is False
        assert result["results"][3]["correct"] is False

    def test_extra_answers_ignored(self):
        # 6 answers for 4 questions → extra entries ignored
        result = grade_quiz(SAMPLE_QUIZ, [0, 1, 2, 3, 99, 99])
        assert result["correct"] == 4
        assert result["total"] == 4

    def test_empty_quiz_returns_zero_score(self):
        result = grade_quiz([], [])
        assert result["correct"] == 0
        assert result["total"] == 0
        assert result["score"] == 0.0
        assert result["passed"] is False
        assert result["results"] == []

    def test_results_structure(self):
        result = grade_quiz(SAMPLE_QUIZ, [0, 0, 0, 0])
        for item in result["results"]:
            assert "q" in item
            assert "options" in item
            assert "your_index" in item
            assert "answer_index" in item
            assert "correct" in item
            assert "explain" in item

    def test_threshold_straddle(self):
        # 7/10 = 0.70 == PASS_THRESHOLD (default) → passes (>=)
        passing = [0] * 7 + [1] * 3
        result = grade_quiz(TEN_QUIZ, passing)
        assert result["correct"] == 7
        assert result["score"] == pytest.approx(0.7)
        assert result["passed"] is True
        # 6/10 = 0.60 < 0.70 → fails
        failing = [0] * 6 + [1] * 4
        result2 = grade_quiz(TEN_QUIZ, failing)
        assert result2["correct"] == 6
        assert result2["score"] == pytest.approx(0.6)
        assert result2["passed"] is False

    def test_full_quiz_empty_answers(self):
        result = grade_quiz(SAMPLE_QUIZ, [])
        assert result["correct"] == 0
        assert result["total"] == 4
        assert result["score"] == 0.0
        assert result["passed"] is False
        assert all(r["your_index"] is None for r in result["results"])

    def test_missing_answer_key_graded_wrong(self):
        # Item missing the "answer" key must not crash and must be graded wrong.
        quiz = [{"q": "Q1", "options": ["A", "B"]}]
        result = grade_quiz(quiz, [0])
        assert result["correct"] == 0
        assert result["total"] == 1
        assert result["passed"] is False
        assert result["results"][0]["answer_index"] is None
        assert result["results"][0]["correct"] is False

    def test_missing_optional_keys_use_defaults(self):
        # Missing q/options/explain default to "" / [] / "" without crashing.
        quiz = [{"answer": 0}]
        result = grade_quiz(quiz, [0])
        assert result["correct"] == 1
        assert result["results"][0]["q"] == ""
        assert result["results"][0]["options"] == []
        assert result["results"][0]["explain"] == ""

    def test_none_answer_with_none_your_index_is_wrong(self):
        # answer=None and a missing submission must NOT be treated as a match.
        quiz = [{"q": "Q1", "options": ["A"], "answer": None}]
        result = grade_quiz(quiz, [])  # your_index = None
        assert result["correct"] == 0
        assert result["results"][0]["correct"] is False


def _chapter(section_id: str, title: str, quiz: list):
    """Duck-typed stand-in for a Chapter ORM row (attribute access only)."""
    return SimpleNamespace(section_id=section_id, title=title, quiz=quiz)


class TestGradeCourseQuizzes:
    """Test grade_course_quizzes aggregation across multiple chapters."""

    def test_aggregates_across_sections(self):
        chapters = [
            _chapter("s1", "Section 1", SAMPLE_QUIZ),
            _chapter("s2", "Section 2", SAMPLE_QUIZ),
        ]
        result = grade_course_quizzes(chapters, {"s1": [0, 1, 2, 3], "s2": [0, 0, 0, 0]})
        assert result["correct"] == 5  # 4/4 + 1/4
        assert result["total"] == 8
        assert result["score"] == pytest.approx(0.625)
        assert result["passed"] is False
        assert [s["section_id"] for s in result["sections"]] == ["s1", "s2"]
        assert result["sections"][0]["correct"] == 4
        assert result["sections"][1]["correct"] == 1

    def test_skips_chapters_without_quiz(self):
        chapters = [
            _chapter("s1", "Section 1", SAMPLE_QUIZ),
            _chapter("s2", "No Quiz", []),
        ]
        result = grade_course_quizzes(chapters, {"s1": [0, 1, 2, 3]})
        assert result["total"] == 4
        assert len(result["sections"]) == 1
        assert result["sections"][0]["section_id"] == "s1"

    def test_missing_section_in_answers_graded_all_wrong(self):
        chapters = [_chapter("s1", "Section 1", SAMPLE_QUIZ)]
        result = grade_course_quizzes(chapters, {})
        assert result["correct"] == 0
        assert result["total"] == 4
        assert result["passed"] is False

    def test_no_chapters_have_quiz_returns_zero(self):
        chapters = [_chapter("s1", "No Quiz", [])]
        result = grade_course_quizzes(chapters, {"s1": [0]})
        assert result["correct"] == 0
        assert result["total"] == 0
        assert result["score"] == 0.0
        assert result["passed"] is False
        assert result["sections"] == []
