from __future__ import annotations


def test_course_crud_lifecycle(client):
    resp = client.post("/api/courses", json={"title": "My Course"})
    assert resp.status_code == 201
    course = resp.json()
    assert course["title"] == "My Course"
    assert course["status"] == "created"
    assert course["is_sample"] is False
    course_id = course["id"]

    resp = client.get("/api/courses")
    assert resp.status_code == 200
    assert any(c["id"] == course_id for c in resp.json())

    resp = client.get(f"/api/courses/{course_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == course_id

    resp = client.delete(f"/api/courses/{course_id}")
    assert resp.status_code == 204

    resp = client.get(f"/api/courses/{course_id}")
    assert resp.status_code == 404

    resp = client.delete(f"/api/courses/{course_id}")
    assert resp.status_code == 404


def test_get_missing_course_is_404(client):
    resp = client.get("/api/courses/does-not-exist")
    assert resp.status_code == 404


def test_listing_reports_real_section_and_failed_asset_counts(client, ingest_course):
    # Regression: ISSUE-001 — /api/courses serialized CourseOut's schema
    # defaults (section_count=0, failed_asset_count=0) for every course
    # because list_courses returned bare ORM rows; only the detail endpoint
    # computed the counts. Found by /qa on 2026-07-28.
    # Report: .gstack/qa-reports/qa-report-localhost-2026-07-28.md
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    listing = client.get("/api/courses").json()
    row = next(c for c in listing if c["id"] == course_id)
    detail = client.get(f"/api/courses/{course_id}").json()

    assert row["section_count"] > 0
    assert row["section_count"] == detail["section_count"]
    assert row["failed_asset_count"] == detail["failed_asset_count"]
