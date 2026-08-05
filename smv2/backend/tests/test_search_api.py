from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Course, Section


def _seed_api_course(course_id: str = "api-course") -> str:
    from app.services import search_index

    session = get_session()
    try:
        session.add(Course(id=course_id, title="API Search", status="ready"))
        for order_index, (suffix, title, body) in enumerate(
            [
                ("one", "Foundations", "alpha first"),
                ("two", "Applications", "alpha second"),
                ("other-word", "Other", "beta only"),
            ]
        ):
            section_id = f"{course_id}-{suffix}"
            section = Section(
                id=section_id,
                course_id=course_id,
                order_index=order_index,
                title=title,
                body_md=body,
                content_hash=f"hash-{section_id}",
                lesson_status="none",
            )
            if suffix == "two":
                section.lesson_md = "lessonalpha generated"
            session.add(section)
            session.flush()
            search_index.upsert_section_document(session, section)
            search_index.upsert_lesson_document(session, section)
        session.commit()
        return course_id
    finally:
        session.close()


def test_search_course_returns_results_for_valid_query(client):
    course_id = _seed_api_course()

    resp = client.get(f"/api/courses/{course_id}/search", params={"query": "alpha"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] in {"fts5", "like"}
    assert body["items"]
    assert body["items"][0]["course_id"] == course_id
    assert body["sanitized_excerpts"] is True


def test_search_rejects_empty_query(client):
    course_id = _seed_api_course("empty-query-course")

    resp = client.get(f"/api/courses/{course_id}/search", params={"query": ""})

    assert resp.status_code == 422


def test_search_is_course_scoped(client):
    course_id = _seed_api_course("scoped-course")
    _seed_api_course("other-course")

    resp = client.get(f"/api/courses/{course_id}/search", params={"query": "alpha"})

    assert resp.status_code == 200
    assert {item["course_id"] for item in resp.json()["items"]} == {course_id}


def test_search_filters_document_types(client):
    course_id = _seed_api_course("type-filter-course")

    resp = client.get(
        f"/api/courses/{course_id}/search",
        params={"query": "alpha", "document_type": "lesson"},
    )

    assert resp.status_code == 200
    assert {item["doc_type"] for item in resp.json()["items"]} == {"lesson"}


def test_search_next_cursor_round_trips(client):
    course_id = _seed_api_course("cursor-api-course")

    first_page = client.get(f"/api/courses/{course_id}/search", params={"query": "alpha", "limit": 1})
    assert first_page.status_code == 200
    token = first_page.json()["next_cursor"]
    assert token

    second_page = client.get(
        f"/api/courses/{course_id}/search",
        params={"query": "alpha", "limit": 10, "cursor": token},
    )

    assert second_page.status_code == 200
    first_ids = {item["cursor_token"] for item in first_page.json()["items"]}
    second_ids = {item["cursor_token"] for item in second_page.json()["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_search_missing_course_returns_404(client):
    resp = client.get("/api/courses/missing/search", params={"query": "alpha"})

    assert resp.status_code == 404
