from __future__ import annotations

import uuid

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptRelation,
    ConceptRevision,
    Course,
    CurriculumVersion,
    Section,
)


def _course_with_sections(session) -> tuple[Course, list[Section]]:
    course = Course(title="Upload Course", status="ready")
    session.add(course)
    session.flush()
    sections = [
        Section(
            id=f"section-{uuid.uuid4()}",
            course_id=course.id,
            order_index=i,
            title=title,
            chapter_label=chapter,
            body_md="source text",
            content_hash=f"hash-{i}",
            page_start=start,
            page_end=end,
        )
        for i, (title, chapter, start, end) in enumerate(
            [
                ("Chapter 5. Replication", "Chapter 5. Replication", 166, 211),
                ("Chapter 6. Partitioning", "Chapter 6. Partitioning", 212, 233),
            ]
        )
    ]
    session.add_all(sections)
    session.flush()
    return course, sections


def _payload() -> dict:
    return {
        "concepts": [
            {
                "label": "Replication",
                "description": "Reason about replication for fault tolerance.",
                "introduced_in": "Chapter 5: Replication",
                "prerequisites": [],
            },
            {
                "label": "Partitioning",
                "description": "Reason about splitting data across nodes.",
                "introduced_in": "Chapter 6: Partitioning",
                "prerequisites": ["Replication"],
            },
        ]
    }


