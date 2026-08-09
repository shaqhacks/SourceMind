from __future__ import annotations

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.db.engine import get_session
from app.db.models import Card, Course, ReviewLog, ReviewState, Section, utcnow
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult
from app.services import srs_service


def _generate_two_cards(client, ingest_course, stub_provider) -> tuple[str, str, str]:
    """Returns (course_id, card_id_1, card_id_2)."""
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = client.get(f"/api/courses/{course_id}/sections").json()[0]["id"]

    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([{"front": "Q1", "back": "A1"}, {"front": "Q2", "back": "A2"}]),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
        )
    ]
    client.post(f"/api/sections/{section_id}/cards")
    assert run_due_jobs_once() is True

    cards = client.get(f"/api/sections/{section_id}/cards").json()
    return course_id, cards[0]["id"], cards[1]["id"]


def _review_scope_course(client) -> SimpleNamespace:
    from conftest import _course_profile_id, _set_learner_cookie

    learner_id = _set_learner_cookie(client)
    now = utcnow()
    created_at = now - timedelta(hours=6)

    session = get_session()
    try:
        course = Course(title="Review scopes")
        session.add(course)
        session.flush()
        profile_id = _course_profile_id(session, course.id, learner_id)

        section_1 = Section(
            id=f"review-scope-section-{uuid.uuid4()}",
            course_id=course.id,
            order_index=0,
            title="Section 1",
            body_md="Chapter one material.",
            content_hash=f"review-scope-section-1-{uuid.uuid4()}",
            chapter_label="Chapter 1",
        )
        section_2 = Section(
            id=f"review-scope-section-{uuid.uuid4()}",
            course_id=course.id,
            order_index=1,
            title="Section 2",
            body_md="Chapter two material.",
            content_hash=f"review-scope-section-2-{uuid.uuid4()}",
            chapter_label="Chapter 2",
        )
        session.add_all([section_1, section_2])
        session.flush()

        new_card = Card(
            id=f"review-scope-new-{uuid.uuid4()}",
            course_id=course.id,
            section_id=section_1.id,
            front_md="New?",
            back_md="New.",
            position=0,
            created_at=created_at,
        )
        chapter_2_card = Card(
            id=f"review-scope-chapter-2-{uuid.uuid4()}",
            course_id=course.id,
            section_id=section_2.id,
            front_md="Chapter 2?",
            back_md="Chapter 2.",
            position=1,
            created_at=created_at + timedelta(hours=1),
        )
        due_card = Card(
            id=f"review-scope-due-{uuid.uuid4()}",
            course_id=course.id,
            section_id=section_1.id,
            front_md="Due?",
            back_md="Due.",
            position=2,
            created_at=created_at + timedelta(hours=2),
        )
        future_card = Card(
            id=f"review-scope-future-{uuid.uuid4()}",
            course_id=course.id,
            section_id=section_1.id,
            front_md="Future?",
            back_md="Future.",
            position=3,
            created_at=created_at + timedelta(hours=3),
        )
        latest_again_card = Card(
            id=f"review-scope-again-{uuid.uuid4()}",
            course_id=course.id,
            section_id=section_1.id,
            front_md="Again?",
            back_md="Again.",
            position=4,
            created_at=created_at + timedelta(hours=4),
        )
        latest_good_card = Card(
            id=f"review-scope-good-{uuid.uuid4()}",
            course_id=course.id,
            section_id=section_1.id,
            front_md="Good?",
            back_md="Good.",
            position=5,
            created_at=created_at + timedelta(hours=5),
        )
        session.add_all(
            [
                new_card,
                chapter_2_card,
                due_card,
                future_card,
                latest_again_card,
                latest_good_card,
            ]
        )
        session.flush()
        session.add_all(
            [
                ReviewState(
                    course_learning_profile_id=profile_id,
                    card_id=due_card.id,
                    course_id=course.id,
                    due_at=now - timedelta(hours=4),
                    interval_days=1.0,
                    ease=2.5,
                    reps=1,
                    lapses=0,
                    last_grade=3,
                ),
                ReviewState(
                    course_learning_profile_id=profile_id,
                    card_id=future_card.id,
                    course_id=course.id,
                    due_at=now + timedelta(days=1),
                    interval_days=6.0,
                    ease=2.5,
                    reps=2,
                    lapses=0,
                    last_grade=3,
                ),
                ReviewState(
                    course_learning_profile_id=profile_id,
                    card_id=latest_again_card.id,
                    course_id=course.id,
                    due_at=now + timedelta(days=2),
                    interval_days=0.0,
                    ease=2.3,
                    reps=0,
                    lapses=1,
                    last_grade=1,
                ),
                ReviewState(
                    course_learning_profile_id=profile_id,
                    card_id=latest_good_card.id,
                    course_id=course.id,
                    due_at=now + timedelta(days=3),
                    interval_days=1.0,
                    ease=2.3,
                    reps=1,
                    lapses=1,
                    last_grade=3,
                ),
            ]
        )
        session.commit()

        return SimpleNamespace(
            id=course.id,
            available_ids={new_card.id, chapter_2_card.id, due_card.id},
            available_ordered_ids=[new_card.id, chapter_2_card.id, due_card.id],
            all_ids=[
                new_card.id,
                chapter_2_card.id,
                due_card.id,
                future_card.id,
                latest_again_card.id,
                latest_good_card.id,
            ],
            latest_again_ids=[latest_again_card.id],
            due_id=due_card.id,
            new_id=new_card.id,
            future_id=future_card.id,
            latest_good_id=latest_good_card.id,
            chapter_2_id=chapter_2_card.id,
        )
    finally:
        session.close()


