from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptRevision,
    ConceptSourceLink,
    Course,
    CurriculumVersion,
    EvidenceItem,
    EvidenceItemConceptLink,
    LearnerConceptState,
    LearnerEvidenceEvent,
    LearningClaim,
    LearningClaimRevision,
    Section,
)
from app.services import learner_context
from app.services.learner_model import LearnerModelConfig, rebuild_profile


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
ALICE_ID = "10000000-0000-0000-0000-000000000001"
BOB_ID = "10000000-0000-0000-0000-000000000002"


def _seed_projection_fixture(session):
    course = Course(title="Projection", status="ready")
    session.add(course)
    session.flush()
    section = Section(
        id=f"section-{uuid.uuid4()}",
        course_id=course.id,
        order_index=0,
        title="Fractions",
        body_md="Fractions source.",
        content_hash="projection-source",
    )
    concept = Concept(course_id=course.id, slug="fractions", label="Fractions")
    version = CurriculumVersion(course_id=course.id, status="published", is_current=True)
    session.add_all([section, concept, version])
    session.flush()
    session.add(
        ConceptRevision(
            curriculum_version_id=version.id,
            concept_id=concept.id,
            label=concept.label,
            description_md="Reason about fractions.",
            aliases=[],
            review_state="verified",
        )
    )
    claim = LearningClaim(
        course_id=course.id,
        concept_id=concept.id,
        stable_key="identify-fractions",
    )
    session.add(claim)
    session.flush()
    session.add_all(
        [
            LearningClaimRevision(
                curriculum_version_id=version.id,
                learning_claim_id=claim.id,
                concept_id=concept.id,
                statement="Identify fractions.",
                success_criteria_md="Identifies the fraction.",
                aliases=[],
                review_state="verified",
            ),
            ConceptSourceLink(
                course_id=course.id,
                curriculum_version_id=version.id,
                concept_id=concept.id,
                learning_claim_id=claim.id,
                section_id=section.id,
                source_ref="Fractions p. 1",
                source_content_hash=section.content_hash,
                review_state="verified",
            ),
        ]
    )
    alice = learner_context.ensure_course_learning_profile(session, ALICE_ID, course.id)
    bob = learner_context.ensure_course_learning_profile(session, BOB_ID, course.id)
    for index, outcome in enumerate((0.0, 0.0, 1.0)):
        item = EvidenceItem(
            course_id=course.id,
            item_type="quiz_question",
            source_record_id=f"quiz-{index}",
            source_index=0,
            content_json={"question": f"Question {index}"},
            content_fingerprint=f"fingerprint-{index}",
            mapping_status="mapped",
        )
        session.add(item)
        session.flush()
        mapping = EvidenceItemConceptLink(
            course_id=course.id,
            evidence_item_id=item.id,
            curriculum_version_id=version.id,
            learning_claim_id=claim.id,
            role="primary",
            task_type="multiple_choice",
            review_state="verified",
        )
        session.add(mapping)
        session.flush()
        session.add(
            LearnerEvidenceEvent(
                course_id=course.id,
                course_learning_profile_id=alice.id,
                evidence_item_id=item.id,
                evidence_mapping_id=mapping.id,
                learning_claim_id=claim.id,
                curriculum_version_id=version.id,
                channel="quiz",
                normalized_outcome=outcome,
                raw_result={"correct": bool(outcome)},
                event_at=NOW - timedelta(days=3 - index),
                session_id=f"session-{index}",
                source_event_key=f"event-{index}",
            )
        )
    session.commit()
    return course, version, concept, claim, section, alice, bob


