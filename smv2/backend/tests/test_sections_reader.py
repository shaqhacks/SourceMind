from __future__ import annotations


def test_list_sections_shape(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    resp = client.get(f"/api/courses/{course_id}/sections")
    assert resp.status_code == 200
    sections = resp.json()
    assert len(sections) == 3
    for s in sections:
        assert set(s) == {
            "id",
            "title",
            "order_index",
            "page_start",
            "page_end",
            "lesson_status",
            "has_content",
            "word_count",
        }
        assert s["lesson_status"] == "none"
        assert s["has_content"] is True
        assert s["word_count"] > 0


def test_list_sections_404_for_missing_course(client):
    resp = client.get("/api/courses/does-not-exist/sections")
    assert resp.status_code == 404


def test_get_section_returns_full_body(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = client.get(f"/api/courses/{course_id}/sections").json()[0]["id"]

    resp = client.get(f"/api/sections/{section_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == section_id
    assert body["course_id"] == course_id
    assert "Chapter 1: Foundations" in body["body_md"]
    assert body["lesson_md"] is None
    assert body["lesson_model"] is None
    assert body["lesson_prompt_version"] is None
    assert body["extractor_version"].startswith("pymupdf4llm-")


def test_get_section_404_for_missing_section(client):
    resp = client.get("/api/sections/does-not-exist")
    assert resp.status_code == 404


def test_progress_defaults_to_nulls_before_any_save(client):
    resp = client.post("/api/courses", json={"title": "Progress Course"})
    course_id = resp.json()["id"]

    resp = client.get(f"/api/courses/{course_id}/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "course_id": course_id,
        "section_id": None,
        "scroll_pos": 0.0,
        "updated_at": None,
    }


def test_save_and_get_progress_round_trips(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = client.get(f"/api/courses/{course_id}/sections").json()[1]["id"]

    resp = client.put(
        f"/api/courses/{course_id}/progress",
        json={"section_id": section_id, "scroll_pos": 0.42},
    )
    assert resp.status_code == 200
    saved = resp.json()
    assert saved["section_id"] == section_id
    assert saved["scroll_pos"] == 0.42
    assert saved["updated_at"] is not None

    resp = client.get(f"/api/courses/{course_id}/progress")
    assert resp.json()["section_id"] == section_id
    assert resp.json()["scroll_pos"] == 0.42


def test_save_progress_upserts_not_duplicates(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()

    client.put(f"/api/courses/{course_id}/progress", json={"section_id": sections[0]["id"], "scroll_pos": 0.1})
    resp = client.put(f"/api/courses/{course_id}/progress", json={"section_id": sections[2]["id"], "scroll_pos": 0.9})
    assert resp.status_code == 200

    final = client.get(f"/api/courses/{course_id}/progress").json()
    assert final["section_id"] == sections[2]["id"]
    assert final["scroll_pos"] == 0.9


def test_save_progress_rejects_section_from_a_different_course(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    other_course_id, *_ = ingest_course("no_bookmarks.pdf")
    other_section_id = client.get(f"/api/courses/{other_course_id}/sections").json()[0]["id"]

    resp = client.put(
        f"/api/courses/{course_id}/progress",
        json={"section_id": other_section_id, "scroll_pos": 0.5},
    )
    assert resp.status_code == 422


def test_save_progress_rejects_nonexistent_section(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    resp = client.put(
        f"/api/courses/{course_id}/progress",
        json={"section_id": "does-not-exist", "scroll_pos": 0.5},
    )
    assert resp.status_code == 422


def test_progress_404_for_missing_course(client):
    assert client.get("/api/courses/does-not-exist/progress").status_code == 404
    assert client.put("/api/courses/does-not-exist/progress", json={"scroll_pos": 0.0}).status_code == 404


def test_get_course_detail_includes_section_count_and_progress(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = client.get(f"/api/courses/{course_id}/sections").json()[0]["id"]
    client.put(f"/api/courses/{course_id}/progress", json={"section_id": section_id, "scroll_pos": 0.5})

    detail = client.get(f"/api/courses/{course_id}").json()
    assert detail["section_count"] == 3
    assert detail["progress"]["section_id"] == section_id
    assert detail["progress"]["scroll_pos"] == 0.5


def test_get_course_detail_progress_none_before_any_save(client):
    resp = client.post("/api/courses", json={"title": "No Progress Yet"})
    course_id = resp.json()["id"]
    detail = client.get(f"/api/courses/{course_id}").json()
    assert detail["section_count"] == 0
    assert detail["progress"] is None
