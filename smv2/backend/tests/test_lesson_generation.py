from __future__ import annotations

import pytest

from app.db.engine import get_session
from app.db.models import Section
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult
from conftest import _first_section_id


def test_generate_lesson_happy_path(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    resp = client.post(f"/api/sections/{section_id}/lesson")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    section = client.get(f"/api/sections/{section_id}").json()
    assert section["lesson_status"] == "queued"

    assert run_due_jobs_once() is True

    section = client.get(f"/api/sections/{section_id}").json()
    assert section["lesson_status"] == "ready"
    assert section["lesson_md"] == "stub lesson content"
    assert section["lesson_stale"] is False
    # UX law: generated content must be labeled with model + prompt version.
    assert section["lesson_model"] == "stub-model"
    assert section["lesson_prompt_version"] == "v1"

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"

    assert stub_provider.call_count == 1


def test_generate_lesson_scopes_prompt_to_this_section_only(client, ingest_course, stub_provider):
    """The prompt sent to the provider must contain THIS section's body_md
    and title, never another section's — one call, one section, per the
    prime directive that generation is never a whole-book call.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    target = sections[0]
    other = sections[1]

    client.post(f"/api/sections/{target['id']}/lesson")
    assert run_due_jobs_once() is True

    assert stub_provider.call_count == 1
    sent_content = stub_provider.received_messages[0][0]["content"]
    assert target["title"] in sent_content
    assert other["title"] not in sent_content

    session = get_session()
    try:
        other_section = session.get(Section, other["id"])
        assert other_section.body_md not in sent_content or other_section.body_md == ""
        assert other_section.lesson_status == "none"  # untouched
    finally:
        session.close()


def test_generate_lesson_sends_instructions_in_system_and_wraps_body_in_source_text_tags(
    client, ingest_course, stub_provider
):
    """Prompt-injection guard: instructions live in the system parameter,
    never mixed into the same message as untrusted PDF-derived text. The
    user message must contain ONLY the title + body_md, wrapped in
    <source_text> tags, with the instructions nowhere inside it.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    section_detail = client.get(f"/api/sections/{section_id}").json()

    client.post(f"/api/sections/{section_id}/lesson")
    assert run_due_jobs_once() is True

    assert stub_provider.call_count == 1
    system_sent = stub_provider.received_systems[0]
    user_content = stub_provider.received_messages[0][0]["content"]

    assert system_sent is not None
    assert "Self-Check Questions" in system_sent  # the actual instructions live in system
    assert "Self-Check Questions" not in user_content  # never leak into the user message

    assert "<source_text>" in user_content
    assert "</source_text>" in user_content
    assert section_detail["body_md"] in user_content

    # body_md must appear strictly inside the tags, not before them.
    before_tag = user_content.split("<source_text>")[0]
    assert section_detail["body_md"] not in before_tag


def test_generate_lesson_409_when_already_in_progress(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    first = client.post(f"/api/sections/{section_id}/lesson")
    assert first.status_code == 202

    second = client.post(f"/api/sections/{section_id}/lesson")
    assert second.status_code == 409


def test_generate_lesson_force_bypasses_409(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    first = client.post(f"/api/sections/{section_id}/lesson")
    assert first.status_code == 202

    forced = client.post(f"/api/sections/{section_id}/lesson?force=true")
    assert forced.status_code == 202


def test_claim_race_second_call_gets_conflict_without_a_job_run_between(client, ingest_course):
    """Regression: the 409 check used to be read-then-write (get status,
    then separately set it), which two concurrent submissions could both
    pass. The claim is now a single atomic UPDATE...RETURNING, so calling
    it twice back to back — with no job execution in between to reset
    lesson_status — must have the second call lose the race deterministically.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    from app.services import lessons_service

    first_job_id = lessons_service.start_lesson_generation(section_id)
    assert first_job_id

    with pytest.raises(lessons_service.LessonAlreadyInProgressError):
        lessons_service.start_lesson_generation(section_id)


def test_claim_race_force_bypasses_the_conflict(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    from app.services import lessons_service

    lessons_service.start_lesson_generation(section_id)
    second_job_id = lessons_service.start_lesson_generation(section_id, force=True)
    assert second_job_id


def test_generate_lesson_404_for_missing_section(client):
    resp = client.post("/api/sections/does-not-exist/lesson")
    assert resp.status_code == 404


def test_generate_lesson_degenerate_output_retries_once_then_fails(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(text="   ", input_tokens=5, output_tokens=0, model="stub-model"),
        CompletionResult(text="", input_tokens=5, output_tokens=0, model="stub-model"),
    ]

    client.post(f"/api/sections/{section_id}/lesson")
    assert run_due_jobs_once() is True

    section = client.get(f"/api/sections/{section_id}").json()
    assert section["lesson_status"] == "failed"
    assert section["lesson_md"] is None
    assert stub_provider.call_count == 2  # one retry, then give up


def test_generate_lesson_succeeds_after_one_degenerate_retry(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(text="", input_tokens=5, output_tokens=0, model="stub-model"),
        CompletionResult(text="A real lesson.", input_tokens=5, output_tokens=10, model="stub-model"),
    ]

    client.post(f"/api/sections/{section_id}/lesson")
    assert run_due_jobs_once() is True

    section = client.get(f"/api/sections/{section_id}").json()
    assert section["lesson_status"] == "ready"
    assert section["lesson_md"] == "A real lesson."
    assert stub_provider.call_count == 2


def test_generate_lesson_strips_leading_code_fence(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(
            text="```markdown\n# Overview\n\nSome lesson content.\n```",
            input_tokens=10,
            output_tokens=10,
            model="stub-model",
        )
    ]

    client.post(f"/api/sections/{section_id}/lesson")
    assert run_due_jobs_once() is True

    section = client.get(f"/api/sections/{section_id}").json()
    assert section["lesson_status"] == "ready"
    assert not section["lesson_md"].startswith("```")
    assert "# Overview" in section["lesson_md"]


def test_generate_lesson_provider_error_marks_failed(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.exceptions = [RuntimeError("provider exploded")]

    resp = client.post(f"/api/sections/{section_id}/lesson")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    section = client.get(f"/api/sections/{section_id}").json()
    assert section["lesson_status"] == "failed"

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert "provider exploded" in job["error"]


def test_generation_never_touches_body_md_through_real_pipeline(client, ingest_course, stub_provider):
    """Extends the ORM/trigger-level immutability guard: the REAL
    generation job, end to end, must never alter body_md — only lesson_md.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    before = client.get(f"/api/sections/{section_id}").json()["body_md"]

    client.post(f"/api/sections/{section_id}/lesson")
    assert run_due_jobs_once() is True

    after = client.get(f"/api/sections/{section_id}").json()
    assert after["body_md"] == before
    assert after["lesson_status"] == "ready"


def test_generate_all_lessons_enqueues_none_and_failed_only(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert len(sections) == 3

    # Manually mark one section 'ready' already, so generate_all_lessons
    # should skip it.
    session = get_session()
    try:
        already_done = session.get(Section, sections[0]["id"])
        already_done.lesson_status = "ready"
        already_done.lesson_md = "existing lesson"
        session.commit()
    finally:
        session.close()

    resp = client.post(f"/api/courses/{course_id}/lessons")
    assert resp.status_code == 202
    body = resp.json()
    assert len(body["job_ids"]) == 2
    assert body["skipped"] == 1

    claimed_count = 0
    while run_due_jobs_once():
        claimed_count += 1
    assert claimed_count == 2

    refreshed = client.get(f"/api/courses/{course_id}/sections").json()
    assert all(s["lesson_status"] == "ready" for s in refreshed)


def test_generate_all_lessons_404_for_missing_course(client):
    resp = client.post("/api/courses/does-not-exist/lessons")
    assert resp.status_code == 404
