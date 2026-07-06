"""ADR-013: deterministic front-matter skipping during ingest. Uses the
front_matter.pdf fixture (title page, copyright/ISBN page, a bookmarked
"Table of Contents" page with dotted page-number lines, then 2 real
bookmarked chapters) end to end through the real ingest pipeline.
"""

from __future__ import annotations


def test_ingest_bookmark_path_drops_front_matter_and_starts_at_chapter_one(client, ingest_course):
    course_id, _, _, claimed = ingest_course("front_matter.pdf")
    assert claimed is True

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ready"
    assert course["section_count"] == 2

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert [s["title"] for s in sections] == ["Chapter 1: Real Content", "Chapter 2: More Content"]

    section = client.get(f"/api/sections/{sections[0]['id']}").json()
    assert "ISBN" not in section["body_md"]
    assert "Table of Contents" not in section["body_md"]
    assert "real first chapter" in section["body_md"]


def test_ingest_skip_front_matter_disabled_keeps_toc_bookmark_as_a_section(
    client, ingest_course, monkeypatch
):
    monkeypatch.setenv("SMV2_SKIP_FRONT_MATTER", "0")

    course_id, _, _, claimed = ingest_course("front_matter.pdf")
    assert claimed is True

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ready"
    assert course["section_count"] == 3

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert [s["title"] for s in sections] == [
        "Table of Contents",
        "Chapter 1: Real Content",
        "Chapter 2: More Content",
    ]
