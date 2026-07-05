"""Quiz (TestAttempt) generation, retrieval, grading, and listing. Business
logic for generate_test/get_test/submit_test/list_tests — routers only do
existence/state checks and delegate here.

get_test hides correct_index/explanation while the attempt is ungraded
(score is None) — a learner must not be able to peek at answers by reading
the raw attempt before submitting.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import Course, TestAttempt
from app.services import jobs_service


class CourseNotFoundError(ValueError):
    pass


class TestAttemptNotFoundError(ValueError):
    pass


class TestAlreadySubmittedError(ValueError):
    pass


def start_test_generation(course_id: str, section_ids: list[str] | None = None) -> str:
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            raise CourseNotFoundError(f"course not found: {course_id}")
    finally:
        session.close()

    job = jobs_service.create_job("generate_test", {"course_id": course_id, "section_ids": section_ids})
    return job.id


def get_test(attempt_id: str) -> dict[str, Any] | None:
    session = get_session()
    try:
        attempt = session.get(TestAttempt, attempt_id)
        if attempt is None:
            return None

        questions = attempt.payload.get("questions", [])
        if attempt.score is None:
            visible_questions = [{"question": q["question"], "choices": q["choices"]} for q in questions]
        else:
            visible_questions = questions

        return {
            "id": attempt.id,
            "course_id": attempt.course_id,
            "score": attempt.score,
            "questions": visible_questions,
            "created_at": attempt.created_at,
        }
    finally:
        session.close()


def submit_test(attempt_id: str, answers: list[int]) -> dict[str, Any] | None:
    session = get_session()
    try:
        attempt = session.get(TestAttempt, attempt_id)
        if attempt is None:
            return None
        if attempt.score is not None:
            raise TestAlreadySubmittedError(f"test attempt {attempt_id} already submitted")

        questions = attempt.payload.get("questions", [])
        results = []
        correct_count = 0
        for i, q in enumerate(questions):
            your_answer = answers[i] if i < len(answers) else None
            is_correct = your_answer == q["correct_index"]
            if is_correct:
                correct_count += 1
            results.append(
                {
                    "correct": is_correct,
                    "correct_index": q["correct_index"],
                    "explanation": q.get("explanation", ""),
                    "your_answer": your_answer,
                }
            )

        score = correct_count / len(questions) if questions else 0.0
        attempt.score = score
        session.commit()

        return {"score": score, "results": results}
    finally:
        session.close()


def list_tests(course_id: str) -> list[dict[str, Any]]:
    session = get_session()
    try:
        attempts = (
            session.query(TestAttempt)
            .filter(TestAttempt.course_id == course_id)
            .order_by(TestAttempt.created_at.desc())
            .all()
        )
        return [
            {
                "id": a.id,
                "course_id": a.course_id,
                "score": a.score,
                "question_count": len(a.payload.get("questions", [])),
                "created_at": a.created_at,
            }
            for a in attempts
        ]
    finally:
        session.close()