def test_upload_creates_draft_with_matched_sections(client):
    session = get_session()
    try:
        course, sections = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    resp = client.post(f"/api/courses/{course.id}/curriculum/upload", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["concept_count"] == 2
    assert body["relation_count"] == 1
    assert body["matched_sections"] == 2
    assert body["unmatched_sections"] == []

    s = get_session()
    try:
        version = (
            s.query(CurriculumVersion)
            .filter_by(course_id=course.id, status="draft")
            .one()
        )
        assert (
            s.query(ConceptRevision)
            .filter_by(curriculum_version_id=version.id)
            .count()
            == 2
        )
        rels = s.query(ConceptRelation).filter_by(curriculum_version_id=version.id).all()
        assert len(rels) == 1
        assert rels[0].kind == "requires"
        concepts = {c.slug: c for c in s.query(Concept).filter_by(course_id=course.id)}
        assert concepts["replication"].section_id == sections[0].id
        assert concepts["partitioning"].section_id == sections[1].id
    finally:
        s.close()


def test_upload_template_returns_copyable_prompt(client):
    session = get_session()
    try:
        course, _ = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    resp = client.get(f"/api/courses/{course.id}/curriculum/upload-template")
    assert resp.status_code == 200
    prompt = resp.json()["prompt"]
    assert '"concepts"' in prompt
    assert '"prerequisites"' in prompt
    assert "at most 20" in prompt.lower()


def test_upload_unmatched_section_falls_back_to_text(client):
    session = get_session()
    try:
        course, _ = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    payload = {
        "concepts": [
            {
                "label": "Transactions",
                "description": "Reason about atomicity.",
                "introduced_in": "Some unlabeled chapter",
                "prerequisites": [],
            }
        ]
    }
    resp = client.post(f"/api/courses/{course.id}/curriculum/upload", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched_sections"] == 0
    assert body["unmatched_sections"] == ["Some unlabeled chapter"]

    s = get_session()
    try:
        concept = s.query(Concept).filter_by(course_id=course.id, slug="transactions").one()
        assert concept.section_id is None
        assert concept.chapter_label == "Some unlabeled chapter"
    finally:
        s.close()


def test_upload_matches_topic_only_reference(client):
    session = get_session()
    try:
        course, sections = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    resp = client.post(
        f"/api/courses/{course.id}/curriculum/upload",
        json={
            "concepts": [
                {
                    "label": "Replication",
                    "description": "",
                    "introduced_in": "Replication",
                    "prerequisites": [],
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["matched_sections"] == 1

    s = get_session()
    try:
        concept = s.query(Concept).filter_by(course_id=course.id, slug="replication").one()
        assert concept.section_id == sections[0].id
    finally:
        s.close()


def test_upload_matches_by_page_number(client):
    session = get_session()
    try:
        course, sections = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    resp = client.post(
        f"/api/courses/{course.id}/curriculum/upload",
        json={
            "concepts": [
                {
                    "label": "Replication",
                    "description": "",
                    "page": 170,
                    "prerequisites": [],
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["matched_sections"] == 1

    s = get_session()
    try:
        concept = s.query(Concept).filter_by(course_id=course.id, slug="replication").one()
        assert concept.section_id == sections[0].id
    finally:
        s.close()


def test_upload_rejects_duplicate_labels(client):
    session = get_session()
    try:
        course, _ = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    payload = {
        "concepts": [
            {"label": "Replication", "description": "", "prerequisites": []},
            {"label": "replication", "description": "", "prerequisites": []},
        ]
    }
    resp = client.post(f"/api/courses/{course.id}/curriculum/upload", json=payload)
    assert resp.status_code == 422


def test_upload_rejects_unknown_prerequisite(client):
    session = get_session()
    try:
        course, _ = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    payload = {
        "concepts": [
            {
                "label": "Replication",
                "description": "",
                "prerequisites": ["Not a listed skill"],
            }
        ]
    }
    resp = client.post(f"/api/courses/{course.id}/curriculum/upload", json=payload)
    assert resp.status_code == 422


def test_upload_rejects_self_prerequisite(client):
    session = get_session()
    try:
        course, _ = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    payload = {
        "concepts": [
            {"label": "Replication", "description": "", "prerequisites": ["Replication"]}
        ]
    }
    resp = client.post(f"/api/courses/{course.id}/curriculum/upload", json=payload)
    assert resp.status_code == 422


def test_upload_rejects_cycle(client):
    session = get_session()
    try:
        course, _ = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    payload = {
        "concepts": [
            {"label": "A", "description": "", "prerequisites": ["B"]},
            {"label": "B", "description": "", "prerequisites": ["A"]},
        ]
    }
    resp = client.post(f"/api/courses/{course.id}/curriculum/upload", json=payload)
    assert resp.status_code == 422


def test_upload_rejects_more_than_20_concepts(client):
    session = get_session()
    try:
        course, _ = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    payload = {
        "concepts": [
            {"label": f"Skill {i}", "description": "", "prerequisites": []}
            for i in range(21)
        ]
    }
    resp = client.post(f"/api/courses/{course.id}/curriculum/upload", json=payload)
    assert resp.status_code == 422


def test_upload_replaces_existing_draft(client):
    session = get_session()
    try:
        course, _ = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    first = client.post(f"/api/courses/{course.id}/curriculum/upload", json=_payload())
    assert first.status_code == 200
    version_id = first.json()["curriculum_version_id"]

    second = client.post(
        f"/api/courses/{course.id}/curriculum/upload",
        json={
            "concepts": [
                {
                    "label": "Only Skill",
                    "description": "The sole remaining skill.",
                    "prerequisites": [],
                }
            ]
        },
    )
    assert second.status_code == 200
    assert second.json()["concept_count"] == 1

    s = get_session()
    try:
        assert (
            s.query(ConceptRevision)
            .filter_by(curriculum_version_id=version_id)
            .count()
            == 1
        )
        assert (
            s.query(ConceptRelation).filter_by(curriculum_version_id=version_id).count() == 0
        )
    finally:
        s.close()


def test_upload_then_publish_exposes_learner_map(client):
    session = get_session()
    try:
        course, _ = _course_with_sections(session)
        session.commit()
    finally:
        session.close()

    upload = client.post(f"/api/courses/{course.id}/curriculum/upload", json=_payload())
    assert upload.status_code == 200
    version_id = upload.json()["curriculum_version_id"]

    publish = client.post(f"/api/curriculum/{version_id}/publish")
    assert publish.status_code == 200

    map_resp = client.get(f"/api/courses/{course.id}/skills")
    assert map_resp.status_code == 200
    nodes = {n["label"] for n in map_resp.json()["nodes"]}
    assert nodes == {"Replication", "Partitioning"}
