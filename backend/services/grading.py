"""Pure grading logic for SourceMind test mode."""
from __future__ import annotations

import os

PASS_THRESHOLD: float = float(os.environ.get("SOURCEMIND_TEST_PASS_THRESHOLD", "0.7"))


def grade_quiz(quiz: list[dict], answers: list[int]) -> dict:
    """Grade *answers* against *quiz* and return a full result dict.

    Parameters
    ----------
    quiz:
        List of quiz items, each with keys ``q``, ``options``, ``answer``
        (0-based correct index), and ``explain``.
    answers:
        List of 0-based selected indices, one per quiz item.  Missing
        answers (list shorter than quiz) are treated as wrong; extra
        answers (list longer than quiz) are ignored.

    Returns
    -------
    dict with keys:
        correct  – number of correct answers (int)
        total    – number of quiz items (int)
        score    – correct/total, or 0.0 when total == 0 (float)
        passed   – score >= PASS_THRESHOLD (bool)
        results  – list of per-item dicts, each with:
                     q, options, your_index, answer_index, correct (bool), explain
    """
    total = len(quiz)
    correct = 0
    results = []
    for i, item in enumerate(quiz):
        your_index: int | None = answers[i] if i < len(answers) else None
        answer_index: int = item["answer"]
        is_correct = your_index == answer_index
        if is_correct:
            correct += 1
        results.append({
            "q": item["q"],
            "options": item["options"],
            "your_index": your_index,
            "answer_index": answer_index,
            "correct": is_correct,
            "explain": item.get("explain", ""),
        })
    score = correct / total if total > 0 else 0.0
    return {
        "correct": correct,
        "total": total,
        "score": score,
        "passed": score >= PASS_THRESHOLD,
        "results": results,
    }
