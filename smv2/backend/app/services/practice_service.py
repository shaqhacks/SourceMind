"""Lazy practice assessment state and job creation.

Routers own HTTP details; this module owns all database decisions for the
practice assessment lifecycle.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptMastery,
    ConceptMasteryEvent,
    Job,
    PracticeAnswer,
    PracticeExtractionRun,
    PracticeQuestion,
    Section,
    utcnow,
)
from app.services.jobs_service import create_job_in_session

EXTRACTION_VERSION = "v3"
LEARNER_COOKIE = "smv2_learner"

GENERATING_MESSAGE = "Practice questions are being extracted from the textbook."
NOT_STARTED_MESSAGE = "Practice questions have not been extracted yet."
FAILED_MESSAGE = "Practice question extraction failed."


class SectionNotFoundError(ValueError):
    pass


class NotPracticeSectionError(ValueError):
    pass


class PracticeQuestionNotFoundError(ValueError):
    pass


class InvalidChoiceError(ValueError):
    pass


def _load_practice_section(session: Session, course_id: str, section_id: str) -> Section:
    section = session.get(Section, section_id)
    if section is None or section.course_id != course_id:
        raise SectionNotFoundError("section not found")
    if section.kind != "practice":
        raise NotPracticeSectionError("section is not a practice section")
    return section


def _answer_sections(session: Session, section: Section) -> list[Section]:
    return (
        session.query(Section)
        .filter(
            Section.course_id == section.course_id,
            Section.kind == "answers",
            Section.chapter_label == section.chapter_label,
        )
        .order_by(Section.order_index)
        .all()
    )


def _fingerprint_for(section: Section, answer_sections: list[Section]) -> str:
    digest = hashlib.sha256()
    digest.update(section.id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(section.content_hash.encode("utf-8"))
    digest.update(b"\0")
    digest.update(EXTRACTION_VERSION.encode("utf-8"))
    for answer_section in answer_sections:
        digest.update(b"\0")
        digest.update(answer_section.id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(answer_section.content_hash.encode("utf-8"))
    return digest.hexdigest()


def _serialize_questions(
    session: Session, questions: list[PracticeQuestion], learner_key: str
) -> list[dict[str, Any]]:
    concept_ids = {question.concept_id for question in questions}
    concepts = {
        concept.id: concept
        for concept in session.query(Concept).filter(Concept.id.in_(concept_ids)).all()
    }
    question_ids = [question.id for question in questions]
    answers = {
        answer.question_id: answer
        for answer in session.query(PracticeAnswer)
        .filter(
            PracticeAnswer.learner_key == learner_key,
            PracticeAnswer.question_id.in_(question_ids),
        )
        .all()
    }
    mastery_points = {
        mastery.concept_id: mastery.points
        for mastery in session.query(ConceptMastery)
        .filter(
            ConceptMastery.learner_key == learner_key,
            ConceptMastery.concept_id.in_(concept_ids),
        )
        .all()
    }
    serialized: list[dict[str, Any]] = []
    for question in questions:
        concept = concepts[question.concept_id]
        answer = answers.get(question.id)
        answered = None
        if answer is not None:
            answered = {
                "selected_index": answer.selected_index,
                "correct": answer.correct,
                "correct_index": question.correct_index,
                "explanation_md": question.explanation_md,
                "points_delta": answer.points_delta,
                "mastery_points": mastery_points.get(question.concept_id, 0),
                "answered_at": answer.answered_at,
            }
        serialized.append(
            {
                "id": question.id,
                "problem_number": question.problem_number,
                "source_ref": question.source_ref,
                "stem_md": question.stem_md,
                "choices": question.choices,
                "concept": {
                    "id": concept.id,
                    "slug": concept.slug,
                    "label": concept.label,
                },
                "answered": answered,
            }
        )
    return serialized


def _get_mastery(
    session: Session, course_id: str, concept_id: str, learner_key: str
) -> ConceptMastery:
    mastery = session.get(ConceptMastery, (course_id, concept_id, learner_key))
    if mastery is not None:
        return mastery

    mastery = ConceptMastery(
        course_id=course_id,
        concept_id=concept_id,
        learner_key=learner_key,
        points=0,
        correct_count=0,
        wrong_count=0,
    )
    session.add(mastery)
    session.flush()
    return mastery


def _apply_mastery_delta(
    session: Session,
    course_id: str,
    concept_id: str,
    learner_key: str,
    delta: int,
    correct: bool,
) -> ConceptMastery:
    mastery = _get_mastery(session, course_id, concept_id, learner_key)
    session.execute(
        update(ConceptMastery)
        .where(
            ConceptMastery.course_id == course_id,
            ConceptMastery.concept_id == concept_id,
            ConceptMastery.learner_key == learner_key,
        )
        .values(
            points=ConceptMastery.points + delta,
            correct_count=ConceptMastery.correct_count + (1 if correct else 0),
            wrong_count=ConceptMastery.wrong_count + (0 if correct else 1),
            updated_at=utcnow(),
        )
        .execution_options(synchronize_session=False)
    )
    session.refresh(mastery)
    return mastery


def _answer_payload(
    session: Session,
    question: PracticeQuestion,
    answer: PracticeAnswer,
    mastery_points: int,
    already_answered: bool,
) -> dict[str, Any]:
    concept = session.get(Concept, question.concept_id)
    if concept is None:
        raise PracticeQuestionNotFoundError("practice question not found")
    return {
        "question_id": question.id,
        "selected_index": answer.selected_index,
        "correct": answer.correct,
        "correct_index": question.correct_index,
        "explanation_md": question.explanation_md,
        "concept": {
            "id": concept.id,
            "slug": concept.slug,
            "label": concept.label,
        },
        "points_delta": answer.points_delta,
        "mastery_points": mastery_points,
        "already_answered": already_answered,
    }


def _load_existing_answer_payload(
    session: Session, question: PracticeQuestion, learner_key: str
) -> dict[str, Any] | None:
    answer = (
        session.query(PracticeAnswer)
        .filter(
            PracticeAnswer.learner_key == learner_key,
            PracticeAnswer.question_id == question.id,
        )
        .one_or_none()
    )
    if answer is None:
        return None

    mastery = session.get(ConceptMastery, (question.course_id, question.concept_id, learner_key))
    return _answer_payload(
        session,
        question,
        answer,
        mastery.points if mastery is not None else 0,
        already_answered=True,
    )


def submit_answer(
    course_id: str, question_id: str, learner_key: str, selected_index: int
) -> dict[str, Any]:
    session = get_session()
    try:
        for attempt in range(2):
            try:
                question = (
                    session.query(PracticeQuestion)
                    .filter(
                        PracticeQuestion.id == question_id,
                        PracticeQuestion.course_id == course_id,
                    )
                    .one_or_none()
                )
                if question is None:
                    raise PracticeQuestionNotFoundError("practice question not found")

                if type(selected_index) is not int or not 0 <= selected_index < len(
                    question.choices
                ):
                    raise InvalidChoiceError("selected_index is out of range")

                existing = _load_existing_answer_payload(session, question, learner_key)
                if existing is not None:
                    return existing

                correct = selected_index == question.correct_index
                delta = 1 if correct else -1
                answer = PracticeAnswer(
                    course_id=course_id,
                    question_id=question.id,
                    learner_key=learner_key,
                    selected_index=selected_index,
                    correct=correct,
                    points_delta=delta,
                )
                session.add(answer)
                session.flush()

                mastery = _apply_mastery_delta(
                    session,
                    course_id,
                    question.concept_id,
                    learner_key,
                    delta,
                    correct,
                )

                session.add(
                    ConceptMasteryEvent(
                        course_id=course_id,
                        concept_id=question.concept_id,
                        question_id=question.id,
                        practice_answer_id=answer.id,
                        learner_key=learner_key,
                        delta=delta,
                    )
                )
                session.commit()
                return _answer_payload(
                    session, question, answer, mastery.points, already_answered=False
                )
            except IntegrityError:
                session.rollback()
                question = (
                    session.query(PracticeQuestion)
                    .filter(
                        PracticeQuestion.id == question_id,
                        PracticeQuestion.course_id == course_id,
                    )
                    .one_or_none()
                )
                if question is None:
                    raise PracticeQuestionNotFoundError("practice question not found")
                existing = _load_existing_answer_payload(session, question, learner_key)
                if existing is not None:
                    return existing
                if attempt == 1:
                    raise
        raise RuntimeError("unreachable practice answer retry state")
    finally:
        session.close()


def _ready_questions(session: Session, course_id: str, section_id: str) -> list[PracticeQuestion]:
    return (
        session.query(PracticeQuestion)
        .filter(
            PracticeQuestion.course_id == course_id,
            PracticeQuestion.section_id == section_id,
            PracticeQuestion.status == "ready",
        )
        .order_by(PracticeQuestion.problem_number, PracticeQuestion.created_at)
        .all()
    )


def _latest_run(session: Session, course_id: str, section_id: str) -> PracticeExtractionRun | None:
    return (
        session.query(PracticeExtractionRun)
        .filter(
            PracticeExtractionRun.course_id == course_id,
            PracticeExtractionRun.section_id == section_id,
        )
        .order_by(PracticeExtractionRun.created_at.desc())
        .first()
    )


def _run_response(run: PracticeExtractionRun, status: str, message: str) -> dict[str, Any]:
    return {
        "status": status,
        "section_id": run.section_id,
        "questions": [],
        "run_id": run.id,
        "job_id": run.job_id,
        "message": message,
    }


def get_assessment(course_id: str, section_id: str, learner_key: str) -> tuple[int, dict[str, Any]]:
    session = get_session()
    try:
        section = _load_practice_section(session, course_id, section_id)

        questions = _ready_questions(session, course_id, section_id)
        if questions:
            return 200, {
                "status": "ready",
                "section_id": section.id,
                "questions": _serialize_questions(session, questions, learner_key),
                "run_id": None,
                "job_id": None,
                "message": None,
            }

        run = _latest_run(session, course_id, section_id)
        if run is None:
            return 200, {
                "status": "not_started",
                "section_id": section.id,
                "questions": [],
                "run_id": None,
                "job_id": None,
                "message": NOT_STARTED_MESSAGE,
            }

        if run.status == "failed":
            return 200, _run_response(run, "failed", FAILED_MESSAGE)

        if run.job_id is not None:
            job = session.get(Job, run.job_id)
            if job is not None and job.status == "failed":
                run.status = "failed"
                run.error = job.error
                session.commit()
                return 200, _run_response(run, "failed", FAILED_MESSAGE)

        return 202, _run_response(run, "generating", GENERATING_MESSAGE)
    finally:
        session.close()


def _matching_run(
    session: Session, course_id: str, section_id: str, fingerprint: str
) -> PracticeExtractionRun | None:
    return (
        session.query(PracticeExtractionRun)
        .filter(
            PracticeExtractionRun.course_id == course_id,
            PracticeExtractionRun.section_id == section_id,
            PracticeExtractionRun.input_fingerprint == fingerprint,
        )
        .one_or_none()
    )


def start_assessment(course_id: str, section_id: str) -> tuple[int, dict[str, Any]]:
    for attempt in range(3):
        session = get_session()
        try:
            section = _load_practice_section(session, course_id, section_id)
            fingerprint = _fingerprint_for(section, _answer_sections(session, section))

            run = _matching_run(session, course_id, section_id, fingerprint)
            if run is not None:
                if run.status == "failed":
                    return 200, _run_response(run, "failed", FAILED_MESSAGE)
                return 202, _run_response(run, "generating", GENERATING_MESSAGE)

            run = PracticeExtractionRun(
                course_id=course_id,
                section_id=section_id,
                status="queued",
                input_fingerprint=fingerprint,
            )
            session.add(run)
            session.flush()
            job = create_job_in_session(
                session,
                "generate_practice_assessment",
                {"course_id": course_id, "section_id": section_id, "run_id": run.id},
            )
            session.flush()
            run.job_id = job.id
            session.commit()
            return 202, _run_response(run, "generating", GENERATING_MESSAGE)
        except IntegrityError:
            session.rollback()
            if attempt == 2:
                raise
        finally:
            session.close()

    raise RuntimeError("unreachable practice assessment retry state")
