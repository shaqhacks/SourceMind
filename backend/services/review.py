"""ReviewState-backed spaced repetition using an SM-2-style algorithm.

Public API
----------
grade_card(session, course_id, section_id, card_index, correct=None, quality=None, now=None) -> ReviewState
due_cards(session, course_id, now=None) -> list[ReviewState]
due_cards_all(session, now=None) -> list[ReviewState]
review_stats(session, now=None, daily_goal=None) -> dict
"""

from __future__ import annotations

import os
from datetime import datetime, date, timedelta, timezone

from sqlalchemy.orm import Session

from SourceMind.backend.db import models

# SM-2 defaults
_DEFAULT_EASE: float = 2.5
_MIN_EASE: float = 1.3
_EASE_CORRECT_NUDGE: float = 0.05
_EASE_WRONG_PENALTY: float = 0.2


def grade_card(
    session: Session,
    course_id: str,
    section_id: str,
    card_index: int,
    correct: bool | None = None,
    quality: int | None = None,
    now: datetime | None = None,
) -> models.ReviewState:
    """Apply an SM-2-style update to the ReviewState for one flashcard.

    Find or create the row for (course_id, section_id, card_index), update
    ease / interval / reps / due_at, flush to the session, and return it.
    The caller's get_session() context manager commits.

    Parameters
    ----------
    session:    Active SQLAlchemy session (caller owns the transaction).
    course_id:  Course identifier.
    section_id: Section / chapter identifier within the course.
    card_index: Zero-based index of the card within the section.
    correct:    Whether the learner answered correctly (legacy 2-button path).
                Mapped to quality 2 (good) when True, 0 (again) when False.
    quality:    4-button quality (0=again, 1=hard, 2=good, 3=easy).
                Takes precedence over correct when provided.
    now:        Base datetime for due_at computation.  Defaults to UTC now.
                Pass a fixed value in tests for deterministic assertions.
    """
    if correct is None and quality is None:
        raise ValueError("At least one of 'correct' or 'quality' must be provided")

    if now is None:
        now = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Find or create row
    # ------------------------------------------------------------------
    row: models.ReviewState | None = (
        session.query(models.ReviewState)
        .filter_by(course_id=course_id, section_id=section_id, card_index=card_index)
        .first()
    )
    if row is None:
        row = models.ReviewState(
            course_id=course_id,
            section_id=section_id,
            card_index=card_index,
            ease=_DEFAULT_EASE,
            interval=0,
            reps=0,
            due_at="",
        )
        session.add(row)
        session.flush()  # assign PK so subsequent queries in this session find it

    # Resolve defaults for rows that pre-existed with NULL fields
    ease: float = row.ease if row.ease is not None else _DEFAULT_EASE
    interval: int = row.interval if row.interval is not None else 0
    reps: int = row.reps if row.reps is not None else 0

    # ------------------------------------------------------------------
    # Resolve quality from correct when quality not supplied
    # ------------------------------------------------------------------
    if quality is None:
        quality = 2 if correct else 0

    # ------------------------------------------------------------------
    # SM-2-style update (4-button)
    # ------------------------------------------------------------------
    if quality == 0:  # again
        reps = 0
        interval = 1
        ease = max(_MIN_EASE, ease - _EASE_WRONG_PENALTY)
    elif quality == 1:  # hard
        reps += 1
        interval = max(1, round(interval * 1.2))
        ease = max(_MIN_EASE, ease - 0.15)
    elif quality == 2:  # good — EXACTLY the existing correct path
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = round(interval * ease)
        ease = max(_MIN_EASE, ease + _EASE_CORRECT_NUDGE)
    elif quality == 3:  # easy
        reps += 1
        interval = max(6, round(interval * ease * 1.3))
        ease = ease + 0.15  # no lower clamp — easy only goes up
    else:
        raise ValueError(f"quality must be 0-3, got {quality!r}")

    due_at = (now + timedelta(days=interval)).isoformat()

    # ------------------------------------------------------------------
    # Persist ReviewState
    # ------------------------------------------------------------------
    row.ease = ease
    row.interval = interval
    row.reps = reps
    row.due_at = due_at

    # ------------------------------------------------------------------
    # Write ReviewLog
    # ------------------------------------------------------------------
    session.add(models.ReviewLog(
        course_id=course_id,
        section_id=section_id,
        card_index=card_index,
        quality=quality,
        created_at=now.isoformat(),
    ))

    return row


