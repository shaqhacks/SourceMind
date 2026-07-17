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


def test_highlights_crud_roundtrip(client, ingest_course):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    first, second = sections[0], sections[1]

    created = client.post(
        f"/api/courses/{course_id}/highlights",
        json={
            "section_id": second["id"],
            "exact": "any selected text",
            "prefix": "before ",
            "suffix": " after",
            "occurrence": 0,
            "page": second["page_start"],
            "color": "green",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["color"] == "green"
    assert body["note_md"] is None
    # 1-based in, 1-based out — the DB's 0-based storage never leaks.
    assert body["page"] == second["page_start"]

    later = client.post(
        f"/api/courses/{course_id}/highlights",
        json={"section_id": first["id"], "exact": "other selected text"},
    )
    assert later.status_code == 201

    listed = client.get(f"/api/courses/{course_id}/highlights").json()
    # Ordered by section order_index then created_at — NOT insertion order.
    assert [h["section_id"] for h in listed] == [first["id"], second["id"]]

    hid = body["id"]
    patched = client.patch(f"/api/highlights/{hid}", json={"note_md": "why does this matter?"})
    assert patched.status_code == 200
    assert patched.json()["note_md"] == "why does this matter?"
    assert patched.json()["color"] == "green"  # untouched: PATCH is exclude_unset

    cleared = client.patch(f"/api/highlights/{hid}", json={"note_md": None})
    assert cleared.status_code == 200
    assert cleared.json()["note_md"] is None

    assert client.delete(f"/api/highlights/{hid}").status_code == 204
    assert client.patch(f"/api/highlights/{hid}", json={"color": "pink"}).status_code == 404
    assert client.delete(f"/api/highlights/{hid}").status_code == 404


def test_highlight_validation(client, ingest_course):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    other = client.post("/api/courses", json={"title": "Other"}).json()["id"]
    section_id = client.get(f"/api/courses/{course_id}/sections").json()[0]["id"]

    assert client.get("/api/courses/nope/highlights").status_code == 404
    assert client.post(
        "/api/courses/nope/highlights", json={"section_id": section_id, "exact": "x"}
    ).status_code == 404

    # Section from a different course -> 422, same contract as save_progress.
    resp = client.post(
        f"/api/courses/{other}/highlights",
        json={"section_id": section_id, "exact": "x"},
    )
    assert resp.status_code == 422

    # Pydantic-level rejects: empty exact, unknown color, 0 page (1-based API).
    for bad in (
        {"section_id": section_id, "exact": ""},
        {"section_id": section_id, "exact": "x", "color": "mauve"},
        {"section_id": section_id, "exact": "x", "page": 0},
    ):
        assert client.post(f"/api/courses/{course_id}/highlights", json=bad).status_code == 422
