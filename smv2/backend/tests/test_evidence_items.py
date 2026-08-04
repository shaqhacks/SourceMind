from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptRevision,
    ConceptSourceLink,
    Course,
    CurriculumVersion,
    EvidenceItem,
    EvidenceItemConceptLink,
    LearningClaim,
    LearningClaimRevision,
    Section,
)
from app.pipeline.cards_generation import _parse_cards
from app.pipeline.quiz_generation import _parse_questions
from app.services import evidence_items_service


def _curriculum(session):
    course = Course(title="Evidence mapping", status="ready")
    session.add(course)
    session.flush()
    section = Section(
        id=f"section-{uuid.uuid4()}",
        course_id=course.id,
        order_index=0,
        title="Fractions",
        body_md="One of four equal parts is one-fourth.",
        content_hash="evidence-source",
    )
    concept = Concept(course_id=course.id, slug="fractions", label="Fractions")
    version = CurriculumVersion(course_id=course.id, status="published", is_current=True)
    session.add_all([section, concept, version])
    session.flush()
    session.add(
        ConceptRevision(
            curriculum_version_id=version.id,
            concept_id=concept.id,
            label="Fractions",
            description_md="Reason about equal parts.",
            aliases=[],
            review_state="verified",
        )
    )
    claims = []
    for key, statement in (
        ("identify-unit-fraction", "Identify a unit fraction."),
        ("explain-unit-fraction", "Explain a unit fraction."),
    ):
        claim = LearningClaim(course_id=course.id, concept_id=concept.id, stable_key=key)
        session.add(claim)
        session.flush()
        session.add_all(
            [
                LearningClaimRevision(
                    curriculum_version_id=version.id,
                    learning_claim_id=claim.id,
                    concept_id=concept.id,
                    statement=statement,
                    success_criteria_md="Uses equal-part reasoning.",
                    aliases=[],
                    cognitive_demand="understand",
                    review_state="verified",
                ),
                ConceptSourceLink(
                    course_id=course.id,
                    curriculum_version_id=version.id,
                    concept_id=concept.id,
                    learning_claim_id=claim.id,
                    section_id=section.id,
                    source_ref="Fractions p. 1",
                    excerpt_md=section.body_md,
                    source_content_hash=section.content_hash,
                    review_state="verified",
                ),
            ]
        )
        claims.append(claim)
    session.commit()
    return course, section, version, claims


def test_evidence_content_is_immutable_and_has_one_primary_mapping(client):
    session = get_session()
    try:
        course, _section, version, claims = _curriculum(session)
        item = evidence_items_service.snapshot_item(
            session,
            course_id=course.id,
            item_type="quiz_question",
            source_record_id="quiz-1",
            source_index=0,
            content={"question": "What is one-fourth?"},
            source_ref="Fractions p. 1",
            prompt_version="v3",
            model="test-model",
        )
        evidence_items_service.map_item_to_claim(
            session,
            item,
            curriculum_version_id=version.id,
            learning_claim_id=claims[0].id,
            task_type="multiple_choice",
            cognitive_demand="understand",
            authored_difficulty_band="introductory",
            mapping_confidence=0.9,
            source_ref="Fractions p. 1",
            prompt_version="v3",
            model="test-model",
            review_state="verified",
        )
        session.commit()
        assert item.mapping_status == "mapped"

        with pytest.raises(IntegrityError):
            evidence_items_service.map_item_to_claim(
                session,
                item,
                curriculum_version_id=version.id,
                learning_claim_id=claims[1].id,
                task_type="multiple_choice",
                cognitive_demand="understand",
                authored_difficulty_band="introductory",
                mapping_confidence=0.8,
                source_ref="Fractions p. 1",
                prompt_version="v3",
                model="test-model",
                review_state="verified",
            )
            session.commit()
        session.rollback()

        immutable = session.get(EvidenceItem, item.id)
        immutable.content_json = {"question": "Rewritten"}
        with pytest.raises((IntegrityError, OperationalError)):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_claim_options_are_limited_to_published_sources_for_selected_sections(client):
    session = get_session()
    try:
        course, section, version, claims = _curriculum(session)
        version_id, options = evidence_items_service.claim_options_for_sections(
            session, course.id, [section.id]
        )
        assert version_id == version.id
        assert {option["claim_id"] for option in options} == {claim.id for claim in claims}
    finally:
        session.close()


def test_quiz_and_card_parsers_reject_invented_claim_ids():
    allowed = {"claim-1"}
    quiz = [
        {
            "question": "Q",
            "choices": ["A", "B", "C", "D"],
            "correct_index": 0,
            "explanation": "A",
            "claim_id": "invented",
            "task_type": "multiple_choice",
            "cognitive_demand": "understand",
            "difficulty_band": "introductory",
            "mapping_confidence": 0.9,
            "source_ref": "p. 1",
        }
    ]
    card = [
        {
            "front": "Q",
            "back": "A",
            "claim_id": "invented",
            "task_type": "recall",
            "cognitive_demand": "remember",
            "difficulty_band": "introductory",
            "mapping_confidence": 0.9,
            "source_ref": "p. 1",
        }
    ]
    with pytest.raises(ValueError, match="unknown claim"):
        _parse_questions(json.dumps(quiz), allowed)
    with pytest.raises(ValueError, match="unknown claim"):
        _parse_cards(json.dumps(card), allowed)


def test_legacy_unmapped_item_has_no_diagnostic_primary_link(client):
    session = get_session()
    try:
        course = Course(title="Legacy evidence", status="ready")
        session.add(course)
        session.flush()
        item = evidence_items_service.snapshot_item(
            session,
            course_id=course.id,
            item_type="flashcard",
            source_record_id="legacy-card",
            source_index=-1,
            content={"front": "Q", "back": "A"},
            source_ref=None,
            prompt_version="v2",
            model=None,
        )
        session.commit()
        assert item.mapping_status == "legacy_unmapped"
        assert (
            session.query(EvidenceItemConceptLink)
            .filter_by(evidence_item_id=item.id, role="primary")
            .count()
            == 0
        )
    finally:
        session.close()