def _filter_due(
    rows: list[models.ReviewState],
    now: datetime | None = None,
) -> list[models.ReviewState]:
    """Filter *rows* to those due at or before *now*, ordered by ``due_at`` asc.

    Shared due-selection logic used by both :func:`due_cards` (one course) and
    :func:`due_cards_all` (all courses).  Rows with an empty ``due_at`` string
    are treated as immediately due; unparseable dates are treated as due to
    avoid silently hiding cards.  Empty strings sort before any ISO date string.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure now is timezone-aware for comparison
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    due: list[models.ReviewState] = []
    for row in rows:
        if not row.due_at:
            # Empty due_at → treat as immediately due
            due.append(row)
        else:
            try:
                due_dt = datetime.fromisoformat(row.due_at)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                if due_dt <= now:
                    due.append(row)
            except ValueError:
                # Unparseable date — treat as due to avoid hiding cards
                due.append(row)

    # Sort ascending: empty string ("") sorts before any ISO date string
    due.sort(key=lambda r: r.due_at or "")
    return due


def due_cards(
    session: Session,
    course_id: str,
    now: datetime | None = None,
) -> list[models.ReviewState]:
    """Return all ReviewState rows for *course_id* that are due at or before *now*.

    Rows with an empty ``due_at`` string are treated as immediately due.
    Results are ordered by ``due_at`` ascending (empty strings sort first).

    Parameters
    ----------
    session:   Active SQLAlchemy session.
    course_id: Course identifier.
    now:       Reference datetime.  Defaults to UTC now.
               Pass a fixed value in tests for deterministic behaviour.
    """
    rows: list[models.ReviewState] = (
        session.query(models.ReviewState)
        .filter_by(course_id=course_id)
        .all()
    )
    return _filter_due(rows, now)


def due_cards_all(
    session: Session,
    now: datetime | None = None,
) -> list[models.ReviewState]:
    """Return all due ReviewState rows across *every* course.

    Same due-selection logic as :func:`due_cards` but without the course filter,
    so the result spans all courses.  Empty ``due_at`` is treated as immediately
    due; results are ordered by ``due_at`` ascending.

    Parameters
    ----------
    session: Active SQLAlchemy session.
    now:     Reference datetime.  Defaults to UTC now.
             Pass a fixed value in tests for deterministic behaviour.
    """
    rows: list[models.ReviewState] = session.query(models.ReviewState).all()
    return _filter_due(rows, now)


def review_stats(
    session: Session,
    now: datetime | None = None,
    daily_goal: int | None = None,
) -> dict:
    """Return aggregate review statistics across all courses.

    Parameters
    ----------
    session:    Active SQLAlchemy session.
    now:        Reference datetime (UTC).  Defaults to UTC now.
    daily_goal: Override for the daily review goal.  Falls back to the
                ``SOURCEMIND_DAILY_GOAL`` env var (default 20).

    Returns a dict with keys:
        reviewed_today, streak_days, due_count, total_cards,
        mastered_count, daily_goal.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    today: date = now.date()
    yesterday: date = today - timedelta(days=1)

    # ------------------------------------------------------------------
    # reviewed_today and streak computation via ReviewLog
    # ------------------------------------------------------------------
    all_logs = session.query(models.ReviewLog).all()
    reviewed_today: int = 0
    log_dates: set[date] = set()

    for log in all_logs:
        try:
            log_dt = datetime.fromisoformat(log.created_at)
            log_date = log_dt.date()
            log_dates.add(log_date)
            if log_date == today:
                reviewed_today += 1
        except (ValueError, TypeError, AttributeError):
            pass

    # Determine streak anchor: today (if has logs) else yesterday else 0
    if today in log_dates:
        anchor: date | None = today
    elif yesterday in log_dates:
        anchor = yesterday
    else:
        anchor = None

    if anchor is None:
        streak_days: int = 0
    else:
        streak_days = 0
        current: date = anchor
        while current in log_dates:
            streak_days += 1
            current -= timedelta(days=1)

    # ------------------------------------------------------------------
    # ReviewState aggregates
    # ------------------------------------------------------------------
    due_count: int = len(due_cards_all(session, now))
    total_cards: int = session.query(models.ReviewState).count()
    # interval >= 21 in SQL excludes NULL intervals (NULL >= 21 is unknown),
    # which matches the spec's "treat NULL interval as 0" intent.
    mastered_count: int = (
        session.query(models.ReviewState)
        .filter(models.ReviewState.interval >= 21)
        .count()
    )

    # ------------------------------------------------------------------
    # Daily goal
    # ------------------------------------------------------------------
    if daily_goal is not None:
        goal: int = daily_goal
    else:
        try:
            goal = int(os.environ.get("SOURCEMIND_DAILY_GOAL", "20"))
        except (ValueError, TypeError):
            goal = 20

    return {
        "reviewed_today": reviewed_today,
        "streak_days": streak_days,
        "due_count": due_count,
        "total_cards": total_cards,
        "mastered_count": mastered_count,
        "daily_goal": goal,
    }
