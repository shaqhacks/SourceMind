from __future__ import annotations

import pytest

from app.services.learner_context import LEGACY_LOCAL_LEARNER_ID

LEARNER_ID = LEGACY_LOCAL_LEARNER_ID


@pytest.fixture(autouse=True)
def _scope_skill_api_client(client):
    from conftest import _set_learner_cookie

    _set_learner_cookie(client, LEARNER_ID)


def _graph(section_id: str) -> dict:
    return {
        "concepts": [
            {
                "slug": "tokenization",
                "label": "Tokenization",
                "section_refs": [
                    {
                        "section_id": section_id,
                        "rank": 0,
                        "relevance_md": "Defines tokens.",
                    }
                ],
            },
            {"slug": "counting", "label": "Token counting", "section_refs": []},
        ],
        "edges": [{"from_slug": "tokenization", "to_slug": "counting"}],
    }


def test_import_graph_creates_nodes_edges_links(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    response = client.put(
        f"/api/courses/{course_id}/skills/graph",
        json=_graph(_first_section_id(client, course_id)),
    )
    assert response.status_code == 200
    assert response.json() == {"concept_count": 2, "edge_count": 1, "link_count": 1}


def test_import_is_idempotent_and_preserves_concept_ids(client, ingest_course):
    from conftest import _first_section_id
    from app.db.engine import get_session
    from app.db.models import Concept

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    payload = _graph(_first_section_id(client, course_id))
    assert client.put(f"/api/courses/{course_id}/skills/graph", json=payload).status_code == 200

    session = get_session()
    try:
        before = {
            concept.slug: concept.id
            for concept in session.query(Concept).filter_by(course_id=course_id).all()
        }
    finally:
        session.close()

    response = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert response.status_code == 200

    session = get_session()
    try:
        after = {
            concept.slug: concept.id
            for concept in session.query(Concept).filter_by(course_id=course_id).all()
        }
        assert after == before
    finally:
        session.close()


@pytest.mark.parametrize(
    "payload",
    [
        {
            "concepts": [
                {"slug": "a", "label": "A", "section_refs": []},
                {"slug": "b", "label": "B", "section_refs": []},
            ],
            "edges": [
                {"from_slug": "a", "to_slug": "b"},
                {"from_slug": "b", "to_slug": "a"},
            ],
        },
        {
            "concepts": [
                {"slug": "a", "label": "A", "section_refs": []},
                {"slug": "a", "label": "Again", "section_refs": []},
            ],
            "edges": [],
        },
        {
            "concepts": [{"slug": "a", "label": "A", "section_refs": []}],
            "edges": [{"from_slug": "a", "to_slug": "missing"}],
        },
    ],
)
def test_import_rejects_invalid_graphs(client, ingest_course, payload):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    response = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert response.status_code == 422


def test_import_rejects_foreign_section(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    other_course_id, *_ = ingest_course("with_bookmarks.pdf")
    response = client.put(
        f"/api/courses/{course_id}/skills/graph",
        json=_graph(_first_section_id(client, other_course_id)),
    )
    assert response.status_code == 422


def test_import_dedupes_edges_and_section_links(client, ingest_course):
    from conftest import _first_section_id
    from app.db.engine import get_session
    from app.db.models import ConceptEdge, ConceptSectionLink

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    payload = _graph(section_id)
    payload["edges"].append(dict(payload["edges"][0]))
    payload["concepts"][0]["section_refs"].append(
        {"section_id": section_id, "rank": 1, "relevance_md": "Duplicate."}
    )

    response = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert response.status_code == 200
    assert response.json() == {"concept_count": 2, "edge_count": 1, "link_count": 1}

    session = get_session()
    try:
        assert session.query(ConceptEdge).filter_by(course_id=course_id).count() == 1
        links = session.query(ConceptSectionLink).filter_by(course_id=course_id).all()
        assert len(links) == 1
        assert links[0].relevance_md == "Defines tokens."
    finally:
        session.close()


def test_read_endpoints_use_evidence_contract_without_legacy_mastery(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    assert (
        client.put(f"/api/courses/{course_id}/skills/graph", json=_graph(section_id)).status_code
        == 200
    )

    response = client.get(f"/api/courses/{course_id}/skills")
    assert response.status_code == 200
    body = response.json()
    nodes = {node["slug"]: node for node in body["nodes"]}
    assert set(nodes) == {"tokenization", "counting"}
    assert nodes["tokenization"]["level"] == 1
    assert nodes["counting"]["level"] == 2
    for node in nodes.values():
        assert node["readiness_estimate"] is None
        assert node["evidence_state"] == "insufficient_evidence"
        assert node["status"] == "insufficient_evidence"
        assert "mastery" not in node
        assert "blocked" not in node
        assert "unlock_note" not in node

    edge = body["edges"][0]
    assert edge == {
        "from_id": nodes["tokenization"]["id"],
        "to_id": nodes["counting"]["id"],
        "kind": "review_suggested",
    }

    detail_response = client.get(
        f"/api/courses/{course_id}/skills/{nodes['tokenization']['id']}"
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["taught_in"][0]["section_id"] == section_id
    assert detail["taught_in"][0]["relevance_md"] == "Defines tokens."
    assert detail["missed_questions"] == []
    assert detail["cards_count"] == 0
    assert detail["quiz_correct"] == 0
    assert detail["quiz_wrong"] == 0
    assert "fix_plan" not in detail
    assert "blocked_skill_labels" not in detail


def test_skill_endpoints_return_404_for_missing_resources(client, ingest_course):
    from app.db.engine import get_session
    from app.db.models import Concept

    assert client.get("/api/courses/does-not-exist/skills").status_code == 404
    assert client.get("/api/courses/does-not-exist/skills/concept").status_code == 404

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    other_course_id, *_ = ingest_course("with_bookmarks.pdf")
    session = get_session()
    try:
        foreign = Concept(course_id=other_course_id, slug="foreign", label="Foreign")
        session.add(foreign)
        session.commit()
        foreign_id = foreign.id
    finally:
        session.close()

    assert client.get(f"/api/courses/{course_id}/skills/{foreign_id}").status_code == 404
    assert client.get(f"/api/courses/{course_id}/skills/missing").status_code == 404


def test_import_graph_bounds_rejected_with_422(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    payload = {
        "concepts": [
            {"slug": f"c-{index}", "label": "Concept", "section_refs": []}
            for index in range(501)
        ],
        "edges": [],
    }
    response = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert response.status_code == 422


def test_import_graph_404_for_missing_course(client):
    response = client.put(
        "/api/courses/does-not-exist/skills/graph",
        json={"concepts": [], "edges": []},
    )
    assert response.status_code == 404
