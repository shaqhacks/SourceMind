from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Concept, ConceptRelation, ConceptRevision, Course, CurriculumVersion
from app.services import curriculum_service


def _course_id() -> str:
    session = get_session()
    try:
        course = Course(title="Curriculum service", status="ready")
        session.add(course)
        session.commit()
        return course.id
    finally:
        session.close()


def test_create_draft_clones_current_curriculum_and_publish_supersedes_it(client):
    course_id = _course_id()
    first = curriculum_service.create_draft(course_id)
    concept = curriculum_service.add_concept(
        first.id,
        stable_key="fractions",
        label="Fractions",
        description_md="Reason about parts of a whole.",
        aliases=["fraction"],
    )
    claim = curriculum_service.add_claim(
        first.id,
        concept_id=concept.id,
        stable_key="identify-unit-fraction",
        statement="Identify a unit fraction.",
        success_criteria_md="Chooses one equal part.",
        cognitive_demand="understand",
    )
    published = curriculum_service.publish(first.id)
    second = curriculum_service.create_draft(course_id, based_on_version_id=published.id)

    session = get_session()
    try:
        cloned_concept = session.query(ConceptRevision).filter_by(
            curriculum_version_id=second.id, concept_id=concept.id
        ).one()
        assert cloned_concept.aliases == ["fraction"]
        assert claim.concept_id == concept.id
    finally:
        session.close()

    curriculum_service.edit_concept(
        second.id,
        concept.id,
        label="Fraction reasoning",
        description_md="Connect representations of fractional quantities.",
        aliases=["fraction", "rational parts"],
    )
    second_published = curriculum_service.publish(second.id)

    session = get_session()
    try:
        versions = session.query(CurriculumVersion).filter_by(course_id=course_id).all()
        assert sum(version.is_current for version in versions) == 1
        assert second_published.is_current is True
        assert session.get(CurriculumVersion, published.id).status == "superseded"
    finally:
        session.close()


def test_relation_review_merge_and_split_operations_are_version_bounded(client):
    course_id = _course_id()
    draft = curriculum_service.create_draft(course_id)
    first = curriculum_service.add_concept(
        draft.id, stable_key="part-whole", label="Part-whole", description_md=""
    )
    duplicate = curriculum_service.add_concept(
        draft.id, stable_key="fractions", label="Fractions", description_md=""
    )
    advanced = curriculum_service.add_concept(
        draft.id, stable_key="equivalent-fractions", label="Equivalent fractions", description_md=""
    )
    relation = curriculum_service.add_relation(
        draft.id,
        from_concept_id=duplicate.id,
        to_concept_id=advanced.id,
        kind="requires",
        confidence=0.7,
        rationale_md="The book introduces fractions first.",
    )
    reviewed = curriculum_service.review_relation(relation.id, "verified")
    curriculum_service.merge_concepts(draft.id, [duplicate.id], target_concept_id=first.id)
    split = curriculum_service.split_concept(
        draft.id,
        first.id,
        [
            {"stable_key": "unit-fractions", "label": "Unit fractions"},
            {"stable_key": "non-unit-fractions", "label": "Non-unit fractions"},
        ],
    )

    session = get_session()
    try:
        assert reviewed.review_state == "verified"
        assert session.get(Concept, duplicate.id).merged_into_concept_id == first.id
        assert len(split) == 2
        assert all(
            session.query(ConceptRevision)
            .filter_by(curriculum_version_id=draft.id, concept_id=concept.id)
            .count()
            == 1
            for concept in split
        )
        assert session.get(ConceptRelation, relation.id).curriculum_version_id == draft.id
    finally:
        session.close()
