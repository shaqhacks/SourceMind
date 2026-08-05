from __future__ import annotations

import io
import json
import zipfile

from app.db.engine import get_session
from app.db.models import Chunk, Section
from app.jobs.worker import run_due_jobs_once


def _sections(client, course_id: str) -> list[dict]:
    return client.get(f"/api/courses/{course_id}/sections").json()


def _by_title(sections: list[dict]) -> dict[str, dict]:
    return {s["title"]: s for s in sections}


def _create_course(client, title: str = "Outline Edit Course") -> str:
    resp = client.post("/api/courses", json={"title": title})
    assert resp.status_code == 201
    return resp.json()["id"]


def _upload(client, course_id: str, filename: str, content: bytes, content_type: str) -> str:
    resp = client.post(
        f"/api/courses/{course_id}/assets",
        files={"file": (filename, content, content_type)},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _run_ingest(client, course_id: str) -> None:
    resp = client.post(f"/api/courses/{course_id}/ingest")
    assert resp.status_code == 202
    assert run_due_jobs_once() is True


def test_rename_keeps_section_id_stable(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _by_title(_sections(client, course_id))
    section_id = before["Chapter 1: Foundations"]["id"]
    original_provenance = {
        "asset_id": before["Chapter 1: Foundations"]["asset_id"],
        "page_start": before["Chapter 1: Foundations"]["page_start"],
        "page_end": before["Chapter 1: Foundations"]["page_end"],
        "source_format": before["Chapter 1: Foundations"]["source_format"],
        "source_locator": before["Chapter 1: Foundations"]["source_locator"],
    }

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "rename", "section_id": section_id, "title": "Intro"}]},
    )
    assert resp.status_code == 200
    after = _by_title(resp.json())
    assert "Intro" in after
    assert after["Intro"]["id"] == section_id
    assert {
        "asset_id": after["Intro"]["asset_id"],
        "page_start": after["Intro"]["page_start"],
        "page_end": after["Intro"]["page_end"],
        "source_format": after["Intro"]["source_format"],
        "source_locator": after["Intro"]["source_locator"],
    } == original_provenance


def test_reorder_updates_order_index(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    before = _sections(client, course_id)
    ids_reversed = [s["id"] for s in reversed(before)]
    provenance_by_id = {
        s["id"]: {
            "asset_id": s["asset_id"],
            "page_start": s["page_start"],
            "page_end": s["page_end"],
            "source_format": s["source_format"],
            "source_locator": s["source_locator"],
        }
        for s in before
    }

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "reorder", "order": ids_reversed}]},
    )
    assert resp.status_code == 200
    after = resp.json()
    assert [s["id"] for s in after] == ids_reversed
    assert [s["order_index"] for s in after] == [0, 1, 2]
    for section in after:
        assert {
            "asset_id": section["asset_id"],
            "page_start": section["page_start"],
            "page_end": section["page_end"],
            "source_format": section["source_format"],
            "source_locator": section["source_locator"],
        } == provenance_by_id[section["id"]]


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
    assert merged["asset_id"] == before["Chapter 1: Foundations"]["asset_id"]
    assert merged["source_format"] == "pdf"
    assert merged["page_start"] == before["Chapter 1: Foundations"]["page_start"]
    assert merged["page_end"] == before["Chapter 2: Structures"]["page_end"]
    assert merged["source_locator"] == {
        "type": "pdf_pages",
        "asset_id": before["Chapter 1: Foundations"]["asset_id"],
        "page_start": before["Chapter 1: Foundations"]["page_start"],
        "page_end": before["Chapter 2: Structures"]["page_end"],
    }

    session = get_session()
    try:
        merged_row = session.get(Section, merged["id"])
        assert merged_row is not None
        assert merged_row.asset_id == merged["asset_id"]
        assert merged_row.source_format == "pdf"
        assert merged_row.source_locator == merged["source_locator"]
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
    course_id, upload_resp, *_ = ingest_course("no_bookmarks.pdf")
    asset_id = upload_resp.json()["id"]
    before = _sections(client, course_id)
    assert len(before) == 1
    original_id = before[0]["id"]
    assert before[0]["page_start"] == 1 and before[0]["page_end"] == 10
    assert before[0]["asset_id"] == asset_id
    assert before[0]["source_format"] == "pdf"
    assert before[0]["source_locator"] == {
        "type": "pdf_pages",
        "asset_id": asset_id,
        "page_start": 1,
        "page_end": 10,
    }

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
    assert first["asset_id"] == second["asset_id"] == asset_id
    assert first["source_format"] == second["source_format"] == "pdf"
    assert first["source_locator"] == {
        "type": "pdf_pages",
        "asset_id": asset_id,
        "page_start": 1,
        "page_end": 5,
    }
    assert second["source_locator"] == {
        "type": "pdf_pages",
        "asset_id": asset_id,
        "page_start": 6,
        "page_end": 10,
    }

    session = get_session()
    try:
        first_row = session.get(Section, first["id"])
        second_row = session.get(Section, second["id"])
        assert first_row is not None and second_row is not None
        assert first_row.asset_id == second_row.asset_id == asset_id
        assert first_row.source_locator == first["source_locator"]
        assert second_row.source_locator == second["source_locator"]
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


