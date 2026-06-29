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


# ---------------------------------------------------------------------------
# Test 4: due_cards_all spans multiple courses
# ---------------------------------------------------------------------------


def test_due_cards_all_spans_courses():
    """due_cards_all returns due rows from every course, not just one."""
    with base.get_session() as s:
        _ensure_course(s, "ca")
        _ensure_course(s, "cb")
        # Empty due_at → due now, one card per course.
        s.add(models.ReviewState(
            course_id="ca", section_id="sec1", card_index=0,
            ease=2.5, interval=0, reps=0, due_at="",
        ))
        s.add(models.ReviewState(
            course_id="cb", section_id="sec1", card_index=0,
            ease=2.5, interval=0, reps=0, due_at="",
        ))

    with base.get_session() as s:
        due = review.due_cards_all(s, now=FIXED_NOW)
        course_ids = {r.course_id for r in due}

    assert "ca" in course_ids, "due_cards_all should include course 'ca'"
    assert "cb" in course_ids, "due_cards_all should include course 'cb'"


# ---------------------------------------------------------------------------
# Test 5: 4-button quality grading — again/hard/good/easy
# ---------------------------------------------------------------------------


def test_grade_card_quality_again_hard_good_easy():
    """Each quality (0-3) produces correct reps/interval/ease updates.

    Seed cards at reps=2, interval=6, ease=2.5 then apply each quality:
      again (0): reps=0, interval=1, ease=max(1.3, 2.5-0.2)=2.3
      hard  (1): reps=3, interval=max(1,round(6*1.2))=7, ease=max(1.3,2.5-0.15)=2.35
                 round(7.2)=7 (straightforward, not a .5 case)
      good  (2): reps=3, interval=round(6*2.5)=15, ease=max(1.3,2.5+0.05)=2.55
                 round(15.0)=15
      easy  (3): reps=3, interval=max(6,round(6*2.5*1.3))=max(6,20)=20, ease=2.65
                 round(19.5)=20 (banker's rounding: 20 is even)
    """
    with base.get_session() as s:
        _ensure_course(s, "cq")
        for sid in ("sagain", "shard", "sgood", "seasy"):
            s.add(models.ReviewState(
                course_id="cq", section_id=sid, card_index=0,
                ease=2.5, interval=6, reps=2, due_at="",
            ))

    # again (0)
    with base.get_session() as s:
        row = review.grade_card(s, "cq", "sagain", 0, quality=0, now=FIXED_NOW)
        assert row.reps == 0
        assert row.interval == 1
        assert row.ease == pytest.approx(2.3)

    # hard (1): round(6*1.2) = round(7.2) = 7
    with base.get_session() as s:
        row = review.grade_card(s, "cq", "shard", 0, quality=1, now=FIXED_NOW)
        assert row.reps == 3
        assert row.interval == 7
        assert row.ease == pytest.approx(2.35)

    # good (2): round(6*2.5) = round(15.0) = 15
    with base.get_session() as s:
        row = review.grade_card(s, "cq", "sgood", 0, quality=2, now=FIXED_NOW)
        assert row.reps == 3
        assert row.interval == 15
        assert row.ease == pytest.approx(2.55)

    # easy (3): round(6*2.5*1.3) = round(19.5) = 20 (banker's rounding, 20 even)
    with base.get_session() as s:
        row = review.grade_card(s, "cq", "seasy", 0, quality=3, now=FIXED_NOW)
        assert row.reps == 3
        assert row.interval == 20
        assert row.ease == pytest.approx(2.65)


# ---------------------------------------------------------------------------
# Test 6: grade_card writes a ReviewLog row
# ---------------------------------------------------------------------------


