from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Concept, ConceptEdge, ConceptSectionLink, Section
from app.jobs.worker import run_due_jobs_once


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
