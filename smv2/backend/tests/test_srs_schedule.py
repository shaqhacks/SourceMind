from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.srs_service import AGAIN, DEFAULT_EASE, EASY, GOOD, HARD, schedule_next


def _assert_due_around(due_at: datetime, expected_delta: timedelta, tolerance_seconds: float = 5.0) -> None:
    now = datetime.now(timezone.utc)
    expected = now + expected_delta
    assert abs((due_at - expected).total_seconds()) < tolerance_seconds


def test_again_from_new_card():
    result = schedule_next(AGAIN, interval_days=0.0, ease=DEFAULT_EASE, reps=0)
    assert result.interval_days == 0.0
    assert result.ease == pytest.approx(2.3)
    assert result.reps == 0
    assert result.lapses_delta == 1
    _assert_due_around(result.due_at, timedelta(minutes=10))


def test_again_floors_ease_at_1_3():
    result = schedule_next(AGAIN, interval_days=5.0, ease=1.35, reps=3)
    assert result.ease == pytest.approx(1.3)
    assert result.reps == 0
    assert result.lapses_delta == 1


def test_first_good_is_fixed_one_day():
    result = schedule_next(GOOD, interval_days=0.0, ease=DEFAULT_EASE, reps=0)
    assert result.interval_days == pytest.approx(1.0)
    assert result.ease == pytest.approx(DEFAULT_EASE)  # unchanged on Good
    assert result.reps == 1
    assert result.lapses_delta == 0
    _assert_due_around(result.due_at, timedelta(days=1))


def test_second_good_is_fixed_six_days():
    result = schedule_next(GOOD, interval_days=1.0, ease=DEFAULT_EASE, reps=1)
    assert result.interval_days == pytest.approx(6.0)
    assert result.ease == pytest.approx(DEFAULT_EASE)
    assert result.reps == 2


def test_third_good_uses_interval_times_ease():
    result = schedule_next(GOOD, interval_days=6.0, ease=DEFAULT_EASE, reps=2)
    assert result.interval_days == pytest.approx(6.0 * DEFAULT_EASE)
    assert result.ease == pytest.approx(DEFAULT_EASE)
    assert result.reps == 3


def test_hard_from_new_card():
    result = schedule_next(HARD, interval_days=0.0, ease=DEFAULT_EASE, reps=0)
    assert result.interval_days == pytest.approx(1.0 * 1.2)
    assert result.ease == pytest.approx(2.35)
    assert result.reps == 1
    assert result.lapses_delta == 0


def test_hard_at_reps_2_uses_actual_interval():
    result = schedule_next(HARD, interval_days=10.0, ease=2.0, reps=2)
    assert result.interval_days == pytest.approx(10.0 * 1.2)
    assert result.ease == pytest.approx(1.85)
    assert result.reps == 3


def test_hard_floors_ease_at_1_3():
    result = schedule_next(HARD, interval_days=5.0, ease=1.4, reps=3)
    assert result.ease == pytest.approx(1.3)


def test_easy_from_new_card():
    result = schedule_next(EASY, interval_days=0.0, ease=DEFAULT_EASE, reps=0)
    assert result.interval_days == pytest.approx(1.0 * 1.3)
    assert result.ease == pytest.approx(2.65)
    assert result.reps == 1
    assert result.lapses_delta == 0


def test_easy_at_reps_1_uses_six_day_baseline():
    result = schedule_next(EASY, interval_days=1.0, ease=DEFAULT_EASE, reps=1)
    assert result.interval_days == pytest.approx(6.0 * 1.3)
    assert result.ease == pytest.approx(2.65)
    assert result.reps == 2


def test_easy_at_reps_2_uses_interval_times_ease_times_1_3():
    result = schedule_next(EASY, interval_days=6.0, ease=DEFAULT_EASE, reps=2)
    assert result.interval_days == pytest.approx(6.0 * DEFAULT_EASE * 1.3)
    assert result.ease == pytest.approx(2.65)
    assert result.reps == 3


def test_invalid_grade_raises():
    with pytest.raises(ValueError):
        schedule_next(0, interval_days=0.0, ease=DEFAULT_EASE, reps=0)
    with pytest.raises(ValueError):
        schedule_next(5, interval_days=0.0, ease=DEFAULT_EASE, reps=0)


def test_srs_schedule():
    """Exhaustive table of (grade, interval_days, ease, reps) -> expected
    (interval_days, ease, reps, lapses_delta), matching the documented
    interpretation in app/services/srs_service.py.
    """
    cases = [
        # grade,  interval, ease, reps -> (expected_interval, expected_ease, expected_reps, expected_lapses_delta)
        (AGAIN, 0.0, 2.5, 0, (0.0, 2.3, 0, 1)),
        (AGAIN, 5.0, 1.35, 3, (0.0, 1.3, 0, 1)),
        (HARD, 0.0, 2.5, 0, (1.2, 2.35, 1, 0)),
        (HARD, 10.0, 2.0, 2, (12.0, 1.85, 3, 0)),
        (HARD, 5.0, 1.4, 3, (6.0, 1.3, 4, 0)),
        (GOOD, 0.0, 2.5, 0, (1.0, 2.5, 1, 0)),
        (GOOD, 1.0, 2.5, 1, (6.0, 2.5, 2, 0)),
        (GOOD, 6.0, 2.5, 2, (15.0, 2.5, 3, 0)),
        (EASY, 0.0, 2.5, 0, (1.3, 2.65, 1, 0)),
        (EASY, 1.0, 2.5, 1, (7.8, 2.65, 2, 0)),
        (EASY, 6.0, 2.5, 2, (19.5, 2.65, 3, 0)),
    ]

    for grade, interval_days, ease, reps, expected in cases:
        expected_interval, expected_ease, expected_reps, expected_lapses = expected
        result = schedule_next(grade, interval_days=interval_days, ease=ease, reps=reps)
        case_id = (grade, interval_days, ease, reps)
        assert result.interval_days == pytest.approx(expected_interval), case_id
        assert result.ease == pytest.approx(expected_ease), case_id
        assert result.reps == expected_reps, case_id
        assert result.lapses_delta == expected_lapses, case_id
