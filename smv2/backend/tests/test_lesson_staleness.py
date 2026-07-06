from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Section
from conftest import _first_section_id


def test_lesson_stale_false_when_no_lesson_yet(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    detail = client.get(f"/api/sections/{section_id}").json()
    assert detail["lesson_status"] == "none"
    assert detail["lesson_stale"] is False


def test_lesson_stale_false_when_generated_under_current_version(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    from app.jobs.worker import run_due_jobs_once

    client.post(f"/api/sections/{section_id}/lesson")
    assert run_due_jobs_once() is True

    detail = client.get(f"/api/sections/{section_id}").json()
    assert detail["lesson_status"] == "ready"
    assert detail["lesson_stale"] is False


def test_lesson_stale_true_when_prompt_version_is_older(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    session = get_session()
    try:
        section = session.get(Section, section_id)
        section.lesson_md = "An old lesson from an earlier prompt."
        section.lesson_status = "ready"
        section.lesson_prompt_version = "v0"  # lexicographically and numerically older than the current version
        session.commit()
    finally:
        session.close()

    detail = client.get(f"/api/sections/{section_id}").json()
    assert detail["lesson_stale"] is True


def test_lesson_stale_true_for_v9_vs_v10_numeric_not_lexicographic(client, ingest_course, monkeypatch):
    """'v9' > 'v10' as plain strings (lexicographic: '9' > '1'), the exact
    opposite of the numeric truth — a v9 lesson would silently be reported
    as NOT stale once the prompt reached v10 under a string comparison.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    session = get_session()
    try:
        section = session.get(Section, section_id)
        section.lesson_md = "A lesson generated under prompt v9."
        section.lesson_status = "ready"
        section.lesson_prompt_version = "v9"
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr(
        "app.services.sections_service.load_prompt", lambda name: ("current system prompt", "v10")
    )

    detail = client.get(f"/api/sections/{section_id}").json()
    assert detail["lesson_stale"] is True


def test_lesson_stale_false_for_v10_vs_v10(client, ingest_course, monkeypatch):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    session = get_session()
    try:
        section = session.get(Section, section_id)
        section.lesson_md = "A lesson generated under prompt v10."
        section.lesson_status = "ready"
        section.lesson_prompt_version = "v10"
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr(
        "app.services.sections_service.load_prompt", lambda name: ("current system prompt", "v10")
    )

    detail = client.get(f"/api/sections/{section_id}").json()
    assert detail["lesson_stale"] is False
