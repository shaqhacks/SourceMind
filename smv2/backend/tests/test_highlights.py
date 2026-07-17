from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Course, Highlight, Section


def _make_highlight(course_id: str, section_id: str, **overrides) -> str:
    session = get_session()
    try:
        h = Highlight(
            course_id=course_id,
            section_id=section_id,
            exact=overrides.get("exact", "any selected text"),
            prefix=overrides.get("prefix", ""),
            suffix=overrides.get("suffix", ""),
            occurrence=overrides.get("occurrence", 0),
            page=overrides.get("page"),
            color=overrides.get("color", "yellow"),
            note_md=overrides.get("note_md"),
        )
        session.add(h)
        session.commit()
        return h.id
    finally:
        session.close()


def _highlight_count(course_id: str) -> int:
    session = get_session()
    try:
        return session.query(Highlight).filter(Highlight.course_id == course_id).count()
    finally:
        session.close()


def _first_section_id(course_id: str) -> str:
    session = get_session()
    try:
        return session.query(Section.id).filter(Section.course_id == course_id).first()[0]
    finally:
        session.close()


def test_highlight_persists_and_cascades_with_course(ingest_course):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(course_id)

    _make_highlight(course_id, section_id, note_md="remember this")
    assert _highlight_count(course_id) == 1

    # DB-level FK cascade (PRAGMA foreign_keys is ON engine-wide, see
    # test_pragmas.py) — deleting the course row must take highlights with it.
    session = get_session()
    try:
        session.delete(session.get(Course, course_id))
        session.commit()
    finally:
        session.close()
    assert _highlight_count(course_id) == 0


def test_reingest_wipes_highlights(client, ingest_course):
    from app.jobs.worker import run_due_jobs_once

    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    _make_highlight(course_id, _first_section_id(course_id))
    assert _highlight_count(course_id) == 1

    # Identical re-ingest: the section diff KEEPS every section row (same
    # content-addressed ids), so FK cascade never fires — only the explicit
    # REPLACED-bucket delete in _run_ingest can wipe these rows. That
    # explicit delete is exactly what this asserts.
    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True
    assert _highlight_count(course_id) == 0
