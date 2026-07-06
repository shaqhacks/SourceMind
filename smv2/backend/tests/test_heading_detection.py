"""ADR-015: heading-detection middle tier (bookmarks -> heading detection ->
page windows). Uses the headings_no_bookmarks.pdf fixture (no embedded
bookmarks; 5 chapters signaled only by large bold "Chapter N: Title"
lines, including two whose headings share a single page, plus one
large-font non-heading trap ending in a period, plus a practice sheet, an
answer key (ADR-017), and a ToC-shaped chapter cover page (ADR-021) --
end to end through the real ingest pipeline.
"""

from __future__ import annotations


def test_ingest_detects_chapters_by_heading_when_no_bookmarks(client, ingest_course):
    course_id, _, _, claimed = ingest_course("headings_no_bookmarks.pdf")
    assert claimed is True

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ready"
    assert course["section_count"] == 7

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert [s["title"] for s in sections] == [
        "Chapter 1: Foundations",
        "0.1 Practice - Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
        "Chapter 4: Geometry",
        "5.1 Basic Probability",
        "Answers - Chapter 1",
    ]
    # Display pages are 1-based (DB is 0-based) -- matches the golden
    # snapshot's 0-based page_start/page_end + 1. Chapter 5's own cover
    # page (page 13, 1-based) is a ToC-shaped chapter cover (ADR-021) and
    # is dropped entirely -- "5.1 Basic Probability" is what's left of
    # Chapter 5, correctly still labeled under it (see test_chapters.py).
    assert (sections[0]["page_start"], sections[0]["page_end"]) == (1, 3)
    assert (sections[1]["page_start"], sections[1]["page_end"]) == (4, 5)
    assert (sections[2]["page_start"], sections[2]["page_end"]) == (6, 6)  # claims the shared page
    assert (sections[3]["page_start"], sections[3]["page_end"]) == (7, 9)  # bumped to the next page
    assert (sections[4]["page_start"], sections[4]["page_end"]) == (10, 12)
    assert (sections[5]["page_start"], sections[5]["page_end"]) == (14, 14)  # cover (p.13) dropped
    assert (sections[6]["page_start"], sections[6]["page_end"]) == (15, 16)


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


def test_ingest_classifies_section_kind_and_chapter_label(client, ingest_course):
    """ADR-017: deterministic title-based classification, wired end to end
    through ingest. The answer key sits at the book's end (after Chapter 4)
    but names Chapter 1 in its own title -- that override must win over
    its position.
    """
    course_id, _, _, claimed = ingest_course("headings_no_bookmarks.pdf")
    assert claimed is True

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    by_title = {s["title"]: s for s in sections}

    assert by_title["Chapter 1: Foundations"]["kind"] == "content"
    assert by_title["Chapter 1: Foundations"]["chapter_label"] == "Chapter 1: Foundations"

    assert by_title["0.1 Practice - Foundations"]["kind"] == "practice"
    assert by_title["0.1 Practice - Foundations"]["chapter_label"] == "Chapter 1: Foundations"

    assert by_title["Chapter 4: Geometry"]["kind"] == "content"
    assert by_title["Chapter 4: Geometry"]["chapter_label"] == "Chapter 4: Geometry"

    assert by_title["Answers - Chapter 1"]["kind"] == "answers"
    # Override: its own title names chapter 1, not the chapter it
    # physically follows (chapter 4).
    assert by_title["Answers - Chapter 1"]["chapter_label"] == "Chapter 1: Foundations"
