"""Pure unit tests for backend/services/grading.py."""
from __future__ import annotations

import pytest

from SourceMind.backend.services.grading import PASS_THRESHOLD, grade_quiz

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
