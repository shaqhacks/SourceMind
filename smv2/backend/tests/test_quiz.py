from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.db.engine import get_session
from app.db.models import (
    Card,
    Job,
    LlmCall,
    PracticeExtractionRun,
    ReviewState,
    Test,
    TestAttempt,
    ensure_utc,
    utcnow,
)
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult
from app.llm.structured_output import QUIZ_SCHEMA
from app.pipeline.quiz_generation import _build_scoped_text
from app.services import tests_service


def _make_questions(n: int = 8) -> list[dict]:
    return [
        {
            "question": f"Question {i}?",
            "choices": ["A", "B", "C", "D"],
            "correct_index": i % 4,
            "explanation": f"Because {i}.",
        }
        for i in range(n)
    ]


def _practice_section_by_title(client, course_id: str, title: str) -> dict:
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    return next(section for section in sections if section["title"] == title)


def _seed_practice_run_for_section(
    section_id: str,
    *,
    course_id: str,
    status: str,
    job_status: str,
    fingerprint_suffix: str,
) -> tuple[str, str]:
    session = get_session()
    try:
        job = Job(
            type="generate_practice_assessment",
            status=job_status,
            payload={"course_id": course_id, "section_id": section_id, "run_id": "seeded-later"},
            progress={"stage": "thinking", "message": "Preparing practice."},
            lease_until=utcnow() + timedelta(seconds=60) if job_status == "running" else None,
        )
        session.add(job)
        session.flush()
        run = PracticeExtractionRun(
            course_id=course_id,
            section_id=section_id,
            status=status,
            job_id=job.id,
            input_fingerprint=f"fingerprint-{section_id}-{fingerprint_suffix}",
            question_count=2 if status == "ready" else 0,
            error="learner-facing practice error" if status == "failed" else None,
        )
        session.add(run)
        session.flush()
        job.payload = {"course_id": course_id, "section_id": section_id, "run_id": run.id}
        session.commit()
        return job.id, run.id
    finally:
        session.close()


def _attempt_profile_id(session, attempt_id: str) -> str:
    return session.get(TestAttempt, attempt_id).course_learning_profile_id


def test_generate_test_cancels_queued_practice_by_deleting_runs_for_same_chapter(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    other_course_id, *_ = ingest_course("headings_no_bookmarks.pdf", title="Other Course")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    other_chapter = _practice_section_by_title(client, course_id, "Chapter 2: Structures")
    other_course_same_chapter = _practice_section_by_title(
        client, other_course_id, "0.1 Practice - Foundations"
    )
    cancelled_job_id, cancelled_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="queued-same",
    )
    other_job_id, other_run_id = _seed_practice_run_for_section(
        other_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="queued-other",
    )
    other_course_job_id, other_course_run_id = _seed_practice_run_for_section(
        other_course_same_chapter["id"],
        course_id=other_course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="queued-other-course",
    )
    ready_job_id, ready_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="ready",
        job_status="succeeded",
        fingerprint_suffix="ready-same",
    )
    running_job_id, running_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="running",
        fingerprint_suffix="running-same",
    )
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )

    assert resp.status_code == 202
    test_job_id = resp.json()["job_id"]
    session = get_session()
    try:
        cancelled_job = session.get(Job, cancelled_job_id)
        other_job = session.get(Job, other_job_id)
        other_run = session.get(PracticeExtractionRun, other_run_id)
        other_course_job = session.get(Job, other_course_job_id)
        other_course_run = session.get(PracticeExtractionRun, other_course_run_id)
        ready_job = session.get(Job, ready_job_id)
        ready_run = session.get(PracticeExtractionRun, ready_run_id)
        running_job = session.get(Job, running_job_id)
        running_run = session.get(PracticeExtractionRun, running_run_id)
        test_job = session.get(Job, test_job_id)

        assert cancelled_job.status == "cancelled"
        assert cancelled_job.progress is None
        assert cancelled_job.lease_until is None
        assert session.get(PracticeExtractionRun, cancelled_run_id) is None
        assert other_job.status == "queued"
        assert other_run.status == "queued"
        assert other_course_job.status == "queued"
        assert other_course_run.status == "queued"
        assert ready_job.status == "succeeded"
        assert ready_run.status == "ready"
        assert ready_run.job_id == ready_job_id
        assert running_job.status == "running"
        assert running_run.status == "queued"
        assert test_job.status == "queued"
    finally:
        session.close()