def test_grade_card_writes_review_log():
    """grade_card inserts exactly one ReviewLog row per call with the resolved quality."""
    with base.get_session() as s:
        _ensure_course(s, "clog")

    # quality=1 (hard) → log quality==1
    with base.get_session() as s:
        review.grade_card(s, "clog", "sec1", 0, quality=1, now=FIXED_NOW)

    with base.get_session() as s:
        logs = (
            s.query(models.ReviewLog)
            .filter_by(course_id="clog")
            .order_by(models.ReviewLog.id)
            .all()
        )
        assert len(logs) == 1
        assert logs[0].quality == 1

    # correct=False → derived quality==0, second log appended
    with base.get_session() as s:
        review.grade_card(s, "clog", "sec1", 0, correct=False, now=FIXED_NOW)

    with base.get_session() as s:
        logs = (
            s.query(models.ReviewLog)
            .filter_by(course_id="clog")
            .order_by(models.ReviewLog.id)
            .all()
        )
        assert len(logs) == 2
        assert logs[1].quality == 0


# ---------------------------------------------------------------------------
# Test 7: review_stats — streak, counts, daily_goal default
# ---------------------------------------------------------------------------


def test_review_stats_streak_and_counts():
    """review_stats computes streak, reviewed_today, mastered_count, total_cards, daily_goal."""
    # FIXED_NOW = 2024-01-10 (today); yesterday = 2024-01-09; day-2 = 2024-01-08
    today_iso = FIXED_NOW.isoformat()
    yesterday_iso = (FIXED_NOW - timedelta(days=1)).isoformat()
    day2_iso = (FIXED_NOW - timedelta(days=2)).isoformat()
    day5_iso = (FIXED_NOW - timedelta(days=5)).isoformat()
    future_iso = (FIXED_NOW + timedelta(days=30)).isoformat()

    with base.get_session() as s:
        _ensure_course(s, "cst")

        # ReviewLog rows: today×2, yesterday×1, day-2×1, day-5×1 (gap before day-3)
        for ts in (today_iso, today_iso, yesterday_iso, day2_iso, day5_iso):
            s.add(models.ReviewLog(
                course_id="cst", section_id="sec1", card_index=0,
                quality=2, created_at=ts,
            ))

        # ReviewState rows: 2 mastered (interval>=21), 1 not mastered (interval=5, due)
        s.add(models.ReviewState(
            course_id="cst", section_id="sec1", card_index=0,
            ease=2.5, interval=21, reps=5, due_at=future_iso,
        ))
        s.add(models.ReviewState(
            course_id="cst", section_id="sec1", card_index=1,
            ease=2.5, interval=30, reps=8, due_at=future_iso,
        ))
        s.add(models.ReviewState(
            course_id="cst", section_id="sec1", card_index=2,
            ease=2.5, interval=5, reps=2, due_at="",
        ))

    with base.get_session() as s:
        stats = review.review_stats(s, now=FIXED_NOW)

    assert stats["reviewed_today"] == 2        # 2 logs on today
    assert stats["streak_days"] == 3           # today + yesterday + day-2; day-3 missing
    assert stats["total_cards"] == 3
    assert stats["mastered_count"] == 2        # interval 21 and 30
    assert stats["due_count"] == 1             # only the empty-due_at card
    assert stats["daily_goal"] == 20           # default from env (not set)


# ---------------------------------------------------------------------------
# Test 8: guard — neither correct nor quality raises ValueError
# ---------------------------------------------------------------------------


def test_grade_card_requires_correct_or_quality():
    """grade_card raises ValueError when neither correct nor quality is given."""
    with base.get_session() as s:
        _ensure_course(s, "cguard")
        with pytest.raises(ValueError):
            review.grade_card(s, "cguard", "sec1", 0, now=FIXED_NOW)


# ---------------------------------------------------------------------------
# Test 9: guard — out-of-range quality raises ValueError
# ---------------------------------------------------------------------------


def test_grade_card_rejects_out_of_range_quality():
    """grade_card raises ValueError for a quality value outside 0-3."""
    with base.get_session() as s:
        _ensure_course(s, "cbadq")
        with pytest.raises(ValueError):
            review.grade_card(s, "cbadq", "sec1", 0, quality=4, now=FIXED_NOW)
