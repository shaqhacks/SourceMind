"""Deterministic SM-2-variant spaced repetition scheduler — schedule_next()
is a pure function of the card's current review state, no LLM involved,
ever. Grades: 1=Again, 2=Hard, 3=Good, 4=Easy.

Interpretive choices beyond the literal brief (documented here since the
source spec left them implicit and a reviewer should be able to see the
reasoning rather than have to reverse-engineer it from the numbers):
- `reps` counts consecutive non-Again grades, reset to 0 on Again.
- The first two non-Again reviews (reps 0 and 1) use fixed baseline
  intervals of 1 day and 6 days respectively (classic SM-2 behavior) for
  Hard/Good/Easy alike, not just Good — otherwise a brand-new card's
  interval_days=0 would multiply out to 0 regardless of grade. Good's
  bootstrap intervals (1d/6d) are used as-is, with no ease multiplier,
  matching "first Good: 1d, second: 6d" literally; Easy's bootstrap applies
  its 1.3x bonus on top of that same baseline but likewise skips the ease
  multiplier until reps >= 2 (ease hasn't been "proven" over enough
  repetitions yet to trust multiplying by it).
- Interval multiplications that DO use ease use the ease factor as it was
  BEFORE this grade's adjustment — the adjustment takes effect for the
  NEXT review, not retroactively for this one.
- Ease reductions (Again, Hard) are floored at 1.3; ease increases (Easy)
  have no ceiling (spec doesn't call for one).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from app.db.engine import get_session
from app.db.models import Card, Course, ReviewLog, ReviewState, utcnow

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
_VALID_GRADES = {AGAIN, HARD, GOOD, EASY}

DEFAULT_EASE = 2.5
_MIN_EASE = 1.3
_AGAIN_DUE_MINUTES = 10
_FIRST_INTERVAL_DAYS = 1.0
_SECOND_INTERVAL_DAYS = 6.0
_EASY_BONUS = 1.3


@dataclass
class ScheduleResult:
    interval_days: float
    ease: float
    due_at: datetime
    reps: int
    lapses_delta: int


def _baseline_interval(current_interval_days: float, reps: int) -> float:
    if reps == 0:
        return _FIRST_INTERVAL_DAYS
    if reps == 1:
        return _SECOND_INTERVAL_DAYS
    return current_interval_days


def schedule_next(grade: int, *, interval_days: float, ease: float, reps: int) -> ScheduleResult:
    """Pure function: given the CURRENT state (before this grade) and the
    grade just given, returns the NEXT state.
    """
    if grade not in _VALID_GRADES:
        raise ValueError(f"invalid grade: {grade} (must be 1-4)")

    now = utcnow()

    if grade == AGAIN:
        new_ease = max(_MIN_EASE, ease - 0.2)
        return ScheduleResult(
            interval_days=0.0,
            ease=new_ease,
            due_at=now + timedelta(minutes=_AGAIN_DUE_MINUTES),
            reps=0,
            lapses_delta=1,
        )

    baseline = _baseline_interval(interval_days, reps)

    if grade == HARD:
        new_ease = max(_MIN_EASE, ease - 0.15)
        new_interval = baseline * 1.2
        return ScheduleResult(
            interval_days=new_interval,
            ease=new_ease,
            due_at=now + timedelta(days=new_interval),
            reps=reps + 1,
            lapses_delta=0,
        )

    if grade == GOOD:
        new_interval = baseline if reps < 2 else baseline * ease
        return ScheduleResult(
            interval_days=new_interval,
            ease=ease,
            due_at=now + timedelta(days=new_interval),
            reps=reps + 1,
            lapses_delta=0,
        )

    # EASY
    new_ease = ease + 0.15
    new_interval = (baseline if reps < 2 else baseline * ease) * _EASY_BONUS
    return ScheduleResult(
        interval_days=new_interval,
        ease=new_ease,
        due_at=now + timedelta(days=new_interval),
        reps=reps + 1,
        lapses_delta=0,
    )


def _due_counts(session, course_id: str, now: datetime) -> dict[str, int]:
    due_count = (
        session.query(ReviewState)
        .filter(ReviewState.course_id == course_id, ReviewState.due_at <= now)
        .count()
    )
    new_count = (
        session.query(Card)
        .outerjoin(ReviewState, ReviewState.card_id == Card.id)
        .filter(Card.course_id == course_id, ReviewState.card_id.is_(None))
        .count()
    )
    total_count = session.query(Card).filter(Card.course_id == course_id).count()
    return {"due": due_count, "new": new_count, "total": total_count}


def get_review_queue(course_id: str, limit: int = 20) -> dict[str, Any]:
    """due cards: ReviewState.due_at <= now OR no ReviewState yet (new).
    Ordered by COALESCE(due_at, created_at) then created_at — a fully
    stable sort (never changes between two calls against the same data),
    so closing and reopening the queue resumes mid-queue for free: the
    cards already reviewed this session are no longer "due" (their new
    due_at moved into the future), and everything else keeps its same
    relative order.
    """
    session = get_session()
    try:
        now = utcnow()
        order_key = func.coalesce(ReviewState.due_at, Card.created_at)

        rows = (
            session.query(Card, ReviewState)
            .outerjoin(ReviewState, ReviewState.card_id == Card.id)
            .filter(Card.course_id == course_id)
            .filter((ReviewState.due_at.is_(None)) | (ReviewState.due_at <= now))
            .order_by(order_key.asc(), Card.created_at.asc())
            .limit(limit)
            .all()
        )

        cards = [
            {
                "id": card.id,
                "section_id": card.section_id,
                "front_md": card.front_md,
                "back_md": card.back_md,
                "due_at": review_state.due_at if review_state else None,
                "is_new": review_state is None,
            }
            for card, review_state in rows
        ]

        counts = _due_counts(session, course_id, now)
        return {"cards": cards, **counts}
    finally:
        session.close()


def grade_card(card_id: str, grade: int, elapsed_ms: int | None = None) -> dict[str, Any] | None:
    session = get_session()
    try:
        card = session.get(Card, card_id)
        if card is None:
            return None

        review_state = session.get(ReviewState, card_id)
        if review_state is None:
            current_interval, current_ease, current_reps = 0.0, DEFAULT_EASE, 0
        else:
            current_interval = review_state.interval_days
            current_ease = review_state.ease
            current_reps = review_state.reps

        result = schedule_next(grade, interval_days=current_interval, ease=current_ease, reps=current_reps)

        if review_state is None:
            review_state = ReviewState(
                card_id=card_id,
                course_id=card.course_id,
                due_at=result.due_at,
                interval_days=result.interval_days,
                ease=result.ease,
                reps=result.reps,
                lapses=result.lapses_delta,
                last_grade=grade,
            )
            session.add(review_state)
        else:
            review_state.due_at = result.due_at
            review_state.interval_days = result.interval_days
            review_state.ease = result.ease
            review_state.reps = result.reps
            review_state.lapses += result.lapses_delta
            review_state.last_grade = grade

        session.add(
            ReviewLog(
                card_id=card_id, course_id=card.course_id, graded_at=utcnow(), grade=grade,
                elapsed_ms=elapsed_ms,
            )
        )
        session.commit()

        counts = _due_counts(session, card.course_id, utcnow())
        return {"next_due_at": result.due_at, "remaining_due": counts["due"] + counts["new"]}
    finally:
        session.close()


def get_review_summary() -> dict[str, Any]:
    session = get_session()
    try:
        now = utcnow()
        courses = session.query(Course).all()

        per_course = []
        due_total = 0
        for course in courses:
            counts = _due_counts(session, course.id, now)
            per_course.append(
                {"course_id": course.id, "title": course.title, "due_count": counts["due"], "new_count": counts["new"]}
            )
            due_total += counts["due"]

        seven_days_ago = now - timedelta(days=7)
        grades_last_7d = session.query(ReviewLog).filter(ReviewLog.graded_at >= seven_days_ago).count()
        daily_throughput = grades_last_7d / 7.0

        backlog_warning = due_total > 2 * daily_throughput and due_total > 20

        return {
            "courses": per_course,
            "due_total": due_total,
            "daily_throughput": daily_throughput,
            "backlog_warning": backlog_warning,
        }
    finally:
        session.close()
