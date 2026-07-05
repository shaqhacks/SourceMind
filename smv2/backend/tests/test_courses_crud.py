from __future__ import annotations


def test_course_crud_lifecycle(client):
    resp = client.post("/api/courses", json={"title": "My Course"})
    assert resp.status_code == 201
    course = resp.json()
    assert course["title"] == "My Course"
    assert course["status"] == "created"
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
