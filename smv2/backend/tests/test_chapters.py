"""ADR-017: chapters API — sections + test_attempts grouped by
chapter_label, split by kind (content/practice/answers).
"""

from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Section


def test_list_chapters_groups_and_splits_by_kind(client, ingest_course):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")

    resp = client.get(f"/api/courses/{course_id}/chapters")
    assert resp.status_code == 200
    chapters = resp.json()

    assert [c["chapter_label"] for c in chapters] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
        "Chapter 4: Geometry",
    ]

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    by_title = {s["title"]: s["id"] for s in sections}

    chapter_1 = chapters[0]
    assert chapter_1["section_ids"] == [by_title["Chapter 1: Foundations"]]
    assert chapter_1["practice_section_ids"] == [by_title["0.1 Practice - Foundations"]]
    assert chapter_1["answers_section_ids"] == [by_title["Answers - Chapter 1"]]
    assert chapter_1["test_stats"] is None

    chapter_2 = chapters[1]
    assert chapter_2["section_ids"] == [by_title["Chapter 2: Structures"]]
    assert chapter_2["practice_section_ids"] == []
    assert chapter_2["answers_section_ids"] == []


def test_list_chapters_404_for_missing_course(client):
    resp = client.get("/api/courses/does-not-exist/chapters")
    assert resp.status_code == 404


def test_list_chapters_null_group_sorts_first(client):
    """A course with a mix of a NULL-labeled section (no detected chapter
    marker at all -- "Front matter", labeled client-side) and a real
    chapter group puts the NULL group first, regardless of order_index.
    """
    resp = client.post("/api/courses", json={"title": "Grouping Test"})
    course_id = resp.json()["id"]

    session = get_session()
    try:
        session.add(
            Section(
                id="s-labeled",
                course_id=course_id,
                order_index=0,
                title="Chapter 1: Foundations",
                body_md="x",
                content_hash="h1",
                kind="content",
                chapter_label="Chapter 1: Foundations",
            )
        )
        session.add(
            Section(
                id="s-unlabeled",
                course_id=course_id,
                order_index=1,
                title="A stray unclassified section",
                body_md="y",
                content_hash="h2",
                kind="content",
                chapter_label=None,
            )
        )
        session.commit()
    finally:
        session.close()

    resp = client.get(f"/api/courses/{course_id}/chapters")
    chapters = resp.json()
    assert [c["chapter_label"] for c in chapters] == [None, "Chapter 1: Foundations"]
    assert chapters[0]["section_ids"] == ["s-unlabeled"]
