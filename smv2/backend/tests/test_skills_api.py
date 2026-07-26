from __future__ import annotations


def _graph(section_id):
    return {
        "concepts": [
            {
                "slug": "tokenization",
                "label": "Tokenization",
                "section_refs": [
                    {"section_id": section_id, "rank": 0, "relevance_md": "Defines tokens."}
                ],
            },
            {"slug": "counting", "label": "Token counting", "section_refs": []},
        ],
        "edges": [{"from_slug": "tokenization", "to_slug": "counting"}],
    }


def test_import_graph_creates_nodes_edges_links(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=_graph(section_id))
    assert resp.status_code == 200
    assert resp.json() == {"concept_count": 2, "edge_count": 1, "link_count": 1}


def test_import_is_idempotent_and_preserves_concept_ids(client, ingest_course):
    from conftest import _first_section_id

    from app.db.engine import get_session
    from app.db.models import Concept, ConceptMastery

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    first = client.put(f"/api/courses/{course_id}/skills/graph", json=_graph(section_id))
    assert first.status_code == 200

    session = get_session()
    try:
        concept_ids = {
            c.slug: c.id for c in session.query(Concept).filter_by(course_id=course_id).all()
        }
        session.add(
            ConceptMastery(
                course_id=course_id,
                concept_id=concept_ids["tokenization"],
                learner_key="default",
                points=10,
                correct_count=3,
                wrong_count=1,
            )
        )
        session.commit()
    finally:
        session.close()

    second = client.put(f"/api/courses/{course_id}/skills/graph", json=_graph(section_id))
    assert second.status_code == 200
    assert second.json() == {"concept_count": 2, "edge_count": 1, "link_count": 1}

    session = get_session()
    try:
        concept_ids_after = {
            c.slug: c.id for c in session.query(Concept).filter_by(course_id=course_id).all()
        }
        assert concept_ids_after == concept_ids

        mastery = session.get(
            ConceptMastery, (course_id, concept_ids["tokenization"], "default")
        )
        assert mastery is not None
        assert mastery.points == 10
    finally:
        session.close()


def test_import_rejects_cycle_with_422(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    payload = {
        "concepts": [
            {"slug": "a", "label": "A", "section_refs": []},
            {"slug": "b", "label": "B", "section_refs": []},
        ],
        "edges": [
            {"from_slug": "a", "to_slug": "b"},
            {"from_slug": "b", "to_slug": "a"},
        ],
    }
    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert resp.status_code == 422


def test_import_rejects_foreign_section_with_422(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    other_course_id, *_ = ingest_course("with_bookmarks.pdf")
    foreign_section_id = _first_section_id(client, other_course_id)

    resp = client.put(
        f"/api/courses/{course_id}/skills/graph", json=_graph(foreign_section_id)
    )
    assert resp.status_code == 422


def test_import_dedupes_duplicate_edge_pair(client, ingest_course):
    from app.db.engine import get_session
    from app.db.models import ConceptEdge

    course_id, *_ = ingest_course("with_bookmarks.pdf")

    payload = {
        "concepts": [
            {"slug": "a", "label": "A", "section_refs": []},
            {"slug": "b", "label": "B", "section_refs": []},
        ],
        "edges": [
            {"from_slug": "a", "to_slug": "b"},
            {"from_slug": "a", "to_slug": "b"},
        ],
    }
    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"concept_count": 2, "edge_count": 1, "link_count": 0}

    session = get_session()
    try:
        assert session.query(ConceptEdge).filter_by(course_id=course_id).count() == 1
    finally:
        session.close()


def test_import_dedupes_duplicate_section_ref(client, ingest_course):
    from conftest import _first_section_id

    from app.db.engine import get_session
    from app.db.models import ConceptSectionLink

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    payload = {
        "concepts": [
            {
                "slug": "tokenization",
                "label": "Tokenization",
                "section_refs": [
                    {"section_id": section_id, "rank": 0, "relevance_md": "First."},
                    {"section_id": section_id, "rank": 1, "relevance_md": "Second."},
                ],
            },
        ],
        "edges": [],
    }
    resp = client.put(f"/api/courses/{course_id}/skills/graph", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"concept_count": 1, "edge_count": 0, "link_count": 1}

    session = get_session()
    try:
        links = session.query(ConceptSectionLink).filter_by(course_id=course_id).all()
        assert len(links) == 1
        assert links[0].relevance_md == "First."
    finally:
        session.close()
