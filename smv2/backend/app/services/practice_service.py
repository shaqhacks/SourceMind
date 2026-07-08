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
from app.db.models import Concept, Job, PracticeExtractionRun, PracticeQuestion, Section
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
    _ = learner_key
    concept_ids = {question.concept_id for question in questions}
    concepts = {
        concept.id: concept
        for concept in session.query(Concept).filter(Concept.id.in_(concept_ids)).all()
    }
    serialized: list[dict[str, Any]] = []
    for question in questions:
        concept = concepts[question.concept_id]
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
                "answered": None,
            }
        )
    return serialized


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
