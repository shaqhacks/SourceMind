from __future__ import annotations

import uuid

from app.db.engine import get_session
from app.db.models import (
    Card,
    Concept,
    ConceptRelation,
    ConceptRevision,
    ConceptSourceLink,
    Course,
    CurriculumVersion,
    Job,
    LearningClaim,
    LearningClaimRevision,
    Section,
    Test,
    TestAttempt,
)
from app.services import (
    curriculum_service,
    evidence_items_service,
    learner_context,
    skills_service,
)


def _course_with_section(session) -> tuple[Course, Section]:
    course = Course(title="Editor Course", status="ready")
    session.add(course)
    session.flush()
    section = Section(
        id=f"section-{uuid.uuid4()}",
        course_id=course.id,
        order_index=0,
        title="Ch 1: Basics",
        body_md="source text",
        content_hash="editor-hash",
    )
    session.add(section)
    session.flush()
    return course, section


def test_ingest_autogens_concept_extraction_job(client, ingest_course, monkeypatch):
    monkeypatch.setenv("SMV2_SKILL_MAP_AUTOGEN", "1")
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        jobs = session.query(Job).filter(Job.type == "concept_extraction").all()
        assert len(jobs) == 1
        assert jobs[0].status == "queued"
        assert (jobs[0].payload or {}).get("course_id") == course_id
        draft = (
            session.query(CurriculumVersion)
            .filter_by(course_id=course_id, status="draft")
            .one_or_none()
        )
        assert draft is not None
        assert (jobs[0].payload or {}).get("curriculum_version_id") == draft.id
    finally:
        session.close()