def test_split_rejects_pdf_section_with_missing_locator_and_rolls_back(client, ingest_course):
    course_id, *_ = ingest_course("no_bookmarks.pdf")
    before = _sections(client, course_id)
    section_id = before[0]["id"]

    session = get_session()
    try:
        row = session.get(Section, section_id)
        row.source_locator = None
        session.commit()
    finally:
        session.close()

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "split", "section_id": section_id, "at_page": 6}]},
    )

    assert resp.status_code == 422
    after = _sections(client, course_id)
    assert [section["id"] for section in after] == [section_id]
    assert after[0]["title"] == before[0]["title"]


def test_merge_non_pdf_sections_creates_composite_locator_and_export_label(client):
    course_id = _create_course(client)
    asset_id = _upload(
        client,
        course_id,
        "units.md",
        b"# Alpha\n\nAlpha body.\n\n# Beta\n\nBeta body.\n",
        "text/markdown",
    )
    _run_ingest(client, course_id)
    before = _sections(client, course_id)

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={"operations": [{"type": "merge", "section_ids": [s["id"] for s in before]}]},
    )

    assert resp.status_code == 200
    [merged] = resp.json()
    assert merged["asset_id"] == asset_id
    assert merged["source_format"] == "markdown"
    assert merged["source_locator"] == {
        "type": "composite",
        "asset_id": asset_id,
        "locators": [
            {"type": "heading", "asset_id": asset_id, "heading_path": ["Alpha"]},
            {"type": "heading", "asset_id": asset_id, "heading_path": ["Beta"]},
        ],
    }

    session = get_session()
    try:
        row = session.get(Section, merged["id"])
        assert row is not None
        assert row.source_locator == merged["source_locator"]
        assert row.extractor_version == "markdown-stdlib-v1"
    finally:
        session.close()

    export_resp = client.get(f"/api/courses/{course_id}/export")
    assert export_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export_resp.content)) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["sections"][0]["source_locator"] == merged["source_locator"]
    assert manifest["sections"][0]["source_label"] == "Alpha + Beta"


def _assert_failed_merge_rolls_back(client, course_id: str, before: list[dict]) -> None:
    before_ids = [section["id"] for section in before]

    resp = client.patch(
        f"/api/courses/{course_id}/outline",
        json={
            "operations": [
                {"type": "rename", "section_id": before_ids[0], "title": "Renamed Before Failure"},
                {"type": "merge", "section_ids": before_ids},
            ]
        },
    )

    assert resp.status_code == 422
    after = _sections(client, course_id)
    assert [(section["id"], section["title"]) for section in after] == [
        (section["id"], section["title"]) for section in before
    ]
    assert [section["source_locator"] for section in after] == [
        section["source_locator"] for section in before
    ]
    assert [section["asset_id"] for section in after] == [section["asset_id"] for section in before]
    assert [section["source_format"] for section in after] == [
        section["source_format"] for section in before
    ]


def test_merge_rejects_cross_asset_sections_and_rolls_back(client):
    course_id = _create_course(client)
    first_asset_id = _upload(
        client,
        course_id,
        "first.md",
        b"# Alpha\n\nAlpha body.\n",
        "text/markdown",
    )
    second_asset_id = _upload(
        client,
        course_id,
        "second.md",
        b"# Beta\n\nBeta body.\n",
        "text/markdown",
    )
    assert first_asset_id != second_asset_id
    _run_ingest(client, course_id)
    before = _sections(client, course_id)
    assert [section["source_format"] for section in before] == ["markdown", "markdown"]
    assert [section["asset_id"] for section in before] == [first_asset_id, second_asset_id]

    _assert_failed_merge_rolls_back(client, course_id, before)


def test_merge_rejects_cross_format_sections_and_rolls_back(client):
    course_id = _create_course(client)
    _upload(
        client,
        course_id,
        "units.md",
        b"# Alpha\n\nAlpha body.\n\n# Beta\n\nBeta body.\n",
        "text/markdown",
    )
    _run_ingest(client, course_id)

    before = _sections(client, course_id)
    session = get_session()
    try:
        second = session.get(Section, before[1]["id"])
        second.source_format = "text"
        session.commit()
    finally:
        session.close()
    before = _sections(client, course_id)
    assert [section["source_format"] for section in before] == ["markdown", "text"]
    assert before[0]["asset_id"] == before[1]["asset_id"]

    _assert_failed_merge_rolls_back(client, course_id, before)


def test_merge_rejects_conflicting_extractor_provenance_and_rolls_back(client):
    course_id = _create_course(client)
    _upload(
        client,
        course_id,
        "units.md",
        b"# Alpha\n\nAlpha body.\n\n# Beta\n\nBeta body.\n",
        "text/markdown",
    )
    _run_ingest(client, course_id)

    before = _sections(client, course_id)
    session = get_session()
    try:
        second = session.get(Section, before[1]["id"])
        second.extractor_version = "other-extractor-v1"
        session.commit()
    finally:
        session.close()
    before = _sections(client, course_id)

    _assert_failed_merge_rolls_back(client, course_id, before)


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
