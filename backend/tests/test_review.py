"""Tests for backend/services/review.py — ReviewState-backed spaced repetition."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from SourceMind.backend.db import base, models
from SourceMind.backend.services import review

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2024, 1, 10, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    """Point SOURCEMIND_DB_URL at a fresh tmp SQLite file for each test."""
    db_file = tmp_path / "test_review.db"
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{db_file}")
    base.reset_engine_cache()
    base.init_db()
    yield
    base.reset_engine_cache()


def _ensure_course(session, course_id: str = "c1") -> models.Course:
    """Insert a Course row if it doesn't exist yet (required by FK)."""
    course = session.query(models.Course).filter_by(id=course_id).first()
    if course is None:
        course = models.Course(id=course_id, title="Test Course")
        session.add(course)
        session.flush()
    return course


# ---------------------------------------------------------------------------
# Test 1: grade correct twice — reps increments, interval grows (1 then 6)
# ---------------------------------------------------------------------------


def test_grade_correct_twice_interval_grows():
    """First correct → reps=1, interval=1; second correct → reps=2, interval=6."""
    # First correct answer
    with base.get_session() as s:
        _ensure_course(s, "c1")
        row = review.grade_card(s, "c1", "sec1", 0, correct=True, now=FIXED_NOW)
        assert row.reps == 1
        assert row.interval == 1
        expected_due = (FIXED_NOW + timedelta(days=1)).isoformat()
        assert row.due_at == expected_due

    # Second correct answer
    with base.get_session() as s:
        row = review.grade_card(s, "c1", "sec1", 0, correct=True, now=FIXED_NOW)
        assert row.reps == 2
        assert row.interval == 6
        expected_due = (FIXED_NOW + timedelta(days=6)).isoformat()
        assert row.due_at == expected_due


# ---------------------------------------------------------------------------
# Test 2: grade wrong — interval resets, reps=0, ease drops (clamped >= 1.3)
# ---------------------------------------------------------------------------


def test_grade_wrong_resets_interval_and_drops_ease():
    """After two correct then one wrong: reps=0, interval=1, ease drops but stays >= 1.3."""
    with base.get_session() as s:
        _ensure_course(s, "c2")
        review.grade_card(s, "c2", "sec1", 0, correct=True, now=FIXED_NOW)

    with base.get_session() as s:
        review.grade_card(s, "c2", "sec1", 0, correct=True, now=FIXED_NOW)

    # Grade wrong
    with base.get_session() as s:
        row = review.grade_card(s, "c2", "sec1", 0, correct=False, now=FIXED_NOW)
        assert row.reps == 0
        assert row.interval == 1
        assert row.ease >= 1.3
        assert row.ease < 2.5  # ease must have dropped from the default 2.5


def test_grade_wrong_ease_clamps_at_1_3():
    """Ease never falls below 1.3, no matter how many wrong answers."""
    with base.get_session() as s:
        _ensure_course(s, "c3")

    final_ease = None
    for _ in range(15):
        with base.get_session() as s:
            row = review.grade_card(s, "c3", "sec1", 0, correct=False, now=FIXED_NOW)
            final_ease = row.ease

    assert final_ease is not None
    assert final_ease >= 1.3


# ---------------------------------------------------------------------------
# Test 3: due_cards filters, empty due_at treated as due, ordered ascending
# ---------------------------------------------------------------------------


def test_due_cards_filters_and_orders():
    """due_cards returns past-due and empty-due_at rows; future rows excluded; ordered asc."""
    past = (FIXED_NOW - timedelta(days=5)).isoformat()
    future = (FIXED_NOW + timedelta(days=5)).isoformat()

    with base.get_session() as s:
        _ensure_course(s, "c4")
        # Card 0: past due (should be returned)
        s.add(models.ReviewState(
            course_id="c4", section_id="sec1", card_index=0,
            ease=2.5, interval=1, reps=1, due_at=past,
        ))
        # Card 1: future (should NOT be returned)
        s.add(models.ReviewState(
            course_id="c4", section_id="sec1", card_index=1,
            ease=2.5, interval=6, reps=2, due_at=future,
        ))
        # Card 2: empty due_at (should be returned — treated as due)
        s.add(models.ReviewState(
            course_id="c4", section_id="sec1", card_index=2,
            ease=2.5, interval=0, reps=0, due_at="",
        ))

    with base.get_session() as s:
        due = review.due_cards(s, "c4", now=FIXED_NOW)
        indices = [r.card_index for r in due]

    assert 0 in indices, "Past-due card should be included"
    assert 2 in indices, "Empty-due_at card should be included"
    assert 1 not in indices, "Future card should be excluded"

    # Empty due_at sorts first (empty string < any date string)
    assert indices.index(2) < indices.index(0), "Empty due_at should sort before past due_at"
