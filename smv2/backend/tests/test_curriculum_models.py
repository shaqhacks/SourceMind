from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptRelation,
    ConceptRevision,
    ConceptSourceLink,
    Course,
    CurriculumVersion,
    LearningClaim,
    LearningClaimRevision,
    Section,
)


def _course(session) -> Course:
    course = Course(title="Versioned curriculum", status="ready")
    session.add(course)
    session.flush()
    return course


def test_concept_identity_is_stable_across_curriculum_revisions(client):
    session = get_session()
    try:
        course = _course(session)
        concept = Concept(course_id=course.id, slug="fractions", label="Fractions")
        first = CurriculumVersion(course_id=course.id, status="published", is_current=True)
        second = CurriculumVersion(
            course_id=course.id,
            status="draft",
            is_current=False,
            parent_version_id=first.id,
        )
        session.add_all([concept, first, second])
        session.flush()
        session.add_all(
            [
                ConceptRevision(
                    curriculum_version_id=first.id,
                    concept_id=concept.id,
                    label="Fractions",
                    description_md="Original description",
                    aliases=["fraction"],
                ),
                ConceptRevision(
                    curriculum_version_id=second.id,
                    concept_id=concept.id,
                    label="Fraction reasoning",
                    description_md="Improved description",
                    aliases=["fraction", "rational parts"],
                ),
            ]
        )
        session.commit()

        revisions = (
            session.query(ConceptRevision)
            .filter_by(concept_id=concept.id)
            .order_by(ConceptRevision.created_at)
            .all()
        )
        assert len(revisions) == 2
        assert {revision.concept_id for revision in revisions} == {concept.id}
        assert revisions[1].aliases == ["fraction", "rational parts"]
    finally:
        session.close()


def test_only_one_curriculum_version_can_be_current_per_course(client):
    session = get_session()
    try:
        course = _course(session)
        session.add(
            CurriculumVersion(course_id=course.id, status="published", is_current=True)
        )
        session.commit()
        session.add(
            CurriculumVersion(course_id=course.id, status="published", is_current=True)
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_relation_kinds_are_database_constrained(client):
    session = get_session()
    try:
        course = _course(session)
        version = CurriculumVersion(
            course_id=course.id, status="published", is_current=True
        )
        first = Concept(course_id=course.id, slug="first", label="First")
        second = Concept(course_id=course.id, slug="second", label="Second")
        session.add_all([version, first, second])
        session.flush()
        session.add(
            ConceptRelation(
                course_id=course.id,
                curriculum_version_id=version.id,
                from_concept_id=first.id,
                to_concept_id=second.id,
                kind="invented_relation",
                review_state="unverified",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_claim_revision_membership_aliases_and_source_provenance_persist(client):
    session = get_session()
    try:
        course = _course(session)
        section = Section(
            id=f"section-{uuid.uuid4()}",
            course_id=course.id,
            order_index=0,
            title="Fractions",
            body_md="A fraction represents part of a whole.",
            content_hash="fractions-source-hash",
        )
        version = CurriculumVersion(
            course_id=course.id, status="published", is_current=True
        )
        concept = Concept(course_id=course.id, slug="fractions", label="Fractions")
        session.add_all([section, version, concept])
        session.flush()
        claim = LearningClaim(
            course_id=course.id,
            concept_id=concept.id,
            stable_key="identify-unit-fraction",
        )
        session.add(claim)
        session.flush()
        revision = LearningClaimRevision(
            curriculum_version_id=version.id,
            learning_claim_id=claim.id,
            concept_id=concept.id,
            statement="Identify a unit fraction in a visual model.",
            success_criteria_md="Selects the correct single equal part.",
            aliases=["recognize unit fractions"],
            cognitive_demand="understand",
        )
        source = ConceptSourceLink(
            course_id=course.id,
            curriculum_version_id=version.id,
            concept_id=concept.id,
            learning_claim_id=claim.id,
            section_id=section.id,
            source_ref="Fractions, p. 1",
            excerpt_md="A fraction represents part of a whole.",
            source_content_hash=section.content_hash,
            confidence=0.95,
            review_state="verified",
        )
        session.add_all([revision, source])
        session.commit()

        loaded = session.get(LearningClaimRevision, revision.id)
        assert loaded.concept_id == concept.id
        assert loaded.aliases == ["recognize unit fractions"]
        loaded_source = session.get(ConceptSourceLink, source.id)
        assert loaded_source.section_id == section.id
        assert loaded_source.source_content_hash == "fractions-source-hash"
        assert loaded_source.stale is False
    finally:
        session.close()
