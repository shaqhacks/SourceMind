from __future__ import annotations

from app.db.engine import get_session
from app.db.models import LlmCall, utcnow
from conftest import _first_section_id


def test_estimate_uses_deterministic_default_with_no_history(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    resp = client.get(f"/api/sections/{section_id}/lesson/estimate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["est_seconds"] == 30.0
    assert body["based_on_calls"] == 0
    assert body["est_cost_usd"] is not None  # derivable from body length + default model pricing


def test_estimate_uses_rolling_average_from_recent_lesson_calls(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    session = get_session()
    try:
        for latency_ms, cost in [(2000, 0.01), (4000, 0.02)]:
            session.add(
                LlmCall(
                    ts=utcnow(),
                    purpose="lesson",
                    model="claude-sonnet-5",
                    input_tokens=100,
                    output_tokens=200,
                    latency_ms=latency_ms,
                    cost_estimate=cost,
                    prompt_version="v1",
                    status="ok",
                    course_id=course_id,
                )
            )
        session.commit()
    finally:
        session.close()

    resp = client.get(f"/api/sections/{section_id}/lesson/estimate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["based_on_calls"] == 2
    assert body["est_seconds"] == 3.0  # (2000+4000)/2 / 1000
    assert body["est_cost_usd"] == 0.015


def test_estimate_ignores_calls_with_other_purposes(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    session = get_session()
    try:
        session.add(
            LlmCall(
                ts=utcnow(),
                purpose="chat",  # not "lesson" — must not be counted
                model="claude-sonnet-5",
                input_tokens=1,
                output_tokens=1,
                latency_ms=99999,
                cost_estimate=999.0,
                status="ok",
                course_id=course_id,
            )
        )
        session.commit()
    finally:
        session.close()

    resp = client.get(f"/api/sections/{section_id}/lesson/estimate")
    body = resp.json()
    assert body["based_on_calls"] == 0


def test_estimate_404_for_missing_section(client):
    resp = client.get("/api/sections/does-not-exist/lesson/estimate")
    assert resp.status_code == 404
