from __future__ import annotations


def test_create_list_update_delete_note(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    create = client.post(
        f"/api/courses/{course_id}/notes",
        json={
            "section_id": section_id,
            "page": 2,
            "anchor_y": 0.4,
            "note_md": "hi",
            "surface": "pdf",
        },
    )
    assert create.status_code == 201
    note = create.json()
    assert note["page"] == 2
    assert note["anchor_y"] == 0.4

    listed = client.get(f"/api/courses/{course_id}/notes")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    patched = client.patch(f"/api/notes/{note['id']}", json={"note_md": "bye"})
    assert patched.status_code == 200
    assert patched.json()["note_md"] == "bye"

    deleted = client.delete(f"/api/notes/{note['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/courses/{course_id}/notes").json() == []


def test_create_note_bad_anchor_is_422(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    resp = client.post(
        f"/api/courses/{course_id}/notes",
        json={
            "section_id": section_id,
            "page": 1,
            "anchor_y": 1.5,
            "note_md": "x",
            "surface": "pdf",
        },
    )
    assert resp.status_code == 422


def test_create_note_missing_course_is_404(client):
    resp = client.post(
        "/api/courses/nope/notes",
        json={"section_id": "s", "page": 1, "anchor_y": 0.1, "note_md": "x", "surface": "pdf"},
    )
    assert resp.status_code == 404


def test_reingest_wipes_notes(client, ingest_course):
    from conftest import _first_section_id

    from app.jobs.worker import run_due_jobs_once

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    create = client.post(
        f"/api/courses/{course_id}/notes",
        json={"section_id": section_id, "page": 1, "anchor_y": 0.3, "note_md": "keep?", "surface": "pdf"},
    )
    assert create.status_code == 201
    assert len(client.get(f"/api/courses/{course_id}/notes").json()) == 1

    # Identical re-ingest KEEPS every section row (same content-addressed ids),
    # so FK cascade never fires — only the explicit REPLACED-bucket delete in
    # _run_ingest wipes notes. That explicit delete is what this asserts.
    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True
    assert client.get(f"/api/courses/{course_id}/notes").json() == []
