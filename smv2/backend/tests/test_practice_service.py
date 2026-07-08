from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptMastery,
    ConceptMasteryEvent,
    Course,
    PracticeAnswer,
    PracticeQuestion,
    Section,
)
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


def test_submit_wrong_answer_records_negative_mastery(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    result = practice_service.submit_answer(course_id, question_id, "learner-1", 1)

    assert result["question_id"] == question_id
    assert result["selected_index"] == 1
    assert result["correct"] is False
    assert result["correct_index"] == 0
    assert result["points_delta"] == -1
    assert result["mastery_points"] == -1
    assert result["already_answered"] is False

    session = get_session()
    try:
        assert session.query(PracticeAnswer).count() == 1
        assert session.query(ConceptMasteryEvent).count() == 1
        mastery = session.query(ConceptMastery).one()
        assert mastery.wrong_count == 1
        assert mastery.correct_count == 0
        assert mastery.points == -1
    finally:
        session.close()


def test_submit_correct_answer_records_positive_mastery(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    result = practice_service.submit_answer(course_id, question_id, "learner-1", 0)

    assert result["correct"] is True
    assert result["points_delta"] == 1
    assert result["mastery_points"] == 1
    assert result["already_answered"] is False

    session = get_session()
    try:
        assert session.query(PracticeAnswer).count() == 1
        assert session.query(ConceptMasteryEvent).count() == 1
        mastery = session.query(ConceptMastery).one()
        assert mastery.correct_count == 1
        assert mastery.wrong_count == 0
        assert mastery.points == 1
    finally:
        session.close()


def test_duplicate_submit_returns_original_result_without_second_delta(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    practice_service.submit_answer(course_id, question_id, "learner-1", 1)
    result = practice_service.submit_answer(course_id, question_id, "learner-1", 0)

    assert result["selected_index"] == 1
    assert result["correct"] is False
    assert result["already_answered"] is True
    assert result["mastery_points"] == -1

    session = get_session()
    try:
        assert session.query(PracticeAnswer).count() == 1
        assert session.query(ConceptMasteryEvent).count() == 1
        mastery = session.query(ConceptMastery).one()
        assert mastery.correct_count == 0
        assert mastery.wrong_count == 1
        assert mastery.points == -1
    finally:
        session.close()


def test_submit_answer_retries_mastery_collision_for_different_question(client, monkeypatch):
    (
        first_question_id,
        second_question_id,
        course_id,
    ) = seed_two_ready_practice_questions_same_concept()
    learner_key = "learner-1"
    practice_service.submit_answer(course_id, first_question_id, learner_key, 0)

    original_get_mastery = practice_service._get_mastery
    calls = 0

    def collide_once(session, course_id, concept_id, learner_key):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise IntegrityError("concept_masteries collision", params=None, orig=None)
        return original_get_mastery(session, course_id, concept_id, learner_key)

    monkeypatch.setattr(practice_service, "_get_mastery", collide_once)

    result = practice_service.submit_answer(course_id, second_question_id, learner_key, 0)

    assert result["question_id"] == second_question_id
    assert result["correct"] is True
    assert result["points_delta"] == 1
    assert result["mastery_points"] == 2
    assert result["already_answered"] is False
    assert calls == 2

    session = get_session()
    try:
        assert session.query(PracticeAnswer).count() == 2
        assert session.query(ConceptMasteryEvent).count() == 2
        mastery = session.query(ConceptMastery).one()
        assert mastery.correct_count == 2
        assert mastery.wrong_count == 0
        assert mastery.points == 2
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
