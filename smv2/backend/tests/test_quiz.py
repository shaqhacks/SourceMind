from __future__ import annotations

import json

from app.db.engine import get_session
from app.db.models import Card, LlmCall, ReviewState, TestAttempt, ensure_utc, utcnow
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


def test_generate_test_records_prompt_version_on_test_attempt(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    resp = client.post(f"/api/courses/{course_id}/tests")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True
    attempt_id = client.get(f"/api/jobs/{job_id}").json()["result"]["attempt_id"]

    session = get_session()
    try:
        attempt = session.get(TestAttempt, attempt_id)
        assert attempt.prompt_version == "v2"
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
    assert parse_failure_row.prompt_version == "v2"
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
        for card_id in body["added_card_ids"]:
            card = session.get(Card, card_id)
            assert card is not None
            assert "Question" in card.front_md
            # Brand-new cards get no ReviewState row at all -- a card with
            # none is already picked up as "new" (and thus due) by the
            # review queue without one.
            assert session.get(ReviewState, card_id) is None
    finally:
        session.close()


def test_submit_test_all_correct_creates_no_cards(client, ingest_course, stub_provider):
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
        state_before = session.get(ReviewState, graded_card_id)
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
        state_after = session.get(ReviewState, graded_card_id)
        assert state_after is not None
        assert state_after.ease == ease_before
        assert state_after.interval_days == interval_before
        assert state_after.reps == reps_before
        assert ensure_utc(state_after.due_at) <= utcnow()  # refreshed to due now
    finally:
        session.close()
