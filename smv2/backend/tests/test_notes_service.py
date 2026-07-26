from __future__ import annotations

import pytest

from app.services import notes_service


def _seed_course_section(client):
    from app.db.engine import get_session
    from app.db.models import Course, Section

    session = get_session()
    try:
        session.add(Course(id="c1", title="C", status="ready"))
        session.add(
            Section(
                id="s1",
                course_id="c1",
                order_index=0,
                title="S",
                body_md="x",
                content_hash="h",
                extractor_version="v",
            )
        )
        session.commit()
    finally:
        session.close()


def test_create_and_list_round_trips_page_1_based(client):
    _seed_course_section(client)
    created = notes_service.create_note(
        "c1", section_id="s1", page=3, anchor_y=0.25, note_md="hi", surface="pdf"
    )
    assert created["page"] == 3  # 1-based out
    assert created["anchor_y"] == 0.25
    listed = notes_service.list_notes("c1")
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]
    assert listed[0]["page"] == 3
    assert listed[0]["note_md"] == "hi"


def test_create_rejects_section_from_other_course(client):
    _seed_course_section(client)
    with pytest.raises(notes_service.InvalidSectionForCourseError):
        notes_service.create_note(
            "c1",
            section_id="does-not-belong",
            page=1,
            anchor_y=0.1,
            note_md="x",
            surface="pdf",
        )


def test_update_and_delete(client):
    _seed_course_section(client)
    n = notes_service.create_note(
        "c1", section_id="s1", page=1, anchor_y=0.1, note_md="a", surface="pdf"
    )
    updated = notes_service.update_note(n["id"], {"note_md": "b"})
    assert updated["note_md"] == "b"
    assert notes_service.delete_note(n["id"]) is True
    assert notes_service.list_notes("c1") == []
