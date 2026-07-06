"""Quiz (TestAttempt) generation, retrieval, grading, and listing. Business
logic for generate_test/get_test/submit_test/list_tests — routers only do
existence/state checks and delegate here.

get_test hides correct_index/explanation while the attempt is ungraded
(score is None) — a learner must not be able to peek at answers by reading
the raw attempt before submitting.

ADR-017: submit_test also turns each missed question into a flashcard
(missed -> SRS). See _resolve_missed_card_section_id/_record_missed_card
for the exact policy.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.identity import card_id_for
from app.db.models import Card, Course, ReviewState, Section, TestAttempt, utcnow
from app.services import jobs_service


class CourseNotFoundError(ValueError):
    pass


class ChapterNotFoundError(ValueError):
    pass


class TestAlreadySubmittedError(ValueError):
    pass


def start_test_generation(
    course_id: str,
    section_ids: list[str] | None = None,
    chapter_label: str | None = None,
) -> str:
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            raise CourseNotFoundError(f"course not found: {course_id}")

        resolved_section_ids = section_ids
        if chapter_label is not None:
            # Practice + content sections only — never an answer key (see
            # run_test_generation's whole-course fallback for the same
            # reasoning: a printed answer key in the prompt invites the
            # model to copy its numbering instead of writing real questions).
            resolved_section_ids = [
                s.id
                for s in session.query(Section)
                .filter(
                    Section.course_id == course_id,
                    Section.chapter_label == chapter_label,
                    Section.kind != "answers",
                )
                .order_by(Section.order_index)
                .all()
            ]
            if not resolved_section_ids:
                raise ChapterNotFoundError(
                    f"no practice/content sections found for chapter {chapter_label!r}"
                )
    finally:
        session.close()

    job = jobs_service.create_job(
        "generate_test",
        {"course_id": course_id, "section_ids": resolved_section_ids, "chapter_label": chapter_label},
    )
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
            "chapter_label": attempt.chapter_label,
            "questions": visible_questions,
            "created_at": attempt.created_at,
        }
    finally:
        session.close()


def _resolve_missed_card_section_id(session, attempt: TestAttempt) -> str | None:
    """Where a card created from a missed question in THIS attempt should
    live: the attempt's chapter's first practice section if one exists,
    else that chapter's first section of any kind, else the attempt's own
    (single-section-mode) section_id, else the course's first section —
    always resolving to SOMETHING if the course has any section at all.
    """
    if attempt.chapter_label is not None:
        chapter_sections = (
            session.query(Section)
            .filter(Section.course_id == attempt.course_id, Section.chapter_label == attempt.chapter_label)
            .order_by(Section.order_index)
            .all()
        )
        practice = next((s for s in chapter_sections if s.kind == "practice"), None)
        if practice is not None:
            return practice.id
        if chapter_sections:
            return chapter_sections[0].id

    if attempt.section_id is not None:
        return attempt.section_id

    first_section = (
        session.query(Section)
        .filter(Section.course_id == attempt.course_id)
        .order_by(Section.order_index)
        .first()
    )
    return first_section.id if first_section is not None else None


def _build_missed_card_content(question: dict[str, Any]) -> tuple[str, str]:
    choices_md = "\n".join(f"- {c}" for c in question["choices"])
    front_md = f"{question['question']}\n\n{choices_md}"

    correct_text = question["choices"][question["correct_index"]]
    explanation = (question.get("explanation") or "").strip()
    back_md = f"{correct_text}\n\n{explanation}" if explanation else correct_text
    return front_md, back_md


def _record_missed_card(session, attempt: TestAttempt, section_id: str, question: dict[str, Any]) -> str:
    front_md, back_md = _build_missed_card_content(question)
    card_id = card_id_for(section_id, front_md, back_md)

    card = session.get(Card, card_id)
    if card is None:
        position = session.query(Card).filter(Card.section_id == section_id).count()
        session.add(
            Card(
                id=card_id,
                course_id=attempt.course_id,
                section_id=section_id,
                front_md=front_md,
                back_md=back_md,
                position=position,
            )
        )
        # No ReviewState created here on purpose: a card with no
        # ReviewState row is already picked up as "new" by
        # srs_service.get_review_queue/_due_counts, so it surfaces in the
        # queue immediately without one — same convention card generation
        # itself follows.
        return card_id

    review_state = session.get(ReviewState, card_id)
    if review_state is not None:
        # A miss on a test is evidence the card needs review NOW, not a
        # formal SM-2 lapse — only due_at moves. Leaving ease/interval/reps
        # untouched (rather than replaying schedule_next as if this were an
        # Again grade) keeps the card's real review history intact; a
        # genuine Again grade from the review queue is what should ever
        # reduce ease or count as a lapse.
        review_state.due_at = utcnow()
    # else: the card already existed (from an earlier miss) but was never
    # graded yet — no ReviewState means it's already "new" and due, same
    # as the brand-new-card case above.

    return card_id


def submit_test(attempt_id: str, answers: list[int]) -> dict[str, Any] | None:
    session = get_session()
    try:
        attempt = session.get(TestAttempt, attempt_id)
        if attempt is None:
            return None
        if attempt.score is not None:
            raise TestAlreadySubmittedError(f"test attempt {attempt_id} already submitted")

        questions = attempt.payload.get("questions", [])
        target_section_id = _resolve_missed_card_section_id(session, attempt)

        results = []
        correct_count = 0
        added_card_ids: list[str] = []
        for i, q in enumerate(questions):
            your_answer = answers[i] if i < len(answers) else None
            is_correct = your_answer == q["correct_index"]
            if is_correct:
                correct_count += 1
            elif target_section_id is not None:
                added_card_ids.append(_record_missed_card(session, attempt, target_section_id, q))
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

        return {"score": score, "results": results, "added_card_ids": added_card_ids}
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
                "chapter_label": a.chapter_label,
                "question_count": len(a.payload.get("questions", [])),
                "created_at": a.created_at,
            }
            for a in attempts
        ]
    finally:
        session.close()
