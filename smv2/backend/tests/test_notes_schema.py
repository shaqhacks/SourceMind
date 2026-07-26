from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Course, Note, Section


def test_notes_table_exists_and_persists_anchor(client):
    # client fixture runs init_db (alembic upgrade head) against the test DB.
    session = get_session()
    try:
        course = Course(id="c1", title="C", status="ready")
        section = Section(
            id="s1",
            course_id="c1",
            order_index=0,
            title="S",
            body_md="x",
            content_hash="h",
            extractor_version="v",
        )
        session.add_all([course, section])
        session.commit()

        note = Note(
            course_id="c1",
            section_id="s1",
            surface="pdf",
            page=2,
            anchor_y=0.5,
            note_md="hello",
        )
        session.add(note)
        session.commit()

        got = session.query(Note).one()
        assert got.course_id == "c1"
        assert got.section_id == "s1"
        assert got.surface == "pdf"
        assert got.page == 2
        assert got.anchor_y == 0.5
        assert got.note_md == "hello"
    finally:
        session.close()
