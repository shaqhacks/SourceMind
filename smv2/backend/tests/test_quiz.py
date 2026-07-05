from __future__ import annotations

import json

from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult
from app.pipeline.quiz_generation import _build_scoped_text


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


def test_list_tests_returns_summaries(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    client.post(f"/api/courses/{course_id}/tests")
    assert run_due_jobs_once() is True

    resp = client.get(f"/api/courses/{course_id}/tests")
    assert resp.status_code == 200
    attempts = resp.json()
    assert len(attempts) == 1
    assert attempts[0]["question_count"] == 8
    assert attempts[0]["score"] is None


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
