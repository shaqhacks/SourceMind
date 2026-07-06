"""Shared helpers for pipeline job handlers (ingest, lesson/cards/quiz
generation): job progress reporting and defensive code-fence stripping of
LLM output. Framework-free, and deliberately free of any app.llm import —
ingest.py (one of this module's callers) must never import anything
LLM-related (ADR-010).
"""

from __future__ import annotations

from datetime import timedelta

from app.db.engine import get_session
from app.db.models import Job, utcnow

PROGRESS_LEASE_EXTENSION_SECONDS = 60


def report_progress(job_id: str, stage: str, pct: int, message: str) -> None:
    """Progress is observability, never a transaction boundary for pipeline
    data — this uses its OWN short-lived session rather than the caller's,
    so a mid-pipeline progress heartbeat can never accidentally commit
    whatever the caller's own session has pending (a real bug: ingest's
    destructive deletes were getting committed early this way, so a later
    failure left old content destroyed and new content incomplete).

    SAFE ONLY when the caller's own session has no uncommitted pending
    writes at the moment of the call — SQLite allows exactly one writer at
    a time, so this call's own commit would otherwise contend for that same
    writer lock against the caller's still-open transaction (observed in
    practice: it deadlocks until busy_timeout, then raises "database is
    locked"). Use report_progress_in_session for any heartbeat that happens
    after the caller has already staged uncommitted writes of its own —
    every pipeline's final "done" report qualifies, since section/card/
    chunk/attempt writes are always pending at that point.
    """
    session = get_session()
    try:
        job = session.get(Job, job_id)
        if job is None:
            return
        job.progress = {"stage": stage, "pct": pct, "message": message}
        job.lease_until = utcnow() + timedelta(seconds=PROGRESS_LEASE_EXTENSION_SECONDS)
        session.commit()
    finally:
        session.close()


def report_progress_in_session(job: Job, stage: str, pct: int, message: str) -> None:
    """Counterpart to report_progress for heartbeats that happen while the
    caller's OWN session already has uncommitted pending writes — updates
    job.progress in place on the caller's own Job instance, riding along
    with whatever commit the caller eventually makes, instead of opening a
    second session that would contend for SQLite's single writer lock
    against the caller's own open transaction.

    Deliberately does NOT renew the lease: a renewal that isn't
    independently visible to another session (e.g. the reconciler) until
    the caller's own eventual commit wouldn't give it any EARLIER
    visibility than that commit already will, so there's nothing gained by
    touching lease_until here specifically. The prior heartbeat made via
    report_progress (before the caller started its destructive/write
    phase) already extended the lease with a fresh window that comfortably
    covers this phase — pure local DB writes with no network/LLM calls.
    """
    job.progress = {"stage": stage, "pct": pct, "message": message}


def strip_leading_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines:
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
