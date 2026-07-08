from __future__ import annotations

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptMastery,
    ConceptMasteryEvent,
    PracticeAnswer,
    PracticeExtractionRun,
    PracticeQuestion,
    Section,
)
from app.jobs.worker import run_due_jobs_once


def test_reingest_removes_practice_assessment_rows(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        section = session.query(Section).filter_by(course_id=course_id).first()
        assert section is not None

        concept = Concept(
            course_id=course_id,
            slug="reingest.concept",
            label="Reingest Concept",
            chapter_label=section.chapter_label,
            section_id=section.id,
        )
        session.add(concept)
        session.flush()

        question = PracticeQuestion(
            course_id=course_id,
            chapter_label=section.chapter_label,
            section_id=section.id,
            concept_id=concept.id,
            problem_number="1",
            source_ref="Practice #1",
            stem_md="2 + 2?",
            choices=["3", "4"],
            correct_index=1,
            explanation_md="2 + 2 = 4.",
            source_fingerprint="reingest-practice-question",
            extraction_version="test",
            confidence=1.0,
        )
        run = PracticeExtractionRun(
            course_id=course_id,
            section_id=section.id,
            input_fingerprint="reingest-practice-run",
            question_count=1,
        )
        session.add_all([question, run])
        session.flush()

        answer = PracticeAnswer(
            course_id=course_id,
            question_id=question.id,
            learner_key="learner",
            selected_index=1,
            correct=True,
            points_delta=1,
        )
        mastery = ConceptMastery(
            course_id=course_id,
            concept_id=concept.id,
            learner_key="learner",
            points=1,
            correct_count=1,
            wrong_count=0,
        )
        session.add_all([answer, mastery])
        session.flush()

        session.add(
            ConceptMasteryEvent(
                course_id=course_id,
                concept_id=concept.id,
                question_id=question.id,
                practice_answer_id=answer.id,
                learner_key="learner",
                delta=1,
            )
        )
        session.commit()
    finally:
        session.close()

    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True

    session = get_session()
    try:
        assert session.query(PracticeAnswer).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptMasteryEvent).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptMastery).filter_by(course_id=course_id).count() == 0
        assert session.query(PracticeQuestion).filter_by(course_id=course_id).count() == 0
        assert session.query(PracticeExtractionRun).filter_by(course_id=course_id).count() == 0
        assert session.query(Concept).filter_by(course_id=course_id).count() == 0
    finally:
        session.close()