def test_review_queue_includes_new_cards_with_no_review_state(client, ingest_course, stub_provider):
    course_id, card1, card2 = _generate_two_cards(client, ingest_course, stub_provider)

    resp = client.get(f"/api/courses/{course_id}/review/queue")
    assert resp.status_code == 200
    body = resp.json()
    assert body["new"] == 2
    assert body["due"] == 0
    assert body["total"] == 2
    assert {c["id"] for c in body["cards"]} == {card1, card2}
    assert all(c["is_new"] for c in body["cards"])
    # New cards (no ReviewState yet) expose the same bootstrap values
    # grade_card() would use — see srs_service.DEFAULT_EASE.
    assert all(c["interval_days"] == 0.0 for c in body["cards"])
    assert all(c["ease"] == 2.5 for c in body["cards"])
    assert all(c["reps"] == 0 for c in body["cards"])


def test_review_queue_available_scope_is_default_available_cards(client):
    review_course = _review_scope_course(client)

    response = client.get(f"/api/courses/{review_course.id}/review/queue")

    assert response.status_code == 200
    body = response.json()
    assert {card["id"] for card in body["cards"]} == review_course.available_ids
    assert [card["id"] for card in body["cards"]] == review_course.available_ordered_ids


def test_review_queue_all_scope_includes_not_due_cards(client):
    review_course = _review_scope_course(client)

    response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "all", "limit": 200},
    )

    assert response.status_code == 200
    assert [card["id"] for card in response.json()["cards"]] == review_course.all_ids


def test_review_queue_needs_attention_uses_latest_again_state(client):
    review_course = _review_scope_course(client)

    response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "needs_attention"},
    )

    assert response.status_code == 200
    assert [card["id"] for card in response.json()["cards"]] == review_course.latest_again_ids


def test_review_queue_filters_by_exact_chapter_label(client):
    review_course = _review_scope_course(client)

    response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "all", "chapter_label": "Chapter 2"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [card["id"] for card in body["cards"]] == [review_course.chapter_2_id]
    assert {card["chapter_label"] for card in body["cards"]} == {"Chapter 2"}


def test_review_queue_chapter_label_scope_requires_exact_match(client):
    review_course = _review_scope_course(client)

    response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "all", "chapter_label": "chapter 2"},
    )

    assert response.status_code == 200
    assert response.json()["cards"] == []


def test_review_queue_unknown_scope_returns_422(client):
    review_course = _review_scope_course(client)

    response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "unknown"},
    )

    assert response.status_code == 422


def test_get_review_queue_rejects_invalid_service_scope(client):
    review_course = _review_scope_course(client)

    with pytest.raises(ValueError, match="invalid review queue scope"):
        srs_service.get_review_queue(review_course.id, scope="unknown")


