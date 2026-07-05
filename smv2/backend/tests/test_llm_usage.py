from __future__ import annotations

from app.db.engine import get_session
from app.db.models import LlmCall, utcnow


def _seed_call(course_id, input_tokens, output_tokens, cost) -> None:
    session = get_session()
    try:
        session.add(
            LlmCall(
                ts=utcnow(),
                purpose="lesson",
                model="claude-sonnet-5",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=100,
                cost_estimate=cost,
                status="ok",
                course_id=course_id,
            )
        )
        session.commit()
    finally:
        session.close()


def test_llm_usage_aggregates_across_courses_by_default(client):
    resp = client.post("/api/courses", json={"title": "Course A"})
    course_a = resp.json()["id"]
    resp = client.post("/api/courses", json={"title": "Course B"})
    course_b = resp.json()["id"]

    _seed_call(course_a, 100, 200, 0.01)
    _seed_call(course_b, 300, 400, 0.02)

    resp = client.get("/api/llm/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["calls"] == 2
    assert body["input_tokens"] == 400
    assert body["output_tokens"] == 600
    assert round(body["est_cost_usd"], 4) == 0.03


def test_llm_usage_filters_by_course_id(client):
    resp = client.post("/api/courses", json={"title": "Course A"})
    course_a = resp.json()["id"]
    resp = client.post("/api/courses", json={"title": "Course B"})
    course_b = resp.json()["id"]

    _seed_call(course_a, 100, 200, 0.01)
    _seed_call(course_b, 999, 999, 9.99)

    resp = client.get(f"/api/llm/usage?course_id={course_a}")
    body = resp.json()
    assert body["calls"] == 1
    assert body["input_tokens"] == 100
    assert body["output_tokens"] == 200
    assert round(body["est_cost_usd"], 4) == 0.01


def test_llm_usage_empty_when_no_calls(client):
    resp = client.get("/api/llm/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"calls": 0, "input_tokens": 0, "output_tokens": 0, "est_cost_usd": 0.0}