def test_rebuild_is_idempotent_and_keeps_claim_and_concept_states(client):
    session = get_session()
    try:
        course, version, concept, claim, _section, alice, _bob = _seed_projection_fixture(session)
        first = rebuild_profile(session, course.id, alice.id, now=NOW)
        session.commit()
        first_ids = {row.state_key: row.id for row in first}

        second = rebuild_profile(session, course.id, alice.id, now=NOW)
        session.commit()

        assert {row.state_key for row in second} == {
            f"claim:{claim.id}",
            f"concept:{concept.id}",
        }
        assert {row.state_key: row.id for row in second} == first_ids
        assert all(row.curriculum_version_id == version.id for row in second)
        assert session.query(LearnerConceptState).count() == 2
    finally:
        session.close()


def test_rebuild_is_learner_scoped_and_versioned_by_model(client):
    session = get_session()
    try:
        course, _version, _concept, _claim, _section, alice, bob = _seed_projection_fixture(session)
        rebuild_profile(session, course.id, alice.id, now=NOW)
        rebuild_profile(session, course.id, bob.id, now=NOW)
        rebuild_profile(
            session,
            course.id,
            alice.id,
            now=NOW,
            config=LearnerModelConfig(version="transparent-beta-v2"),
        )
        session.commit()

        alice_v1 = session.query(LearnerConceptState).filter_by(
            course_learning_profile_id=alice.id,
            model_version="transparent-beta-v1",
        ).all()
        alice_v2 = session.query(LearnerConceptState).filter_by(
            course_learning_profile_id=alice.id,
            model_version="transparent-beta-v2",
        ).all()
        bob_v1 = session.query(LearnerConceptState).filter_by(
            course_learning_profile_id=bob.id,
            model_version="transparent-beta-v1",
        ).all()
        assert len(alice_v1) == len(alice_v2) == len(bob_v1) == 2
        assert all(row.readiness_estimate is None for row in bob_v1)
        assert any(row.readiness_estimate is not None for row in alice_v1)
    finally:
        session.close()


def test_rebuild_excludes_stale_source_mappings_without_erasing_history(client):
    session = get_session()
    try:
        course, version, concept, claim, section, alice, _bob = _seed_projection_fixture(session)
        before = rebuild_profile(session, course.id, alice.id, now=NOW)
        session.commit()
        assert next(row for row in before if row.state_key == f"claim:{claim.id}").readiness_estimate

        source = session.query(ConceptSourceLink).filter_by(
            curriculum_version_id=version.id,
            learning_claim_id=claim.id,
            section_id=section.id,
        ).one()
        source.stale = True
        session.commit()
        after = rebuild_profile(session, course.id, alice.id, now=NOW)
        session.commit()

        claim_state = next(row for row in after if row.state_key == f"claim:{claim.id}")
        assert claim_state.readiness_estimate is None
        assert claim_state.status == "insufficient_evidence"
        assert session.query(LearnerEvidenceEvent).count() == 3
    finally:
        session.close()


def test_skill_map_exposes_nullable_evidence_aware_readiness(client):
    session = get_session()
    try:
        course, _version, concept, _claim, _section, alice, bob = _seed_projection_fixture(session)
        rebuild_profile(session, course.id, alice.id, now=NOW)
        rebuild_profile(session, course.id, bob.id, now=NOW)
        session.commit()
        course_id = course.id
        concept_id = concept.id
    finally:
        session.close()

    client.cookies.set(learner_context.LEARNER_COOKIE, ALICE_ID)
    alice_node = next(
        node
        for node in client.get(f"/api/courses/{course_id}/skills").json()["nodes"]
        if node["id"] == concept_id
    )
    assert 0 < alice_node["readiness_estimate"] < 1
    assert "mastery" not in alice_node
    assert alice_node["evidence_state"] != "insufficient_evidence"
    assert alice_node["effective_evidence_count"] > 0

    client.cookies.set(learner_context.LEARNER_COOKIE, BOB_ID)
    bob_node = next(
        node
        for node in client.get(f"/api/courses/{course_id}/skills").json()["nodes"]
        if node["id"] == concept_id
    )
    assert bob_node["readiness_estimate"] is None
    assert bob_node["evidence_state"] == "insufficient_evidence"
    assert "mastery" not in bob_node