def test_skill_status_reports_generating_after_autogen(client, ingest_course, monkeypatch):
    monkeypatch.setenv("SMV2_SKILL_MAP_AUTOGEN", "1")
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    resp = client.get(f"/api/courses/{course_id}/skills/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["phase"] == "generating"
    assert body["job_id"] is not None
    assert body["draft_version_id"] is not None
    assert body["published"] is False


def test_skill_status_none_without_autogen(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    resp = client.get(f"/api/courses/{course_id}/skills/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["phase"] == "none"
    assert body["published"] is False
    assert body["concept_count"] == 0


def test_editor_operations_add_edit_reassign_relation_delete(client):
    session = get_session()
    try:
        course, section = _course_with_section(session)
        session.commit()
    finally:
        session.close()

    version = curriculum_service.create_draft(course.id)
    concept = curriculum_service.add_concept(
        version.id,
        stable_key="a",
        label="A",
        description_md="",
        section_id=section.id,
        chapter_label="Ch 1: Basics",
    )
    revision = curriculum_service.edit_concept(
        version.id,
        concept.id,
        label="A renamed",
        description_md="described",
        aliases=[],
        chapter_label="Ch 1: Basics",
        section_id=section.id,
    )
    assert revision.label == "A renamed"

    other = curriculum_service.add_concept(
        version.id, stable_key="b", label="B", description_md=""
    )
    relation = curriculum_service.add_relation(
        version.id, from_concept_id=concept.id, to_concept_id=other.id, kind="requires"
    )
    curriculum_service.remove_relation_by_id(relation.id)
    curriculum_service.delete_concept(version.id, other.id)

    session = get_session()
    try:
        assert session.get(Concept, concept.id).section_id == section.id
        assert session.get(ConceptRelation, relation.id) is None
        deactivated = (
            session.query(ConceptRevision)
            .filter_by(curriculum_version_id=version.id, concept_id=other.id)
            .one()
        )
        assert deactivated.is_active is False
    finally:
        session.close()


def test_editor_endpoints_via_http(client):
    session = get_session()
    try:
        course, section = _course_with_section(session)
        session.commit()
    finally:
        session.close()

    draft = client.post(
        f"/api/courses/{course.id}/curriculum/drafts", json={"label": "Editor"}
    ).json()
    version_id = draft["curriculum_version_id"]

    add = client.post(
        f"/api/curriculum/{version_id}/concepts",
        json={
            "stable_key": "x",
            "label": "X",
            "description_md": "",
            "section_id": section.id,
            "chapter_label": "Ch 1: Basics",
        },
    )
    assert add.status_code == 201
    concept_id = add.json()["concept_id"]

    add_other = client.post(
        f"/api/curriculum/{version_id}/concepts",
        json={"stable_key": "y", "label": "Y", "description_md": ""},
    )
    assert add_other.status_code == 201
    other_id = add_other.json()["concept_id"]

    rel = client.post(
        f"/api/curriculum/{version_id}/relations",
        json={"from_concept_id": concept_id, "to_concept_id": other_id, "kind": "requires"},
    )
    assert rel.status_code == 201
    rel_id = rel.json()["relation_id"]

    assert client.delete(f"/api/curriculum/relations/{rel_id}").status_code == 200
    assert (
        client.delete(f"/api/curriculum/{version_id}/concepts/{other_id}").status_code == 200
    )


def test_taught_in_prepends_primary_section(client):
    session = get_session()
    try:
        course, section = _course_with_section(session)
        concept = Concept(course_id=course.id, slug="a", label="A", section_id=section.id)
        session.add(concept)
        session.flush()
        session.commit()
        taught = skills_service._taught_in(session, course.id, concept.id)
        assert [item["section_id"] for item in taught] == [section.id]
        assert taught[0]["rank"] == 0
        assert taught[0]["relevance_md"] == "Introduced here"
    finally:
        session.close()


def test_skill_detail_surfaces_linked_items(client):
    session = get_session()
    try:
        course, section = _course_with_section(session)
        concept = Concept(
            course_id=course.id, slug="fractions", label="Fractions", section_id=section.id
        )
        version = CurriculumVersion(course_id=course.id, status="published", is_current=True)
        session.add_all([concept, version])
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
        claim = LearningClaim(course_id=course.id, concept_id=concept.id, stable_key="c1")
        session.add(claim)
        session.flush()
        session.add(
            LearningClaimRevision(
                curriculum_version_id=version.id,
                learning_claim_id=claim.id,
                concept_id=concept.id,
                statement="Identify a unit fraction.",
                success_criteria_md="",
                aliases=[],
                review_state="verified",
            )
        )
        session.add(
            ConceptSourceLink(
                course_id=course.id,
                curriculum_version_id=version.id,
                concept_id=concept.id,
                learning_claim_id=claim.id,
                section_id=section.id,
                source_ref="p1",
                excerpt_md="",
                source_content_hash="h",
                review_state="verified",
            )
        )
        card = Card(
            id=f"card-{uuid.uuid4()}",
            course_id=course.id,
            section_id=section.id,
            front_md="What is 1/4?",
            back_md="One of four equal parts.",
            position=0,
        )
        session.add(card)
        session.flush()
        item = evidence_items_service.snapshot_item(
            session,
            course_id=course.id,
            item_type="flashcard",
            source_record_id=card.id,
            source_index=-1,
            content={"front": "What is 1/4?", "back": "One of four equal parts."},
            source_ref="p1",
            prompt_version=None,
            model=None,
        )
        evidence_items_service.map_item_to_claim(
            session,
            item,
            curriculum_version_id=version.id,
            learning_claim_id=claim.id,
            role="primary",
            task_type="retrieval",
            cognitive_demand=None,
            authored_difficulty_band=None,
            mapping_confidence=None,
            source_ref="p1",
            prompt_version=None,
            model=None,
            review_state="verified",
        )
        session.commit()
    finally:
        session.close()

    detail = skills_service.get_skill_detail(course.id, concept.id)
    assert detail is not None
    assert detail["node"]["section_id"] == section.id
    items = detail["linked_items"]
    assert len(items) == 1
    assert items[0]["item_type"] == "flashcard"
    assert items[0]["card_id"] == card.id
    assert items[0]["section_id"] == section.id
    assert items[0]["claim_statement"] == "Identify a unit fraction."


def test_skill_detail_surfaces_linked_quiz_question(client):
    session = get_session()
    try:
        course, section = _course_with_section(session)
        concept = Concept(
            course_id=course.id, slug="fractions", label="Fractions", section_id=section.id
        )
        version = CurriculumVersion(course_id=course.id, status="published", is_current=True)
        session.add_all([concept, version])
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
        claim = LearningClaim(course_id=course.id, concept_id=concept.id, stable_key="c1")
        session.add(claim)
        session.flush()
        session.add(
            LearningClaimRevision(
                curriculum_version_id=version.id,
                learning_claim_id=claim.id,
                concept_id=concept.id,
                statement="Identify a unit fraction.",
                success_criteria_md="",
                aliases=[],
                review_state="verified",
            )
        )
        session.add(
            ConceptSourceLink(
                course_id=course.id,
                curriculum_version_id=version.id,
                concept_id=concept.id,
                learning_claim_id=claim.id,
                section_id=section.id,
                source_ref="p1",
                excerpt_md="",
                source_content_hash="h",
                review_state="verified",
            )
        )
        profile = learner_context.ensure_course_learning_profile(
            session, learner_context.LEGACY_LOCAL_LEARNER_ID, course.id
        )
        test = Test(
            course_id=course.id,
            questions=[
                {
                    "question": "Which is one-fourth?",
                    "choices": ["1/2", "1/4", "3/4", "1/8"],
                    "correct_index": 1,
                    "explanation": "One of four equal parts.",
                }
            ],
        )
        session.add(test)
        session.flush()
        session.add(
            TestAttempt(
                course_learning_profile_id=profile.id, test_id=test.id, course_id=course.id
            )
        )
        session.flush()
        item = evidence_items_service.snapshot_item(
            session,
            course_id=course.id,
            item_type="quiz_question",
            source_record_id=test.id,
            source_index=0,
            content={
                "question": "Which is one-fourth?",
                "choices": ["1/2", "1/4", "3/4", "1/8"],
                "correct_index": 1,
                "explanation": "One of four equal parts.",
            },
            source_ref="p1",
            prompt_version=None,
            model=None,
        )
        evidence_items_service.map_item_to_claim(
            session,
            item,
            curriculum_version_id=version.id,
            learning_claim_id=claim.id,
            role="primary",
            task_type="application",
            cognitive_demand=None,
            authored_difficulty_band=None,
            mapping_confidence=None,
            source_ref="p1",
            prompt_version=None,
            model=None,
            review_state="verified",
        )
        session.commit()
    finally:
        session.close()

    detail = skills_service.get_skill_detail(course.id, concept.id)
    assert detail is not None
    questions = [i for i in detail["linked_items"] if i["item_type"] == "quiz_question"]
    assert len(questions) == 1
    assert questions[0]["test_id"] == test.id
    assert questions[0]["attempt_id"] is not None
    assert questions[0]["preview"] == "Which is one-fourth?"
