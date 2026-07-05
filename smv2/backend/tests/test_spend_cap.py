from __future__ import annotations

from app.db.engine import get_session
from app.db.models import LlmCall, utcnow
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult


def _first_section_id(client, course_id: str) -> str:
    return client.get(f"/api/courses/{course_id}/sections").json()[0]["id"]


def test_spend_cap_blocks_generation_when_exceeded(client, ingest_course, stub_provider, monkeypatch):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    monkeypatch.setenv("SMV2_COURSE_SPEND_CAP_USD", "0.0001")

    # Seed prior spend for this course already at/above the cap.
    session = get_session()
    try:
        session.add(
            LlmCall(
                ts=utcnow(),
                purpose="lesson",
                model="claude-sonnet-5",
                input_tokens=1000,
                output_tokens=1000,
                latency_ms=100,
                cost_estimate=0.01,
                status="ok",
                course_id=course_id,
            )
        )
        session.commit()
    finally:
        session.close()

    resp = client.post(f"/api/sections/{section_id}/lesson")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    section = client.get(f"/api/sections/{section_id}").json()
    assert section["lesson_status"] == "failed"
    assert section["lesson_md"] is None

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert "spend cap exceeded" in job["error"]

    # The cap check must short-circuit BEFORE any provider call — no
    # partial billing loop.
    assert stub_provider.call_count == 0


def test_spend_cap_unlimited_by_default(client, ingest_course, stub_provider, monkeypatch):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    monkeypatch.delenv("SMV2_COURSE_SPEND_CAP_USD", raising=False)

    resp = client.post(f"/api/sections/{section_id}/lesson")
    assert run_due_jobs_once() is True

    section = client.get(f"/api/sections/{section_id}").json()
    assert section["lesson_status"] == "ready"


def test_spend_cap_second_job_blocked_after_first_pushes_over_cap(
    client, ingest_course, stub_provider, monkeypatch
):
    """The realistic overspend scenario: generate_all_lessons enqueues a
    batch, the sequential worker runs job 1 (which alone costs enough to
    exceed the cap), and job 2 must be blocked BEFORE calling the provider
    at all — proven by call_count staying at 1, not 2.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    section1_id, section2_id = sections[0]["id"], sections[1]["id"]

    # A priced model so job 1's own cost is what crosses the cap, not a
    # pre-seeded row: 1M in + 1M out at claude-sonnet-5 rates = $3 + $15 = $18.
    stub_provider.model_name = "claude-sonnet-5"
    stub_provider.responses = [
        CompletionResult(text="Lesson one.", input_tokens=1_000_000, output_tokens=1_000_000, model="claude-sonnet-5"),
    ]
    monkeypatch.setenv("SMV2_COURSE_SPEND_CAP_USD", "10.0")

    client.post(f"/api/sections/{section1_id}/lesson")
    assert run_due_jobs_once() is True
    section1 = client.get(f"/api/sections/{section1_id}").json()
    assert section1["lesson_status"] == "ready"
    assert stub_provider.call_count == 1

    resp = client.post(f"/api/sections/{section2_id}/lesson")
    job2_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    section2 = client.get(f"/api/sections/{section2_id}").json()
    assert section2["lesson_status"] == "failed"

    job2 = client.get(f"/api/jobs/{job2_id}").json()
    assert job2["status"] == "failed"
    assert "spend cap exceeded" in job2["error"]

    assert stub_provider.call_count == 1  # job 2 never reached the provider


def test_job_result_flags_spend_cap_reached_after_this_call(client, ingest_course, stub_provider, monkeypatch):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.model_name = "claude-sonnet-5"
    stub_provider.responses = [
        CompletionResult(text="Lesson.", input_tokens=1_000_000, output_tokens=1_000_000, model="claude-sonnet-5"),
    ]
    # This single call alone costs $18, over a $10 cap.
    monkeypatch.setenv("SMV2_COURSE_SPEND_CAP_USD", "10.0")

    resp = client.post(f"/api/sections/{section_id}/lesson")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["result"]["spend_cap_reached"] is True


def test_job_result_spend_cap_not_reached_when_under_cap(client, ingest_course, stub_provider, monkeypatch):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    monkeypatch.setenv("SMV2_COURSE_SPEND_CAP_USD", "1000.0")

    resp = client.post(f"/api/sections/{section_id}/lesson")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["result"]["spend_cap_reached"] is False
