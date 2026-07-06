"""Shared helpers for pipeline job handlers (ingest, lesson/cards/quiz
generation): job progress reporting and defensive code-fence stripping of
LLM output. Framework-free, and deliberately free of any app.llm import —
ingest.py (one of this module's callers) must never import anything
LLM-related (ADR-010).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.models import Job, utcnow

PROGRESS_LEASE_EXTENSION_SECONDS = 60


def report_progress(session: Session, job: Job, stage: str, pct: int, message: str) -> None:
    job.progress = {"stage": stage, "pct": pct, "message": message}
    job.lease_until = utcnow() + timedelta(seconds=PROGRESS_LEASE_EXTENSION_SECONDS)
    session.commit()


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