def test_practice_post_after_test_cancellation_creates_fresh_run_and_job(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    old_job_id, old_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="queued-before-test",
    )
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    test_resp = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )
    assert test_resp.status_code == 202
    practice_resp = client.post(
        f"/api/courses/{course_id}/sections/{same_chapter['id']}/practice-assessment"
    )

    assert practice_resp.status_code == 202
    body = practice_resp.json()
    assert body["run_id"] != old_run_id
    assert body["job_id"] != old_job_id
    session = get_session()
    try:
        assert session.get(PracticeExtractionRun, old_run_id) is None
        fresh_run = session.get(PracticeExtractionRun, body["run_id"])
        fresh_job = session.get(Job, body["job_id"])
        assert fresh_run is not None
        assert fresh_run.status == "queued"
        assert fresh_job is not None
        assert fresh_job.status == "queued"
    finally:
        session.close()


def test_generate_test_preserves_practice_job_claimed_during_cancellation(
    client, ingest_course, monkeypatch, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    claimed_job_id, claimed_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="claimed-race",
    )
    original_execute = tests_service.session_execute_returning_cancelled_job_ids

    def claim_before_update(session, statement):
        job = session.get(Job, claimed_job_id)
        assert job is not None
        job.status = "running"
        job.lease_until = utcnow() + timedelta(seconds=60)
        session.flush()
        return original_execute(session, statement)

    monkeypatch.setattr(
        tests_service,
        "session_execute_returning_cancelled_job_ids",
        claim_before_update,
    )
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )

    assert resp.status_code == 202
    session = get_session()
    try:
        job = session.get(Job, claimed_job_id)
        run = session.get(PracticeExtractionRun, claimed_run_id)
        assert job.status == "running"
        assert job.lease_until is not None
        assert run is not None
        assert run.status == "queued"
        assert run.job_id == claimed_job_id
    finally:
        session.close()


def test_generate_test_reuses_active_same_scope_job_without_repeated_cancellation(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    queued_practice_job_id, queued_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="idempotency-cancel-once",
    )
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    first = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )
    second = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]
    session = get_session()
    try:
        assert session.query(Job).filter(Job.type == "generate_test").count() == 1
        assert session.get(Job, queued_practice_job_id).status == "cancelled"
        assert session.get(PracticeExtractionRun, queued_run_id) is None
    finally:
        session.close()


def test_generate_test_reuses_active_same_scope_job_without_readiness(
    client, ingest_course, monkeypatch, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    first = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    second = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]


def test_generate_test_reuses_active_job_for_reversed_section_ids(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    target_ids = [sections[0]["id"], sections[1]["id"]]
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    first = client.post(
        f"/api/courses/{course_id}/tests",
        json={"section_ids": target_ids},
    )
    second = client.post(
        f"/api/courses/{course_id}/tests",
        json={"section_ids": list(reversed(target_ids))},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]


def test_generate_test_creates_new_job_after_same_scope_job_is_terminal(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    first = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )
    session = get_session()
    try:
        first_job = session.get(Job, first.json()["job_id"])
        first_job.status = "succeeded"
        session.commit()
    finally:
        session.close()

    second = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )

    assert second.status_code == 202
    assert second.json()["job_id"] != first.json()["job_id"]


def test_generate_test_rolls_back_practice_cancellation_when_test_job_creation_fails(
    client, ingest_course, monkeypatch, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    queued_job_id, queued_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="rollback-create-test",
    )
    original_create_job_in_session = tests_service.jobs_service.create_job_in_session

    def fail_generate_test_job(session, job_type, payload):
        if job_type == "generate_test":
            raise RuntimeError("synthetic generate_test creation failure")
        return original_create_job_in_session(session, job_type, payload)

    monkeypatch.setattr(
        tests_service.jobs_service,
        "create_job_in_session",
        fail_generate_test_job,
    )

    with pytest.raises(RuntimeError, match="synthetic generate_test creation failure"):
        tests_service.start_test_generation(
            course_id,
            chapter_label="Chapter 1: Foundations",
        )

    session = get_session()
    try:
        queued_job = session.get(Job, queued_job_id)
        queued_run = session.get(PracticeExtractionRun, queued_run_id)
        assert queued_job is not None
        assert queued_job.status == "queued"
        assert queued_job.progress == {"stage": "thinking", "message": "Preparing practice."}
        assert queued_run is not None
        assert queued_run.status == "queued"
        assert queued_run.job_id == queued_job_id
        assert session.query(Job).filter(Job.type == "generate_test").count() == 0
    finally:
        session.close()


