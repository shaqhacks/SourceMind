from __future__ import annotations

import pytest

from app.db.engine import get_session
from app.db.models import Concept, ConceptEdge, ConceptSectionLink, Section
from app.jobs.worker import run_due_jobs_once
from app.services.skills_service import derive_levels


def test_reingest_wipes_concept_graph(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    session = get_session()
    try:
        a = Concept(course_id=course_id, slug="a", label="A")
        b = Concept(course_id=course_id, slug="b", label="B")
        session.add_all([a, b])
        session.flush()
        session.add(ConceptEdge(course_id=course_id, from_concept_id=a.id, to_concept_id=b.id))
        section_id = session.query(Section).filter_by(course_id=course_id).first().id
        session.add(
            ConceptSectionLink(course_id=course_id, concept_id=a.id, section_id=section_id)
        )
        session.commit()
    finally:
        session.close()

    # Re-ingest the exact same asset again via a fresh ingest job — the
    # established idiom from test_reingest_idempotency.py.
    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True

    session = get_session()
    try:
        assert session.query(ConceptEdge).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptSectionLink).filter_by(course_id=course_id).count() == 0
    finally:
        session.close()


def test_derive_levels_longest_path_and_cycle_rejection():
    levels = derive_levels(["a", "b", "c"], [("a", "b"), ("b", "c"), ("a", "c")])
    assert levels == {"a": 1, "b": 2, "c": 3}  # c takes the LONGEST path
    with pytest.raises(ValueError):
        derive_levels(["a", "b"], [("a", "b"), ("b", "a")])


def test_derive_levels_handles_duplicate_node_ids():
    """Regression: duplicate node_ids should not cause false-positive cycle detection."""
    levels = derive_levels(["a", "b", "b"], [("a", "b")])
    assert levels == {"a": 1, "b": 2}


def test_derive_levels_rejects_edge_with_unknown_endpoint():
    """Regression: edge referencing unknown node should raise ValueError, not KeyError."""
    with pytest.raises(ValueError) as exc_info:
        derive_levels(["a", "b"], [("a", "x")])
    assert "x" in str(exc_info.value)


def test_derive_levels_handles_duplicate_roots():
    """Regression: duplicate root nodes should not inflate processed_count."""
    levels = derive_levels(["a", "a", "b"], [])
    assert levels == {"a": 1, "b": 1}


def test_derive_levels_handles_duplicate_nodes_in_diamond():
    """Regression: duplicate nodes in a DAG should be deduplicated, not cause cycle detection."""
    levels = derive_levels(["a", "a", "b", "c"], [("a", "b"), ("a", "c"), ("b", "c")])
    assert levels == {"a": 1, "b": 2, "c": 3}