def test_review_queue_scope_response_includes_card_metadata(client):
    review_course = _review_scope_course(client)

    response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "all", "limit": 200},
    )

    assert response.status_code == 200
    cards_by_id = {card["id"]: card for card in response.json()["cards"]}
    assert cards_by_id[review_course.new_id]["chapter_label"] == "Chapter 1"
    assert cards_by_id[review_course.new_id]["section_title"] == "Section 1"
    assert cards_by_id[review_course.new_id]["is_due"] is False
    assert cards_by_id[review_course.new_id]["last_grade"] is None
    assert cards_by_id[review_course.due_id]["is_due"] is True
    assert cards_by_id[review_course.due_id]["last_grade"] == 3
    assert cards_by_id[review_course.future_id]["is_due"] is False
    assert cards_by_id[review_course.latest_good_id]["last_grade"] == 3


def test_review_queue_scope_keeps_course_wide_counts_unchanged(client):
    review_course = _review_scope_course(client)

    default_response = client.get(f"/api/courses/{review_course.id}/review/queue")
    all_response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "all", "limit": 200},
    )
    attention_response = client.get(
        f"/api/courses/{review_course.id}/review/queue",
        params={"scope": "needs_attention"},
    )

    assert default_response.status_code == 200
    default_counts = {
        key: default_response.json()[key]
        for key in ("due", "new", "total", "overdue_count", "new_count", "available_count", "total_count")
    }
    assert default_counts == {
        "due": 1,
        "new": 2,
        "total": 6,
        "overdue_count": 1,
        "new_count": 2,
        "available_count": 3,
        "total_count": 6,
    }
    for response in (all_response, attention_response):
        assert response.status_code == 200
        assert {
            key: response.json()[key]
            for key in (
                "due",
                "new",
                "total",
                "overdue_count",
                "new_count",
                "available_count",
                "total_count",
            )
        } == default_counts


def test_review_queue_includes_past_due_and_excludes_future_due(client, ingest_course, stub_provider):
    from conftest import _course_profile_id, _set_learner_cookie

    course_id, card1, card2 = _generate_two_cards(client, ingest_course, stub_provider)
    learner_id = _set_learner_cookie(client)

    session = get_session()
    try:
        profile_id = _course_profile_id(session, course_id, learner_id)
        session.add(
            ReviewState(
                course_learning_profile_id=profile_id,
                card_id=card1, course_id=course_id, due_at=utcnow() - timedelta(hours=1),
                interval_days=1.0, ease=2.5, reps=1, lapses=0,
            )
        )
        session.add(
            ReviewState(
                course_learning_profile_id=profile_id,
                card_id=card2, course_id=course_id, due_at=utcnow() + timedelta(days=5),
                interval_days=6.0, ease=2.5, reps=2, lapses=0,
            )
        )
        session.commit()
    finally:
        session.close()

    resp = client.get(f"/api/courses/{course_id}/review/queue")
    body = resp.json()
    assert body["due"] == 1
    assert body["overdue_count"] == 1
    assert body["new"] == 0
    assert body["new_count"] == 0
    assert body["available_count"] == 1
    assert body["total_count"] == 2
    ids_in_queue = {c["id"] for c in body["cards"]}
    assert card1 in ids_in_queue
    assert card2 not in ids_in_queue
    # A reviewed card's own scheduler state passes through unchanged (not
    # the new-card bootstrap) — mirrors the ReviewState seeded above.
    card1_out = next(c for c in body["cards"] if c["id"] == card1)
    assert card1_out["interval_days"] == 1.0
    assert card1_out["ease"] == 2.5
    assert card1_out["reps"] == 1


def test_review_queue_and_summary_contract_require_canonical_counts(client):
    from app.main import app

    components = app.openapi()["components"]["schemas"]

    for schema_name in ("ReviewQueueOut", "CourseReviewSummaryOut"):
        required = set(components[schema_name]["required"])
        assert {
            "overdue_count",
            "new_count",
            "available_count",
            "total_count",
        }.issubset(required)


