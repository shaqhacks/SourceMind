"""Job type -> handler registry.

Each handler takes (session, job) and returns a JSON-serializable result dict.
Handlers must not commit/rollback the session themselves — the worker owns
the transaction boundary so it can persist success/failure atomically.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import Job

JobHandler = Callable[[Session, Job], dict[str, Any]]


def _noop_handler(session: Session, job: Job) -> dict[str, Any]:
    return {"ok": True}


JOB_HANDLERS: dict[str, JobHandler] = {
    "noop": _noop_handler,
}
