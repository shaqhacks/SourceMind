"""Pure grading logic for SourceMind test mode."""
from __future__ import annotations

import os


def _read_pass_threshold() -> float:
    """Read the pass threshold from env, falling back to 0.7 on bad input.

    Evaluated at import time; tests should monkeypatch grading.PASS_THRESHOLD
    directly rather than the env var.
    """
    raw = os.environ.get("SOURCEMIND_TEST_PASS_THRESHOLD", "0.7")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.7


PASS_THRESHOLD: float = _read_pass_threshold()


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
        your_index = answers[i] if i < len(answers) else None
        answer_index = item.get("answer")
        # A missing/None correct-answer key is ungradeable -> always wrong.
        is_correct = answer_index is not None and your_index == answer_index
        if is_correct:
            correct += 1
        results.append({
            "q": item.get("q", ""),
            "options": item.get("options", []),
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


def grade_course_quizzes(chapters: list, answers: dict[str, list[int]]) -> dict:
    """Grade a course-level test across every chapter that has a quiz.

    Parameters
    ----------
    chapters:
        Chapter-like objects (ORM rows or any duck-typed equivalent) with
        ``section_id``, ``title``, and ``quiz`` attributes. Chapters with a
        falsy ``quiz`` are skipped entirely.
    answers:
        ``{section_id: [answer_index, ...]}``. A chapter whose section_id is
        absent from *answers* is graded with an empty answers list (all wrong).

    Returns
    -------
    dict with keys:
        score, correct, total, passed — aggregated across all graded chapters.
        sections — list of per-chapter {section_id, title, score, correct,
                    total, passed}, in the same order as *chapters*.
    """
    section_results = []
    total_correct = 0
    total_questions = 0
    for ch in chapters:
        if not ch.quiz:
            continue
        result = grade_quiz(ch.quiz, answers.get(ch.section_id, []))
        total_correct += result["correct"]
        total_questions += result["total"]
        section_results.append({
            "section_id": ch.section_id,
            "title": ch.title,
            "score": result["score"],
            "correct": result["correct"],
            "total": result["total"],
            "passed": result["passed"],
        })

    agg_score = total_correct / total_questions if total_questions > 0 else 0.0
    return {
        "score": agg_score,
        "correct": total_correct,
        "total": total_questions,
        "passed": agg_score >= PASS_THRESHOLD,
        "sections": section_results,
    }
