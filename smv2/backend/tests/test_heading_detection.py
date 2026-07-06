"""ADR-015: heading-detection middle tier (bookmarks -> heading detection ->
page windows). Uses the headings_no_bookmarks.pdf fixture (no embedded
bookmarks; 4 chapters signaled only by large bold "Chapter N: Title"
lines, including two whose headings share a single page, plus one
large-font non-heading trap ending in a period) end to end through the
real ingest pipeline.
"""

from __future__ import annotations


def test_ingest_detects_chapters_by_heading_when_no_bookmarks(client, ingest_course):
    course_id, _, _, claimed = ingest_course("headings_no_bookmarks.pdf")
    assert claimed is True

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ready"
    assert course["section_count"] == 4

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert [s["title"] for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
        "Chapter 4: Practice",
    ]
    # Display pages are 1-based (DB is 0-based) -- matches the golden
    # snapshot's 0-based page_start/page_end + 1.
    assert (sections[0]["page_start"], sections[0]["page_end"]) == (1, 4)
    assert (sections[1]["page_start"], sections[1]["page_end"]) == (5, 5)  # claims the shared page
    assert (sections[2]["page_start"], sections[2]["page_end"]) == (6, 8)  # bumped to the next page
    assert (sections[3]["page_start"], sections[3]["page_end"]) == (9, 12)


def test_ingest_heading_trap_stays_inside_chapter_body_not_its_own_section(client, ingest_course):
    """The large-font pull-quote ending in a period must never become its
    own section -- it's real body content, just styled like a heading.
    """
    course_id, _, _, claimed = ingest_course("headings_no_bookmarks.pdf")
    assert claimed is True

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    chapter_1 = next(s for s in sections if s["title"] == "Chapter 1: Foundations")
    detail = client.get(f"/api/sections/{chapter_1['id']}").json()
    assert "Deterministic fixtures make regressions visible." in detail["body_md"]
