from __future__ import annotations

import pytest

from app.db.engine import get_session
from app.db.models import Concept, ConceptEdge, ConceptSectionLink, Section
from app.jobs.worker import run_due_jobs_once
from app.services.skills_service import derive_levels, mastery_score, status_for


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


def test_mastery_renormalizes_over_missing_signals():
    assert mastery_score(None, None, None) == 0
    assert mastery_score(1.0, None, None) == 100      # only practice present
    assert mastery_score(0.5, 0.5, 0.5) == 50
    # quiz 0.5 weight vs practice 0.3: (0.5*0 + 0.3*1)/(0.8) = 0.375
    assert mastery_score(1.0, None, 0.0) == 38


def test_status_thresholds_and_locked_gate():
    assert status_for(0, has_any_signal=False, weak_prereq=True) == "locked"
    assert status_for(0, has_any_signal=False, weak_prereq=False) == "growing"  # new, unblocked
    assert status_for(39, True, False) == "struggling"
    assert status_for(70, True, False) == "growing"
    assert status_for(71, True, False) == "solid"
