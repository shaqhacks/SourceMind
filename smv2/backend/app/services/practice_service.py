"""Lazy practice assessment state and job creation.

Routers own HTTP details; this module owns all database decisions for the
practice assessment lifecycle.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.db.models import (
    Concept,
    CurriculumVersion,
    Job,
    LearnerConceptState,
    PracticeAnswer,
    PracticeExtractionRun,
    PracticeQuestion,
    Section,
)
from app.services import evidence_items_service, evidence_service, learner_context
from app.services.jobs_service import create_job_in_session

EXTRACTION_VERSION = "v3"
LEARNER_COOKIE = learner_context.LEARNER_COOKIE

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
    session: Session, questions: list[PracticeQuestion], learner_key: str | None
) -> list[dict[str, Any]]:
    concept_ids = {question.concept_id for question in questions}
    concepts = {
        concept.id: concept
        for concept in session.query(Concept).filter(Concept.id.in_(concept_ids)).all()
    }
    answers: dict[str, PracticeAnswer] = {}
    learner_states: dict[str, LearnerConceptState] = {}
    if learner_key is not None:
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
        profile = learner_context.ensure_course_learning_profile(
            session, learner_key, questions[0].course_id
        )
        current_version_id = session.query(CurriculumVersion.id).filter_by(
            course_id=questions[0].course_id, is_current=True
        ).scalar()
        if current_version_id is not None:
            learner_states = {
                state.concept_id: state
                for state in session.query(LearnerConceptState).filter(
                    LearnerConceptState.course_learning_profile_id == profile.id,
                    LearnerConceptState.curriculum_version_id == current_version_id,
                    LearnerConceptState.state_scope == "concept",
                    LearnerConceptState.concept_id.in_(concept_ids),
                    LearnerConceptState.model_version == "transparent-beta-v1",
                )
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
                **_state_payload(learner_states.get(question.concept_id)),
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


def _state_payload(state: LearnerConceptState | None) -> dict[str, Any]:
    return {
        "readiness_estimate": state.readiness_estimate if state is not None else None,
        "evidence_state": state.status if state is not None else "insufficient_evidence",
        "evidence_count": state.distinct_item_count if state is not None else 0,
    }


def _concept_state(
    session: Session, course_profile_id: str, course_id: str, concept_id: str
) -> LearnerConceptState | None:
    version_id = session.query(CurriculumVersion.id).filter_by(
        course_id=course_id, is_current=True
    ).scalar()
    if version_id is None:
        return None
    return session.query(LearnerConceptState).filter_by(
        course_learning_profile_id=course_profile_id,
        curriculum_version_id=version_id,
        concept_id=concept_id,
        state_scope="concept",
        model_version="transparent-beta-v1",
    ).one_or_none()


def _answer_payload(
    session: Session,
    question: PracticeQuestion,
    answer: PracticeAnswer,
    course_profile_id: str,
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
        **_state_payload(
            _concept_state(
                session,
                course_profile_id,
                question.course_id,
                question.concept_id,
            )
        ),
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

    profile = learner_context.ensure_course_learning_profile(
        session, learner_key, question.course_id
    )
    return _answer_payload(
        session,
        question,
        answer,
        profile.id,
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

                course_profile = learner_context.ensure_course_learning_profile(
                    session, learner_key, course_id
                )

                if type(selected_index) is not int or not 0 <= selected_index < len(
                    question.choices
                ):
                    raise InvalidChoiceError("selected_index is out of range")

                existing = _load_existing_answer_payload(session, question, learner_key)
                if existing is not None:
                    return existing

                correct = selected_index == question.correct_index
                answer = PracticeAnswer(
                    course_id=course_id,
                    question_id=question.id,
                    learner_key=learner_key,
                    selected_index=selected_index,
                    correct=correct,
                    points_delta=0,
                )
                session.add(answer)
                session.flush()

                evidence_item = evidence_service.find_item(
                    session,
                    item_type="practice_question",
                    source_record_id=question.id,
                )
                if evidence_item is None:
                    evidence_item = evidence_items_service.snapshot_item(
                        session,
                        course_id=course_id,
                        item_type="practice_question",
                        source_record_id=question.id,
                        source_index=-1,
                        content={
                            "stem_md": question.stem_md,
                            "choices": question.choices,
                            "correct_index": question.correct_index,
                            "explanation_md": question.explanation_md,
                        },
                        source_ref=question.source_ref,
                        prompt_version=question.extraction_version,
                        model=None,
                    )
                evidence_service.record_event(
                    session,
                    course_learning_profile_id=course_profile.id,
                    evidence_item=evidence_item,
                    channel="practice",
                    normalized_outcome=1.0 if correct else 0.0,
                    raw_result={
                        "correct": correct,
                        "selected_index": selected_index,
                        "correct_index": question.correct_index,
                    },
                    source_event_key=f"practice_answer:{answer.id}",
                    event_at=answer.answered_at,
                    attempt_id=answer.id,
                )
                session.commit()
                return _answer_payload(
                    session,
                    question,
                    answer,
                    course_profile.id,
                    already_answered=False,
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


def get_assessment(
    course_id: str, section_id: str, learner_key: str | None
) -> tuple[int, dict[str, Any]]:
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


def _run_is_retryable(session: Session, run: PracticeExtractionRun) -> bool:
    if run.status == "failed":
        return True
    if run.job_id is None:
        return False
    job = session.get(Job, run.job_id)
    return job is not None and job.status == "failed"


def start_assessment(course_id: str, section_id: str) -> tuple[int, dict[str, Any]]:
    for attempt in range(3):
        session = get_session()
        try:
            section = _load_practice_section(session, course_id, section_id)
            fingerprint = _fingerprint_for(section, _answer_sections(session, section))

            run = _matching_run(session, course_id, section_id, fingerprint)
            if run is not None:
                if _run_is_retryable(session, run):
                    job = create_job_in_session(
                        session,
                        "generate_practice_assessment",
                        {"course_id": course_id, "section_id": section_id, "run_id": run.id},
                    )
                    session.flush()
                    run.status = "queued"
                    run.error = None
                    run.question_count = 0
                    run.job_id = job.id
                    session.commit()
                    return 202, _run_response(run, "generating", GENERATING_MESSAGE)
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
