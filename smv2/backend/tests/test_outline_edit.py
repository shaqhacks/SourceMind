from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Chunk


def _sections(client, course_id: str) -> list[dict]:
    return client.get(f"/api/courses/{course_id}/sections").json()


def _by_title(sections: list[dict]) -> dict[str, dict]:
    return {s["title"]: s for s in sections}


def test_rename_keeps_section_id_stable(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _by_title(_sections(client, course_id))
    section_id = before["Chapter 1: Foundations"]["id"]

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "rename", "section_id": section_id, "title": "Intro"}]},
    )
    assert resp.status_code == 200
    after = _by_title(resp.json())
    assert "Intro" in after
    assert after["Intro"]["id"] == section_id


def test_reorder_updates_order_index(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _sections(client, course_id)
    ids_reversed = [s["id"] for s in reversed(before)]

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "reorder", "order": ids_reversed}]},
    )
    assert resp.status_code == 200
    after = resp.json()
    assert [s["id"] for s in after] == ids_reversed
    assert [s["order_index"] for s in after] == [0, 1, 2]


def test_reorder_rejects_partial_list(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _sections(client, course_id)
    partial = [s["id"] for s in before[:2]]  # missing the third section's id

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "reorder", "order": partial}]},
    )
    assert resp.status_code == 422


def test_reorder_rejects_duplicate_ids(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _sections(client, course_id)
    duplicated = [before[0]["id"], before[0]["id"], before[1]["id"]]

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "reorder", "order": duplicated}]},
    )
    assert resp.status_code == 422


def test_reorder_rejects_unknown_extra_id(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _sections(client, course_id)
    with_extra = [s["id"] for s in before] + ["not-a-real-section-id"]

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "reorder", "order": with_extra}]},
    )
    assert resp.status_code == 422


def test_delete_removes_section(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _by_title(_sections(client, course_id))
    section_id = before["Chapter 2: Structures"]["id"]

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "delete", "section_id": section_id}]},
    )
    assert resp.status_code == 200
    after = _by_title(resp.json())
    assert "Chapter 2: Structures" not in after
    assert len(after) == 2


def test_merge_adjacent_sections_produces_new_id_and_rederives_chunks(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _by_title(_sections(client, course_id))
    id1 = before["Chapter 1: Foundations"]["id"]
    id2 = before["Chapter 2: Structures"]["id"]
    id3 = before["Chapter 3: Applications"]["id"]

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "merge", "section_ids": [id1, id2]}]},
    )
    assert resp.status_code == 200
    after = resp.json()
    assert len(after) == 2  # merged + chapter 3

    merged = next(s for s in after if s["id"] not in {id1, id2, id3})
    assert merged["id"] != id1 and merged["id"] != id2
    assert "Chapter 1: Foundations" in merged["title"]
    assert "Chapter 2: Structures" in merged["title"]

    session = get_session()
    try:
        merged_chunks = session.query(Chunk).filter(Chunk.section_id == merged["id"]).all()
        assert len(merged_chunks) > 0
        # Chapter 3 (untouched by the merge) keeps its own original chunks.
        ch3_chunks = session.query(Chunk).filter(Chunk.section_id == id3).all()
        assert len(ch3_chunks) > 0
    finally:
        session.close()


def test_merge_requires_adjacent_sections(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _by_title(_sections(client, course_id))
    id1 = before["Chapter 1: Foundations"]["id"]
    id3 = before["Chapter 3: Applications"]["id"]

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "merge", "section_ids": [id1, id3]}]},
    )
    assert resp.status_code == 422


def test_split_section_produces_two_new_ids_with_affected_only_rederivation(client, ingest_course):
    course_id, *_ = ingest_course("no_bookmarks.pdf")
    before = _sections(client, course_id)
    assert len(before) == 1
    original_id = before[0]["id"]
    assert before[0]["page_start"] == 1 and before[0]["page_end"] == 10

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "split", "section_id": original_id, "at_page": 6}]},
    )
    assert resp.status_code == 200
    after = resp.json()
    assert len(after) == 2

    first, second = sorted(after, key=lambda s: s["order_index"])
    assert first["id"] != original_id
    assert second["id"] != original_id
    assert first["page_start"] == 1 and first["page_end"] == 5
    assert second["page_start"] == 6 and second["page_end"] == 10

    session = get_session()
    try:
        assert session.query(Chunk).filter(Chunk.section_id == first["id"]).count() > 0
        assert session.query(Chunk).filter(Chunk.section_id == second["id"]).count() > 0
    finally:
        session.close()


def test_split_rejects_at_page_outside_range(client, ingest_course):
    course_id, *_ = ingest_course("no_bookmarks.pdf")
    section_id = _sections(client, course_id)[0]["id"]

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "split", "section_id": section_id, "at_page": 1}]},
    )
    assert resp.status_code == 422


def test_edit_outline_409_while_course_is_mid_ingest(client):
    resp = client.post("/api/courses", json={"title": "Mid Ingest Course"})
    course_id = resp.json()["id"]

    from app.services import courses_service

    courses_service.set_course_status(course_id, "ingesting")

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "rename", "section_id": "whatever", "title": "x"}]},
    )
    assert resp.status_code == 409


def test_edit_outline_404_for_missing_course(client):
    resp = client.patch(
        "/api/courses/does-not-exist/outline",
        json={"operations": []},
    )
    assert resp.status_code == 404
