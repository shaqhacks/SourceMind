from __future__ import annotations

import json

from app.db.engine import get_session
from app.db.models import Card, LlmCall, ReviewState
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import PROVIDER_NOT_CONFIGURED_MESSAGE, CompletionResult, ProviderNotConfiguredError
from conftest import _first_section_id


def test_generate_cards_happy_path(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps(
                [{"front": "What is X?", "back": "X is Y."}, {"front": "What is Z?", "back": "Z is W."}]
            ),
            input_tokens=100,
            output_tokens=50,
            model="stub-model",
        )
    ]

    resp = client.post(f"/api/sections/{section_id}/cards")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["result"]["card_count"] == 2

    cards = client.get(f"/api/sections/{section_id}/cards").json()
    assert len(cards) == 2
    assert {c["front_md"] for c in cards} == {"What is X?", "What is Z?"}


def test_generate_cards_records_prompt_version_on_each_card(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "What is X?", "back": "X is Y."}]),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    cards = client.get(f"/api/sections/{section_id}/cards").json()
    session = get_session()
    try:
        card = session.get(Card, cards[0]["id"])
        assert card.prompt_version == "v1"
    finally:
        session.close()


def test_generate_cards_scoped_to_this_section_only(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    target, other = sections[0], sections[1]

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "Q", "back": "A"}]), input_tokens=1, output_tokens=1, model="stub-model"
        )
    ]

    client.post(f"/api/sections/{target['id']}/cards")
    assert run_due_jobs_once() is True

    assert stub_provider.call_count == 1
    sent = stub_provider.received_messages[0][0]["content"]
    assert target["title"] in sent
    assert other["title"] not in sent


def test_generate_cards_409_when_active_job_exists(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    assert client.post(f"/api/sections/{section_id}/cards").status_code == 202
    assert client.post(f"/api/sections/{section_id}/cards").status_code == 409


def test_generate_cards_no_longer_blocked_once_job_completes(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "Q", "back": "A"}]), input_tokens=1, output_tokens=1, model="stub-model"
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    # The active job is done; a second submission must not 409.
    resp = client.post(f"/api/sections/{section_id}/cards")
    assert resp.status_code == 202


def test_generate_cards_404_for_missing_section(client):
    resp = client.post("/api/sections/does-not-exist/cards")
    assert resp.status_code == 404


def test_generate_cards_drops_malformed_items_keeps_valid_ones(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps(
                [
                    {"front": "Good Q", "back": "Good A"},
                    {"front": "", "back": "missing front"},
                    {"back": "no front key at all"},
                    "not an object",
                ]
            ),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
        )
    ]

    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    cards = client.get(f"/api/sections/{section_id}/cards").json()
    assert len(cards) == 1
    assert cards[0]["front_md"] == "Good Q"


def test_generate_cards_retries_once_on_top_level_parse_failure(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(text="not json at all", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(
            text=json.dumps([{"front": "Q", "back": "A"}]), input_tokens=1, output_tokens=1, model="stub-model"
        ),
    ]

    resp = client.post(f"/api/sections/{section_id}/cards")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert stub_provider.call_count == 2

    cards = client.get(f"/api/sections/{section_id}/cards").json()
    assert len(cards) == 1


def test_generate_cards_job_reports_friendly_error_when_provider_not_configured(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    stub_provider.exceptions = [ProviderNotConfiguredError(PROVIDER_NOT_CONFIGURED_MESSAGE)]

    resp = client.post(f"/api/sections/{section_id}/cards")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error"] == PROVIDER_NOT_CONFIGURED_MESSAGE


def test_generate_cards_fails_after_two_parse_failures(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(text="not json", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text="still not json", input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    resp = client.post(f"/api/sections/{section_id}/cards")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert stub_provider.call_count == 2


def test_generate_cards_fails_after_two_parse_failures_records_parse_failure_ledger_row(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(text="not json", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text="still not json", input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    session = get_session()
    try:
        calls = session.query(LlmCall).filter(LlmCall.purpose == "cards").order_by(LlmCall.ts).all()
    finally:
        session.close()

    assert [c.status for c in calls] == ["ok", "ok", "parse_failure"]
    parse_failure_row = calls[-1]
    assert parse_failure_row.cost_estimate is None
    assert parse_failure_row.prompt_version == "v1"
    assert parse_failure_row.course_id == course_id


def test_regenerate_cards_preserves_review_state_for_unchanged_cards(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps(
                [{"front": "Keep Q", "back": "Keep A"}, {"front": "Change Q", "back": "Change A"}]
            ),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    cards = client.get(f"/api/sections/{section_id}/cards").json()
    keep_card = next(c for c in cards if c["front_md"] == "Keep Q")
    change_card = next(c for c in cards if c["front_md"] == "Change Q")

    assert client.post(f"/api/cards/{keep_card['id']}/grade", json={"grade": 3}).status_code == 200
    assert client.post(f"/api/cards/{change_card['id']}/grade", json={"grade": 2}).status_code == 200

    session = get_session()
    try:
        assert session.get(ReviewState, keep_card["id"]) is not None
        assert session.get(ReviewState, change_card["id"]) is not None
    finally:
        session.close()

    # Re-generate: "Keep Q" text is byte-identical (same content-addressed
    # id survives); "Change Q" becomes different text (new id, old row gone).
    stub_provider.responses = [
        CompletionResult(
            text=json.dumps(
                [
                    {"front": "Keep Q", "back": "Keep A"},
                    {"front": "Totally Different Q", "back": "Totally Different A"},
                ]
            ),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
        )
    ]
    resp = client.post(f"/api/sections/{section_id}/cards")
    assert resp.status_code == 202
    assert run_due_jobs_once() is True

    cards_after = client.get(f"/api/sections/{section_id}/cards").json()
    assert len(cards_after) == 2
    keep_card_after = next(c for c in cards_after if c["front_md"] == "Keep Q")
    assert keep_card_after["id"] == keep_card["id"]

    session = get_session()
    try:
        assert session.get(ReviewState, keep_card["id"]) is not None  # survived
        assert session.get(ReviewState, change_card["id"]) is None  # cascaded away with the old card
    finally:
        session.close()
