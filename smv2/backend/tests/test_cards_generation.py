from __future__ import annotations

import json

from conftest import _first_section_id

from app.db.engine import get_session
from app.db.models import Card, Job, LlmCall, ReviewState
from app.jobs.worker import run_due_jobs_once
from app.llm.structured_output import CARDS_SCHEMA
from app.llm.provider import (
    PROVIDER_NOT_CONFIGURED_MESSAGE,
    CompletionResult,
    ProviderNotConfiguredError,
)


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


def test_generate_cards_unconfigured_provider_fails_before_job_creation(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    resp = client.post(f"/api/sections/{section_id}/cards")

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["failure_category"] == "missing_credentials"
    assert "ANTHROPIC_API_KEY" in body["detail"]["remediation"]

    session = get_session()
    try:
        assert session.query(Job).filter(Job.type == "generate_cards").count() == 0
    finally:
        session.close()


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
        assert card.prompt_version == "v3"
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


def test_generate_cards_409_when_active_job_exists(client, ingest_course, stub_provider):
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
    assert len(stub_provider.received_completion_options) == 2
    assert all(option.progress is not None for option in stub_provider.received_completion_options)
    assert all(option.is_cancelled is not None for option in stub_provider.received_completion_options)

    cards = client.get(f"/api/sections/{section_id}/cards").json()
    assert len(cards) == 1


def test_generate_cards_schema_sent_on_first_and_repair_completion(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(text="not json at all", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(
            text=json.dumps([{"front": "Q", "back": "A"}]), input_tokens=1, output_tokens=1, model="stub-model"
        ),
    ]

    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    assert stub_provider.complete_call_count == 2
    assert [option.response_schema for option in stub_provider.received_completion_options] == [
        CARDS_SCHEMA,
        CARDS_SCHEMA,
    ]
    repair_content = stub_provider.received_messages[1][-1]["content"]
    assert "valid JSON" in repair_content
    assert "not json at all" not in repair_content


def test_generate_cards_repairs_empty_structured_array(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(text="[]", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(
            text=json.dumps([{"front": "Q", "back": "A"}]),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
        ),
    ]

    resp = client.post(f"/api/sections/{section_id}/cards")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert stub_provider.complete_call_count == 2


def test_generate_cards_records_parse_failure_after_two_all_malformed_arrays(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    malformed = [{"front": "", "back": ""}, "not an object"]

    stub_provider.responses = [
        CompletionResult(text=json.dumps(malformed), input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(text=json.dumps(malformed), input_tokens=1, output_tokens=1, model="stub-model"),
    ]

    resp = client.post(f"/api/sections/{section_id}/cards")
    job_id = resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error_detail"]["code"] == "invalid_model_output"
    session = get_session()
    try:
        calls = session.query(LlmCall).filter(LlmCall.purpose == "cards").order_by(LlmCall.ts).all()
    finally:
        session.close()
    assert [row.status for row in calls] == ["ok", "ok", "parse_failure"]


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
    assert parse_failure_row.prompt_version == "v3"
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
        assert session.query(ReviewState).filter_by(card_id=keep_card["id"]).one_or_none() is not None
        assert session.query(ReviewState).filter_by(card_id=change_card["id"]).one_or_none() is not None
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
        assert session.query(ReviewState).filter_by(card_id=keep_card["id"]).one_or_none() is not None  # survived
        assert session.query(ReviewState).filter_by(card_id=change_card["id"]).one_or_none() is None  # cascaded away with the old card
    finally:
        session.close()


def test_regenerate_cards_preserves_user_edited_card_untouched(client, ingest_course, stub_provider):
    """ADR-023: the regenerate diff's delete side applies ONLY to
    origin='generated' cards. A card the learner edited (origin='user',
    via PATCH /api/cards/{id}) must survive regeneration even though its
    (edited) content is absent from the new generated set entirely.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "Original Q", "back": "Original A"}]),
            input_tokens=1, output_tokens=1, model="stub-model",
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True
    original_card = client.get(f"/api/sections/{section_id}/cards").json()[0]

    edit_resp = client.patch(
        f"/api/cards/{original_card['id']}", json={"front_md": "Edited Q", "back_md": "Edited A"}
    )
    assert edit_resp.status_code == 200
    edited_card_id = edit_resp.json()["id"]
    assert edited_card_id != original_card["id"]

    # Regenerate with completely different content -- the user's edited
    # card shares nothing with the new generated set at all.
    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "Brand New Q", "back": "Brand New A"}]),
            input_tokens=1, output_tokens=1, model="stub-model",
        )
    ]
    resp = client.post(f"/api/sections/{section_id}/cards")
    assert resp.status_code == 202
    assert run_due_jobs_once() is True

    cards_after = client.get(f"/api/sections/{section_id}/cards").json()
    fronts = {c["front_md"] for c in cards_after}
    assert "Edited Q" in fronts  # user-origin card survived
    assert "Brand New Q" in fronts  # new generated card also present
    assert "Original Q" not in fronts  # the pre-edit generated card is long gone

    by_id = {c["id"]: c for c in cards_after}
    assert by_id[edited_card_id]["origin"] == "user"


def test_regenerate_cards_still_replaces_unedited_generated_cards(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "Old Q", "back": "Old A"}]),
            input_tokens=1, output_tokens=1, model="stub-model",
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "New Q", "back": "New A"}]),
            input_tokens=1, output_tokens=1, model="stub-model",
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    cards_after = client.get(f"/api/sections/{section_id}/cards").json()
    fronts = {c["front_md"] for c in cards_after}
    assert fronts == {"New Q"}  # untouched (origin='generated') card replaced, as before ADR-023


def test_regenerate_cards_skips_insert_when_id_collides_with_user_card(client, ingest_course, stub_provider):
    """A user's edit happens to produce EXACTLY the text a later
    regeneration would also produce -- same content-addressed id. The
    user's card (and its review history) must win; no duplicate insert,
    no overwrite.
    """
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "Placeholder Q", "back": "Placeholder A"}]),
            input_tokens=1, output_tokens=1, model="stub-model",
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True
    placeholder_card = client.get(f"/api/sections/{section_id}/cards").json()[0]

    # Edit it to converge on the exact text the NEXT generation will produce.
    edit_resp = client.patch(
        f"/api/cards/{placeholder_card['id']}", json={"front_md": "Converged Q", "back_md": "Converged A"}
    )
    assert edit_resp.status_code == 200
    converged_card_id = edit_resp.json()["id"]
    client.post(f"/api/cards/{converged_card_id}/grade", json={"grade": 3})

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "Converged Q", "back": "Converged A"}]),
            input_tokens=1, output_tokens=1, model="stub-model",
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    cards_after = client.get(f"/api/sections/{section_id}/cards").json()
    assert len(cards_after) == 1
    assert cards_after[0]["id"] == converged_card_id
    assert cards_after[0]["origin"] == "user"

    session = get_session()
    try:
        assert session.query(ReviewState).filter_by(card_id=converged_card_id).one_or_none() is not None  # the user's grade survived
    finally:
        session.close()