def test_review_queue_respects_limit(client, ingest_course, stub_provider):
    course_id, _card1, _card2 = _generate_two_cards(client, ingest_course, stub_provider)

    resp = client.get(f"/api/courses/{course_id}/review/queue?limit=1")
    assert resp.status_code == 200
    assert len(resp.json()["cards"]) == 1


def test_review_queue_404_for_missing_course(client):
    resp = client.get("/api/courses/does-not-exist/review/queue")
    assert resp.status_code == 404


def test_grade_card_creates_review_state_on_first_grade(client, ingest_course, stub_provider):
    from conftest import _course_profile_id, _set_learner_cookie

    course_id, card1, _card2 = _generate_two_cards(client, ingest_course, stub_provider)
    learner_id = _set_learner_cookie(client)

    session = get_session()
    try:
        profile_id = _course_profile_id(session, course_id, learner_id)
        session.commit()
        assert session.get(ReviewState, (profile_id, card1)) is None
    finally:
        session.close()

    resp = client.post(f"/api/cards/{card1}/grade", json={"grade": 3})
    assert resp.status_code == 200
    body = resp.json()
    assert "next_due_at" in body
    assert "remaining_due" in body

    session = get_session()
    try:
        state = session.get(ReviewState, (profile_id, card1))
        assert state is not None
        assert state.interval_days == 1.0  # first Good
        assert state.reps == 1
    finally:
        session.close()


def test_grade_card_writes_review_log(client, ingest_course, stub_provider):
    _course_id, card1, _card2 = _generate_two_cards(client, ingest_course, stub_provider)

    client.post(f"/api/cards/{card1}/grade", json={"grade": 4, "elapsed_ms": 1234})

    session = get_session()
    try:
        logs = session.query(ReviewLog).filter(ReviewLog.card_id == card1).all()
        assert len(logs) == 1
        assert logs[0].grade == 4
        assert logs[0].elapsed_ms == 1234
    finally:
        session.close()


def test_grade_card_404_for_missing_card(client):
    resp = client.post("/api/cards/does-not-exist/grade", json={"grade": 3})
    assert resp.status_code == 404


def test_grade_card_422_for_invalid_grade(client, ingest_course, stub_provider):
    _course_id, card1, _card2 = _generate_two_cards(client, ingest_course, stub_provider)
    resp = client.post(f"/api/cards/{card1}/grade", json={"grade": 9})
    assert resp.status_code == 422


def test_review_summary_aggregates_across_courses(client, ingest_course, stub_provider):
    course_id, _card1, _card2 = _generate_two_cards(client, ingest_course, stub_provider)

    resp = client.get("/api/review/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["due_total"] >= 0
    assert isinstance(body["daily_throughput"], float)
    assert isinstance(body["backlog_warning"], bool)
    matching = [c for c in body["courses"] if c["course_id"] == course_id]
    assert len(matching) == 1
    assert matching[0]["due_count"] == 0
    assert matching[0]["overdue_count"] == 0
    assert matching[0]["new_count"] == 2
    assert matching[0]["available_count"] == 2
    assert matching[0]["total_count"] == 2


def test_review_summary_backlog_warning_flags_large_backlog(client, ingest_course, stub_provider):
    from conftest import _course_profile_id, _set_learner_cookie

    course_id, card1, _card2 = _generate_two_cards(client, ingest_course, stub_provider)
    learner_id = _set_learner_cookie(client)

    # Seed 25 due ReviewStates with zero recent throughput -> backlog warning.
    session = get_session()
    try:
        profile_id = _course_profile_id(session, course_id, learner_id)
        for i in range(25):
            c = Card(
                id=f"backlog-card-{i}", course_id=course_id,
                section_id=session.query(Card).filter(Card.id == card1).one().section_id,
                front_md=f"F{i}", back_md=f"B{i}", position=100 + i,
            )
            session.add(c)
            session.flush()
            session.add(
                ReviewState(
                    course_learning_profile_id=profile_id,
                    card_id=c.id, course_id=course_id, due_at=utcnow() - timedelta(hours=1),
                    interval_days=1.0, ease=2.5, reps=1, lapses=0,
                )
            )
        session.commit()
    finally:
        session.close()

    resp = client.get("/api/review/summary")
    body = resp.json()
    assert body["due_total"] > 20
    assert body["backlog_warning"] is True
