"""ADR-023: card editing (PATCH /api/cards/{id}) and deletion
(DELETE /api/cards/{id}). Content-addressed edit-as-new-card, with
explicit review-history migration to the new id — see
app.services.cards_service.update_card.
"""

from __future__ import annotations

import json

from app.db.engine import get_session
from app.db.models import Card, ReviewLog, ReviewState
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult
from conftest import _first_section_id


def _seed_one_card(client, ingest_course, stub_provider, front="Original Q", back="Original A") -> tuple[str, str]:
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    stub_provider.responses = [
        CompletionResult(text=json.dumps([{"front": front, "back": back}]), input_tokens=1, output_tokens=1, model="stub-model")
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True
    card = client.get(f"/api/sections/{section_id}/cards").json()[0]
    return course_id, card["id"]


def test_update_card_mints_new_id_and_migrates_review_state_and_logs(client, ingest_course, stub_provider):
    course_id, card_id = _seed_one_card(client, ingest_course, stub_provider)

    grade_resp = client.post(f"/api/cards/{card_id}/grade", json={"grade": 3})
    assert grade_resp.status_code == 200

    session = get_session()
    try:
        state_before = session.get(ReviewState, card_id)
        due_before, interval_before, reps_before = (
            state_before.due_at, state_before.interval_days, state_before.reps
        )
        logs_before = session.query(ReviewLog).filter(ReviewLog.card_id == card_id).count()
        assert logs_before == 1
    finally:
        session.close()

    resp = client.patch(f"/api/cards/{card_id}", json={"front_md": "Edited Q", "back_md": "Edited A"})
    assert resp.status_code == 200
    new_card = resp.json()
    new_id = new_card["id"]
    assert new_id != card_id
    assert new_card["front_md"] == "Edited Q"
    assert new_card["origin"] == "user"

    session = get_session()
    try:
        assert session.get(Card, card_id) is None  # old card gone
        assert session.get(ReviewState, card_id) is None
        assert session.query(ReviewLog).filter(ReviewLog.card_id == card_id).count() == 0

        new_state = session.get(ReviewState, new_id)
        assert new_state is not None
        assert new_state.due_at == due_before
        assert new_state.interval_days == interval_before
        assert new_state.reps == reps_before
        assert session.query(ReviewLog).filter(ReviewLog.card_id == new_id).count() == 1
    finally:
        session.close()


def test_update_card_no_op_when_content_unchanged(client, ingest_course, stub_provider):
    course_id, card_id = _seed_one_card(client, ingest_course, stub_provider, front="Same Q", back="Same A")

    resp = client.patch(f"/api/cards/{card_id}", json={"front_md": "Same Q", "back_md": "Same A"})
    assert resp.status_code == 200
    assert resp.json()["id"] == card_id  # identical content -> identical id, no-op

    session = get_session()
    try:
        assert session.query(Card).count() == 1
    finally:
        session.close()


def test_update_card_409_when_edit_duplicates_an_existing_card(client, ingest_course, stub_provider):
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "Q1", "back": "A1"}, {"front": "Q2", "back": "A2"}]),
            input_tokens=1, output_tokens=1, model="stub-model",
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True
    cards = client.get(f"/api/sections/{section_id}/cards").json()
    card1 = next(c for c in cards if c["front_md"] == "Q1")
    card2 = next(c for c in cards if c["front_md"] == "Q2")

    # Edit card1 so its content becomes byte-identical to card2's.
    resp = client.patch(f"/api/cards/{card1['id']}", json={"front_md": "Q2", "back_md": "A2"})
    assert resp.status_code == 409

    session = get_session()
    try:
        assert session.get(Card, card1["id"]) is not None  # untouched
        assert session.get(Card, card2["id"]) is not None
    finally:
        session.close()


def test_update_card_404_for_missing_card(client):
    resp = client.patch("/api/cards/does-not-exist", json={"front_md": "Q", "back_md": "A"})
    assert resp.status_code == 404


def test_delete_card_cascades_review_state_and_logs(client, ingest_course, stub_provider):
    course_id, card_id = _seed_one_card(client, ingest_course, stub_provider)
    assert client.post(f"/api/cards/{card_id}/grade", json={"grade": 3}).status_code == 200

    resp = client.delete(f"/api/cards/{card_id}")
    assert resp.status_code == 204

    session = get_session()
    try:
        assert session.get(Card, card_id) is None
        assert session.get(ReviewState, card_id) is None
        assert session.query(ReviewLog).filter(ReviewLog.card_id == card_id).count() == 0
    finally:
        session.close()


def test_delete_card_404_for_missing_card(client):
    resp = client.delete("/api/cards/does-not-exist")
    assert resp.status_code == 404


def test_list_cards_includes_origin(client, ingest_course, stub_provider):
    course_id, card_id = _seed_one_card(client, ingest_course, stub_provider)
    cards = client.get(f"/api/sections/{_first_section_id(client, course_id)}/cards").json()
    assert all(c["origin"] == "generated" for c in cards)

    client.patch(f"/api/cards/{card_id}", json={"front_md": "New Q", "back_md": "New A"})
    cards_after = client.get(f"/api/sections/{_first_section_id(client, course_id)}/cards").json()
    assert any(c["origin"] == "user" for c in cards_after)
