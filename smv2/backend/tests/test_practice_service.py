from __future__ import annotations

import uuid

import pytest

from app.db.engine import get_session
from app.db.models import (
    Concept,
    Course,
    Job,
    LearnerEvidenceEvent,
    PracticeAnswer,
    PracticeExtractionRun,
    PracticeQuestion,
    Section,
)
from app.jobs.error_envelope import encode_job_error
from app.services import practice_service


def seed_ready_practice_question(correct_index=0) -> tuple[str, str]:
    session = get_session()
    try:
        course = Course(title="Practice Course")
        session.add(course)
        session.flush()

        practice = Section(
            id=f"practice-{uuid.uuid4()}",
            course_id=course.id,
            order_index=1,
            title="0.2 Practice - Fractions",
            body_md="1. Simplify 42/12.",
            content_hash="practice-hash",
            kind="practice",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        session.add(practice)
        session.flush()

        concept = Concept(
            course_id=course.id,
            slug="fractions.simplify",
            label="Simplifying Fractions",
            chapter_label=practice.chapter_label,
            section_id=practice.id,
        )
        session.add(concept)
        session.flush()

        question = PracticeQuestion(
            course_id=course.id,
            chapter_label=practice.chapter_label,
            section_id=practice.id,
            concept_id=concept.id,
            problem_number="1",
            source_ref="0.2 Practice - Fractions #1",
            stem_md="Simplify $42/12$.",
            choices=["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
            correct_index=correct_index,
            explanation_md="$42/12 = 7/2$.",
            source_fingerprint="fingerprint-1",
            extraction_version="v3",
            confidence=0.99,
            status="ready",
        )
        session.add(question)
        session.commit()
        return question.id, course.id
    finally:
        session.close()


def seed_two_ready_practice_questions_same_concept() -> tuple[str, str, str]:
    session = get_session()
    try:
        course = Course(title="Practice Course")
        session.add(course)
        session.flush()

        practice = Section(
            id=f"practice-{uuid.uuid4()}",
            course_id=course.id,
            order_index=1,
            title="0.2 Practice - Fractions",
            body_md="1. Simplify 42/12.\n2. Simplify 6/3.",
            content_hash="practice-hash",
            kind="practice",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        session.add(practice)
        session.flush()

        concept = Concept(
            course_id=course.id,
            slug="fractions.simplify",
            label="Simplifying Fractions",
            chapter_label=practice.chapter_label,
            section_id=practice.id,
        )
        session.add(concept)
        session.flush()

        first = PracticeQuestion(
            course_id=course.id,
            chapter_label=practice.chapter_label,
            section_id=practice.id,
            concept_id=concept.id,
            problem_number="1",
            source_ref="0.2 Practice - Fractions #1",
            stem_md="Simplify $42/12$.",
            choices=["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
            correct_index=0,
            explanation_md="$42/12 = 7/2$.",
            source_fingerprint="fingerprint-1",
            extraction_version="v3",
            confidence=0.99,
            status="ready",
        )
        second = PracticeQuestion(
            course_id=course.id,
            chapter_label=practice.chapter_label,
            section_id=practice.id,
            concept_id=concept.id,
            problem_number="2",
            source_ref="0.2 Practice - Fractions #2",
            stem_md="Simplify $6/3$.",
            choices=["2", "3", "6", "9"],
            correct_index=0,
            explanation_md="$6/3 = 2$.",
            source_fingerprint="fingerprint-2",
            extraction_version="v3",
            confidence=0.99,
            status="ready",
        )
        session.add_all([first, second])
        session.commit()
        return first.id, second.id, course.id
    finally:
        session.close()


def seed_practice_run(
    *,
    run_status: str = "queued",
    job_status: str = "queued",
    job_error: str | None = None,
    run_error: str | None = None,
) -> tuple[str, str]:
    session = get_session()
    try:
        course = Course(title="Practice Course")
        session.add(course)
        session.flush()

        practice = Section(
            id=f"practice-{uuid.uuid4()}",
            course_id=course.id,
            order_index=1,
            title="0.2 Practice - Fractions",
            body_md="1. Simplify 42/12.",
            content_hash="practice-hash",
            kind="practice",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        session.add(practice)
        session.flush()

        job = Job(
            type="generate_practice_assessment",
            status=job_status,
            payload={"course_id": course.id, "section_id": practice.id},
            error=job_error,
        )
        session.add(job)
        session.flush()
        run = PracticeExtractionRun(
            course_id=course.id,
            section_id=practice.id,
            status=run_status,
            job_id=job.id,
            input_fingerprint="fingerprint",
            error=run_error,
        )
        session.add(run)
        session.commit()
        return course.id, practice.id
    finally:
        session.close()


def test_submit_wrong_answer_records_evidence_without_legacy_mastery(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    result = practice_service.submit_answer(course_id, question_id, "learner-1", 1)

    assert result["question_id"] == question_id
    assert result["selected_index"] == 1
    assert result["correct"] is False
    assert result["correct_index"] == 0
    assert result["readiness_estimate"] is None
    assert result["evidence_state"] == "insufficient_evidence"
    assert result["evidence_count"] == 0
    assert "points_delta" not in result
    assert "mastery_points" not in result
    assert result["already_answered"] is False

    session = get_session()
    try:
        assert session.query(PracticeAnswer).count() == 1
        event = session.query(LearnerEvidenceEvent).one()
        assert event.channel == "practice"
        assert event.normalized_outcome == 0.0
    finally:
        session.close()


def test_submit_correct_answer_records_positive_evidence(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    result = practice_service.submit_answer(course_id, question_id, "learner-1", 0)

    assert result["correct"] is True
    assert result["readiness_estimate"] is None
    assert result["evidence_state"] == "insufficient_evidence"
    assert result["evidence_count"] == 0
    assert result["already_answered"] is False

    session = get_session()
    try:
        assert session.query(PracticeAnswer).count() == 1
        event = session.query(LearnerEvidenceEvent).one()
        assert event.channel == "practice"
        assert event.normalized_outcome == 1.0
    finally:
        session.close()


def test_duplicate_submit_returns_original_result_without_second_evidence_event(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    practice_service.submit_answer(course_id, question_id, "learner-1", 1)
    result = practice_service.submit_answer(course_id, question_id, "learner-1", 0)

    assert result["selected_index"] == 1
    assert result["correct"] is False
    assert result["already_answered"] is True
    assert result["evidence_state"] == "insufficient_evidence"

    session = get_session()
    try:
        assert session.query(PracticeAnswer).count() == 1
        assert session.query(LearnerEvidenceEvent).count() == 1
    finally:
        session.close()


def test_two_answers_append_independent_evidence_events(client):
    (
        first_question_id,
        second_question_id,
        course_id,
    ) = seed_two_ready_practice_questions_same_concept()
    learner_key = "learner-1"
    practice_service.submit_answer(course_id, first_question_id, learner_key, 0)

    result = practice_service.submit_answer(course_id, second_question_id, learner_key, 0)

    assert result["question_id"] == second_question_id
    assert result["correct"] is True
    assert result["already_answered"] is False

    session = get_session()
    try:
        assert session.query(PracticeAnswer).count() == 2
        events = session.query(LearnerEvidenceEvent).order_by(LearnerEvidenceEvent.created_at).all()
        assert len(events) == 2
        assert {event.attempt_id for event in events} == {
            answer.id for answer in session.query(PracticeAnswer).all()
        }
    finally:
        session.close()


def test_submit_answer_rejects_out_of_range_choice(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    with pytest.raises(practice_service.InvalidChoiceError):
        practice_service.submit_answer(course_id, question_id, "learner-1", 4)


def test_submit_answer_rejects_boolean_choice(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    with pytest.raises(practice_service.InvalidChoiceError):
        practice_service.submit_answer(course_id, question_id, "learner-1", True)


def test_submit_answer_rejects_cross_course_question(client):
    question_id, _course_id = seed_ready_practice_question(correct_index=0)
    session = get_session()
    try:
        other_course = Course(title="Other Course")
        session.add(other_course)
        session.commit()
        other_course_id = other_course.id
    finally:
        session.close()

    with pytest.raises(practice_service.PracticeQuestionNotFoundError):
        practice_service.submit_answer(other_course_id, question_id, "learner-1", 0)


def test_failed_practice_assessment_exposes_safe_structured_error_detail(client):
    course_id, section_id = seed_practice_run(
        job_status="failed",
        job_error=encode_job_error(
            "The model returned an invalid question format.",
            {
                "code": "invalid_model_output",
                "message": "The model returned an invalid question format.",
                "failure_category": "structured_output_invalid",
            },
        ),
    )

    status_code, body = practice_service.get_assessment(course_id, section_id, None)

    assert status_code == 200
    assert body["status"] == "failed"
    assert body["message"] == "Practice question extraction failed."
    assert body["error_detail"] == {
        "code": "invalid_model_output",
        "message": "The model returned an invalid question format.",
        "failure_category": "structured_output_invalid",
    }


def test_legacy_failed_practice_assessment_has_no_error_detail(client):
    course_id, section_id = seed_practice_run(
        run_status="failed",
        job_status="failed",
        job_error="Expecting value: line 1 column 1 (char 0)",
        run_error="raw extraction parser trace",
    )

    status_code, body = practice_service.get_assessment(course_id, section_id, None)

    assert status_code == 200
    assert body["status"] == "failed"
    assert body["message"] == "Practice question extraction failed."
    assert body["error_detail"] is None


def test_generating_practice_assessment_has_no_error_detail(client):
    course_id, section_id = seed_practice_run()

    status_code, body = practice_service.get_assessment(course_id, section_id, None)

    assert status_code == 202
    assert body["status"] == "generating"
    assert body["error_detail"] is None
