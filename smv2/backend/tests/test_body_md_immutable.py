from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_session
from app.db.models import Course, Section


def test_generation_never_touches_body_md(client):
    session = get_session()
    try:
        course = Course(id=str(uuid.uuid4()), title="FK Test Course", status="created")
        session.add(course)
        session.flush()

        section = Section(
            id=f"section-{uuid.uuid4().hex[:12]}",
            course_id=course.id,
            order_index=0,
            title="Intro",
            body_md="Original source text.",
            content_hash="hash-original",
        )
        session.add(section)
        session.commit()
        section_id = section.id

        # (1) ORM path: reassigning body_md on a persisted instance is blocked
        # in Python before any SQL is even sent.
        with pytest.raises(ValueError):
            section.body_md = "Mutated via ORM."
    finally:
        session.close()

    # (2) raw-SQL path: bypassing the ORM entirely still hits the DB-level
    # trigger, which aborts the statement with an IntegrityError.
    session = get_session()
    try:
        with pytest.raises(IntegrityError):
            session.execute(
                text("UPDATE sections SET body_md = :new WHERE id = :id"),
                {"new": "Mutated via raw SQL.", "id": section_id},
            )
        session.rollback()
    finally:
        session.close()

    # (3) lesson_md is the one sanctioned generated-content column.
    session = get_session()
    try:
        section = session.get(Section, section_id)
        section.lesson_md = "Generated lesson content."
        session.commit()

        refreshed = session.get(Section, section_id)
        assert refreshed.lesson_md == "Generated lesson content."
        assert refreshed.body_md == "Original source text."
    finally:
        session.close()