def test_generate_test_happy_path(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(f"/api/courses/{course_id}/tests")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["result"]["question_count"] == 8
    attempt_id = job["result"]["attempt_id"]
    detail = client.get(f"/api/tests/{attempt_id}").json()
    assert detail["score"] is None
    assert len(detail["questions"]) == 8
    # Answers hidden while ungraded.
    assert all("correct_index" not in q or q.get("correct_index") is None for q in detail["questions"])
    assert all("explanation" not in q or q.get("explanation") is None for q in detail["questions"])


def test_generate_test_unconfigured_provider_fails_before_job_creation(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    resp = client.post(f"/api/courses/{course_id}/tests")

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["failure_category"] == "missing_credentials"
    assert "ANTHROPIC_API_KEY" in body["detail"]["remediation"]

    session = get_session()
    try:
        assert session.query(Job).filter(Job.type == "generate_test").count() == 0
        assert session.query(Test).count() == 0
        assert session.query(TestAttempt).count() == 0
    finally:
        session.close()

def test_generate_test_records_prompt_version_and_model_on_the_test_deck(client, ingest_course, stub_provider):
    """ADR-022: prompt_version/model live on Test (the deck), not the
    attempt -- every attempt against the same deck shares them.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    job_result = client.get(f"/api/jobs/{job_id}").json()["result"]

    session = get_session()
    try:
        test = session.get(Test, job_result["test_id"])
        assert test.prompt_version == "v3"
        assert test.model == "stub-model"
    finally:
        session.close()


def test_generate_test_with_specific_sections(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    target = sections[0]

    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(f"/api/courses/{course_id}/tests", json={"section_ids": [target["id"]]})
    assert resp.status_code == 202
    assert run_due_jobs_once() is True

    sent = stub_provider.received_messages[0][0]["content"]
    assert target["title"] in sent
    for other in sections[1:]:
        assert other["title"] not in sent


def test_generate_test_404_for_missing_course(client):
    resp = client.post("/api/courses/does-not-exist/tests")
    assert resp.status_code == 404


def test_generate_test_drops_malformed_questions(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    good = _make_questions(3)
    malformed = [
        {"question": "", "choices": ["A", "B", "C", "D"], "correct_index": 0, "explanation": "x"},
        {"question": "Q", "choices": ["A", "B"], "correct_index": 0, "explanation": "x"},  # only 2 choices
        {"question": "Q", "choices": ["A", "B", "C", "D"], "correct_index": 9, "explanation": "x"},  # oob
        "not an object",
    ]
    stub_provider.responses = [
        CompletionResult(text=json.dumps(good + malformed), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["result"]["question_count"] == 3


def test_generate_test_retries_once_on_parse_failure(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    stub_provider.responses = [
        CompletionResult(text="not json", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert stub_provider.call_count == 2


def test_generate_test_schema_sent_on_first_and_repair_completion(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    stub_provider.responses = [
        CompletionResult(text="not json", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    client.post(f"/api/courses/{course_id}/tests")
    assert run_due_jobs_once() is True

    assert stub_provider.complete_call_count == 2
    assert [option.response_schema for option in stub_provider.received_completion_options] == [
        QUIZ_SCHEMA,
        QUIZ_SCHEMA,
    ]
    repair_content = stub_provider.received_messages[1][-1]["content"]
    assert "valid JSON" in repair_content
    assert "not json" not in repair_content


def test_generate_test_repairs_empty_structured_array(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    stub_provider.responses = [
        CompletionResult(text="[]", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert stub_provider.complete_call_count == 2


def test_generate_test_records_parse_failure_after_two_all_malformed_arrays(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    malformed = [{"question": "", "choices": ["A", "B"], "correct_index": 0}, "not an object"]

    stub_provider.responses = [
        CompletionResult(text=json.dumps(malformed), input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text=json.dumps(malformed), input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error_detail"]["code"] == "invalid_model_output"
    session = get_session()
    try:
        calls = session.query(LlmCall).filter(LlmCall.purpose == "quiz").order_by(LlmCall.ts).all()
    finally:
        session.close()
    assert [row.status for row in calls] == ["ok", "ok", "parse_failure"]


def test_generate_test_fails_after_two_parse_failures_records_parse_failure_ledger_row(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    stub_provider.responses = [
        CompletionResult(text="not json", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text="still not json", input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert stub_provider.call_count == 2

    session = get_session()
    try:
        calls = session.query(LlmCall).filter(LlmCall.purpose == "quiz").order_by(LlmCall.ts).all()
    finally:
        session.close()

    assert [c.status for c in calls] == ["ok", "ok", "parse_failure"]
    parse_failure_row = calls[-1]
    assert parse_failure_row.cost_estimate is None
    assert parse_failure_row.prompt_version == "v3"
    assert parse_failure_row.course_id == course_id


def test_submit_test_grades_deterministically(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    questions = _make_questions(4)
    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    attempt_id = client.get(f"/api/jobs/{job_id}").json()["result"]["attempt_id"]

    correct_indices = [q["correct_index"] for q in questions]
    # Answer all correctly.
    resp = client.post(f"/api/tests/{attempt_id}/submit", json={"answers": correct_indices})
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"] == 1.0
    assert all(r["correct"] for r in body["results"])
    assert all(r["correct_index"] == correct_indices[i] for i, r in enumerate(body["results"]))

    # Answers/explanations now visible.
    detail = client.get(f"/api/tests/{attempt_id}").json()
    assert detail["score"] == 1.0
    assert all("correct_index" in q for q in detail["questions"])


def test_submit_test_partial_score(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    questions = _make_questions(4)
    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    attempt_id = client.get(f"/api/jobs/{job_id}").json()["result"]["attempt_id"]

    wrong_answers = [(q["correct_index"] + 1) % 4 for q in questions]
    resp = client.post(f"/api/tests/{attempt_id}/submit", json={"answers": wrong_answers})
    body = resp.json()
    assert body["score"] == 0.0
    assert all(not r["correct"] for r in body["results"])


def test_submit_test_twice_is_409(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    questions = _make_questions(2)
    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    attempt_id = client.get(f"/api/jobs/{job_id}").json()["result"]["attempt_id"]

    answers = [q["correct_index"] for q in questions]
    assert client.post(f"/api/tests/{attempt_id}/submit", json={"answers": answers}).status_code == 200
    assert client.post(f"/api/tests/{attempt_id}/submit", json={"answers": answers}).status_code == 409


def test_submit_test_404_for_missing_attempt(client):
    resp = client.post("/api/tests/does-not-exist/submit", json={"answers": [0]})
    assert resp.status_code == 404


def test_get_test_404_for_missing_attempt(client):
    resp = client.get("/api/tests/does-not-exist")
    assert resp.status_code == 404


def test_retake_test_creates_new_attempt_with_zero_llm_calls(client, ingest_course, stub_provider):
    """ADR-022: retaking a test reuses the SAME deck's questions -- no
    further provider.complete() call at all.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    questions = _make_questions(4)
    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    job_result = client.get(f"/api/jobs/{job_id}").json()["result"]
    test_id = job_result["test_id"]
    calls_after_generate = stub_provider.call_count

    resp = client.post(f"/api/tests/{test_id}/attempts")
    assert resp.status_code == 201
    new_attempt_id = resp.json()["attempt_id"]
    assert new_attempt_id != job_result["attempt_id"]
    assert stub_provider.call_count == calls_after_generate  # no new LLM call

    detail = client.get(f"/api/tests/{new_attempt_id}").json()
    assert detail["test_id"] == test_id
    assert detail["score"] is None
    assert len(detail["questions"]) == 4
    # Same underlying questions as the original attempt (redacted the same way).
    original_detail = client.get(f"/api/tests/{job_result['attempt_id']}").json()
    assert detail["questions"] == original_detail["questions"]


def test_retake_test_404_for_missing_test(client):
    resp = client.post("/api/tests/does-not-exist/attempts")
    assert resp.status_code == 404


def test_list_tests_groups_multiple_attempts_under_one_deck(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    questions = _make_questions(2)
    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    job_result = client.get(f"/api/jobs/{job_id}").json()["result"]
    test_id = job_result["test_id"]

    client.post(f"/api/tests/{test_id}/attempts")
    client.post(f"/api/tests/{test_id}/attempts")

    resp = client.get(f"/api/courses/{course_id}/tests")
    tests = resp.json()
    assert len(tests) == 1
    assert len(tests[0]["attempts"]) == 3  # original + 2 retakes


def test_list_tests_returns_summaries(client, ingest_course, stub_provider):
    """ADR-022: list_tests is test-grouped -- one deck with a nested
    attempt history, not a flat list of attempts.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    client.post(f"/api/courses/{course_id}/tests")
    assert run_due_jobs_once() is True

    resp = client.get(f"/api/courses/{course_id}/tests")
    assert resp.status_code == 200
    tests = resp.json()
    assert len(tests) == 1
    assert tests[0]["question_count"] == 8
    assert len(tests[0]["attempts"]) == 1
    assert tests[0]["attempts"][0]["score"] is None


def test_list_tests_404_for_missing_course(client):
    resp = client.get("/api/courses/does-not-exist/tests")
    assert resp.status_code == 404


def test_build_scoped_text_gives_every_section_a_proportional_head_when_over_cap():
    from app.db.models import Section

    class _FakeSection:
        def __init__(self, title, body):
            self.title = title
            self.body_md = body

    big_section = _FakeSection("Big", "x" * 20_000)
    small_section = _FakeSection("Small", "y" * 10_000)

    scoped = _build_scoped_text([big_section, small_section])
    assert "Big" in scoped
    assert "Small" in scoped
    # Every section contributes SOMETHING, not just the first one in full.
    assert "y" in scoped
    assert len(scoped) < 20_000 + 10_000 + 100  # actually capped, not just concatenated


# --- ADR-017: chapter test mode ---------------------------------------------


def test_generate_test_with_chapter_label_scopes_to_practice_and_content_only(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    by_title = {s["title"]: s for s in sections}

    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(f"/api/courses/{course_id}/tests", json={"chapter_label": "Chapter 1: Foundations"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    sent = stub_provider.received_messages[0][0]["content"]
    assert by_title["Chapter 1: Foundations"]["title"] in sent
    assert by_title["0.1 Practice - Foundations"]["title"] in sent
    # The answer key names its own chapter but must never reach the prompt.
    assert by_title["Answers - Chapter 1"]["title"] not in sent
    assert by_title["Chapter 2: Structures"]["title"] not in sent

    job = client.get(f"/api/jobs/{job_id}").json()
    attempt_id = job["result"]["attempt_id"]
    detail = client.get(f"/api/tests/{attempt_id}").json()
    assert detail["chapter_label"] == "Chapter 1: Foundations"

    summary = client.get(f"/api/courses/{course_id}/tests").json()
    assert summary[0]["chapter_label"] == "Chapter 1: Foundations"


def test_generate_test_404_for_unknown_chapter_label(client, ingest_course):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    resp = client.post(f"/api/courses/{course_id}/tests", json={"chapter_label": "Chapter 99: Nonexistent"})
    assert resp.status_code == 404


def test_generate_test_whole_course_mode_excludes_answer_key_sections(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    by_title = {s["title"]: s for s in sections}

    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(f"/api/courses/{course_id}/tests")  # no chapter_label, no section_ids
    assert resp.status_code == 202
    assert run_due_jobs_once() is True

    sent = stub_provider.received_messages[0][0]["content"]
    assert by_title["Chapter 1: Foundations"]["title"] in sent
    assert by_title["Answers - Chapter 1"]["title"] not in sent


# --- ADR-017: missed questions become flashcards (missed -> SRS) -----------


def test_submit_test_wrong_answers_create_cards_due_now(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    questions = _make_questions(4)
    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    attempt_id = client.get(f"/api/jobs/{job_id}").json()["result"]["attempt_id"]

    wrong_answers = [(q["correct_index"] + 1) % 4 for q in questions]
    resp = client.post(f"/api/tests/{attempt_id}/submit", json={"answers": wrong_answers})
    body = resp.json()
    assert len(body["added_card_ids"]) == 4

    session = get_session()
    try:
        profile_id = _attempt_profile_id(session, attempt_id)
        for card_id in body["added_card_ids"]:
            card = session.get(Card, card_id)
            assert card is not None
            assert "Question" in card.front_md
            # Brand-new cards get no ReviewState row at all -- a card with
            # none is already picked up as "new" (and thus due) by the
            # review queue without one.
            assert session.get(ReviewState, (profile_id, card_id)) is None
    finally:
        session.close()


def test_submit_test_all_correct_seeds_cards_as_good_reviews_not_added_card_ids(
    client, ingest_course, stub_provider
):
    """ADR-022: every question becomes a card now, including correct ones --
    but added_card_ids keeps its pre-ADR-022 meaning (missed-question cards
    only, an existing frontend surface already reads it that way), so it
    stays empty for an all-correct submission even though cards WERE
    created. A brand-new card answered correctly is seeded as one
    successful Good review: first-Good baseline (1 day), reps=1, due
    tomorrow -- not due right now.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    questions = _make_questions(3)
    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    attempt_id = client.get(f"/api/jobs/{job_id}").json()["result"]["attempt_id"]

    correct_answers = [q["correct_index"] for q in questions]
    body = client.post(f"/api/tests/{attempt_id}/submit", json={"answers": correct_answers}).json()
    assert body["added_card_ids"] == []
    assert body["due_now_count"] == 0

    section_id = client.get(f"/api/courses/{course_id}/sections").json()[0]["id"]
    session = get_session()
    try:
        profile_id = _attempt_profile_id(session, attempt_id)
        cards = session.query(Card).filter(Card.section_id == section_id).all()
        assert len(cards) == 3
        for card in cards:
            state = session.get(ReviewState, (profile_id, card.id))
            assert state is not None
            assert state.reps == 1
            assert state.last_grade == 3  # GOOD
            assert 0.9 < state.interval_days < 1.1  # first-Good baseline, ~1 day
            assert ensure_utc(state.due_at) > utcnow()  # due tomorrow, not now
    finally:
        session.close()


def test_submit_test_correct_on_not_yet_due_card_is_a_cramming_guard_noop(
    client, ingest_course, stub_provider
):
    """ADR-022 cramming guard: a card that already has SRS history and
    isn't due yet must not get credit for a correct test answer -- that
    would let a learner farm schedule advancement by re-taking a test on
    material they only just reviewed. Answering it correctly on a test
    leaves interval/ease/reps/due_at completely untouched.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    questions = _make_questions(1)
    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    attempt_id = client.get(f"/api/jobs/{job_id}").json()["result"]["attempt_id"]

    correct_answers = [q["correct_index"] for q in questions]
    client.post(f"/api/tests/{attempt_id}/submit", json={"answers": correct_answers})

    section_id = client.get(f"/api/courses/{course_id}/sections").json()[0]["id"]
    session = get_session()
    try:
        profile_id = _attempt_profile_id(session, attempt_id)
        card = session.query(Card).filter(Card.section_id == section_id).first()
        state_before = session.get(ReviewState, (profile_id, card.id))
        due_before, interval_before, ease_before, reps_before = (
            state_before.due_at, state_before.interval_days, state_before.ease, state_before.reps
        )
        assert ensure_utc(due_before) > utcnow()  # seeded due tomorrow, not due yet
        card_id = card.id
    finally:
        session.close()

    # Retake the same test, answer the same question correctly again while
    # its card is still not due -- must be a complete no-op.
    test_id = client.get(f"/api/jobs/{job_id}").json()["result"]["test_id"]
    retake_resp = client.post(f"/api/tests/{test_id}/attempts")
    new_attempt_id = retake_resp.json()["attempt_id"]
    client.post(f"/api/tests/{new_attempt_id}/submit", json={"answers": correct_answers})

    session = get_session()
    try:
        state_after = session.get(ReviewState, (profile_id, card_id))
        assert state_after.due_at == due_before
        assert state_after.interval_days == interval_before
        assert state_after.ease == ease_before
        assert state_after.reps == reps_before
    finally:
        session.close()


def test_submit_test_correct_on_a_due_existing_card_advances_via_real_schedule_next(
    client, ingest_course, stub_provider
):
    """A card that's already due (or new) when answered correctly on a
    test IS real review evidence -- schedule_next(GOOD, ...) applies from
    its actual current state, same as a genuine review-queue grade.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    questions = _make_questions(1)
    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    job_result = client.get(f"/api/jobs/{job_id}").json()["result"]
    attempt_id = job_result["attempt_id"]
    test_id = job_result["test_id"]

    correct_answers = [q["correct_index"] for q in questions]
    client.post(f"/api/tests/{attempt_id}/submit", json={"answers": correct_answers})

    section_id = client.get(f"/api/courses/{course_id}/sections").json()[0]["id"]
    session = get_session()
    try:
        profile_id = _attempt_profile_id(session, attempt_id)
        card = session.query(Card).filter(Card.section_id == section_id).first()
        card_id = card.id
        # Force the seeded ReviewState into the past so it's genuinely due
        # again, then note its state right before the second correct answer.
        state = session.get(ReviewState, (profile_id, card_id))
        state.due_at = utcnow() - timedelta(days=1)
        ease_before, interval_before, reps_before = state.ease, state.interval_days, state.reps
        session.commit()
    finally:
        session.close()

    retake_resp = client.post(f"/api/tests/{test_id}/attempts")
    new_attempt_id = retake_resp.json()["attempt_id"]
    client.post(f"/api/tests/{new_attempt_id}/submit", json={"answers": correct_answers})

    session = get_session()
    try:
        state_after = session.get(ReviewState, (profile_id, card_id))
        assert state_after.reps == reps_before + 1
        assert state_after.last_grade == 3  # GOOD
        # Good's own formula at reps>=2 multiplies by ease; below that it's
        # the plain baseline -- either way it must have genuinely advanced
        # past the forced due_at, proving schedule_next actually ran.
        assert ensure_utc(state_after.due_at) > utcnow()
    finally:
        session.close()


def test_submit_test_repeat_miss_dedupes_and_refreshes_due_at_without_touching_srs_state(
    client, ingest_course, stub_provider
):
    """Content-addressing means the SAME missed question across two
    separate test attempts maps to the SAME card -- no PK violation on the
    second submit, and if that card already has real SM-2 history (from
    being graded normally), a repeat miss only nudges due_at to now and
    leaves ease/interval/reps untouched (a miss on a test is evidence it
    needs review, not a formal SM-2 lapse).
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    questions = _make_questions(2)

    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    attempt_id = client.get(f"/api/jobs/{job_id}").json()["result"]["attempt_id"]

    wrong_answers = [(q["correct_index"] + 1) % 4 for q in questions]
    body1 = client.post(f"/api/tests/{attempt_id}/submit", json={"answers": wrong_answers}).json()
    first_card_ids = set(body1["added_card_ids"])
    assert len(first_card_ids) == 2

    graded_card_id = next(iter(first_card_ids))
    assert client.post(f"/api/cards/{graded_card_id}/grade", json={"grade": 3}).status_code == 200

    session = get_session()
    try:
        profile_id = _attempt_profile_id(session, attempt_id)
        state_before = session.get(ReviewState, (profile_id, graded_card_id))
        assert state_before is not None
        ease_before, interval_before, reps_before = (
            state_before.ease,
            state_before.interval_days,
            state_before.reps,
        )
    finally:
        session.close()

    stub_provider.responses = [
        CompletionResult(text=json.dumps(questions), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp2 = client.post(f"/api/courses/{course_id}/tests")
    job_id2 = resp2.json()["job_id"]
    assert run_due_jobs_once() is True
    attempt_id2 = client.get(f"/api/jobs/{job_id2}").json()["result"]["attempt_id"]

    body2 = client.post(f"/api/tests/{attempt_id2}/submit", json={"answers": wrong_answers}).json()
    assert set(body2["added_card_ids"]) == first_card_ids  # deduped, not new PK-violating rows

    session = get_session()
    try:
        state_after = session.get(ReviewState, (profile_id, graded_card_id))
        assert state_after is not None
        assert state_after.ease == ease_before
        assert state_after.interval_days == interval_before
        assert state_after.reps == reps_before
        assert ensure_utc(state_after.due_at) <= utcnow()  # refreshed to due now
    finally:
        session.close()
