from __future__ import annotations

import uuid

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptMastery,
    ConceptMasteryEvent,
    Course,
    PracticeAnswer,
    PracticeExtractionRun,
    PracticeQuestion,
    Section,
)
from app.db.registry import REMAPPED_ON_REINGEST, REPLACED_ON_REINGEST


def test_practice_models_are_registered_for_reingest(client):
    assert {
        PracticeQuestion,
        PracticeExtractionRun,
        PracticeAnswer,
        ConceptMastery,
        ConceptMasteryEvent,
    }.issubset(set(REPLACED_ON_REINGEST))
    assert Concept in REMAPPED_ON_REINGEST


def test_practice_question_unique_fingerprint_per_section(client):
    session = get_session()
    try:
        course = Course(title="Practice Course")
        session.add(course)
        session.flush()
        section = Section(
            id="practice-section",
            course_id=course.id,
            order_index=1,
            title="0.2 Practice - Fractions",
            body_md="1. Simplify 42/12",
            content_hash="practice-hash",
            kind="practice",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        concept = Concept(
            id=str(uuid.uuid4()),
            course_id=course.id,
            slug="fractions.simplify",
            label="Simplifying Fractions",
            chapter_label=section.chapter_label,
            section_id=section.id,
        )
        session.add(section)
        session.flush()
        session.add(concept)
        session.flush()
        first = PracticeQuestion(
            course_id=course.id,
            chapter_label=section.chapter_label,
            section_id=section.id,
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
        duplicate = PracticeQuestion(
            course_id=course.id,
            chapter_label=section.chapter_label,
            section_id=section.id,
            concept_id=concept.id,
            problem_number="1",
            source_ref="0.2 Practice - Fractions #1 duplicate",
            stem_md="Simplify $42/12$.",
            choices=["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
            correct_index=0,
            explanation_md="$42/12 = 7/2$.",
            source_fingerprint="fingerprint-1",
            extraction_version="v3",
            confidence=0.99,
            status="ready",
        )
        session.add(first)
        session.commit()
        session.add(duplicate)
        try:
            session.commit()
        except Exception:
            session.rollback()
        else:
            raise AssertionError("duplicate source_fingerprint should be rejected")
    finally:
        session.close()
