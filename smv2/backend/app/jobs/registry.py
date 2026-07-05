"""Job type -> handler registry, plus per-type orphan-recovery hooks.

Each handler takes (session, job) and returns a JSON-serializable result dict.
Handlers must not commit/rollback the session themselves — the worker owns
the transaction boundary so it can persist success/failure atomically.

ON_ORPHAN_HOOKS lets a job type override how the reconciler recovers a
lease-expired 'running' job; anything not registered here falls back to
default_on_orphan in the reconciler.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import Job
from app.services.backup_service import run_backup

JobHandler = Callable[[Session, Job], dict[str, Any]]
OrphanHook = Callable[[Session, Job], None]

MAX_ORPHAN_ATTEMPTS = 3


def _noop_handler(session: Session, job: Job) -> dict[str, Any]:
    return {"ok": True}


def _backup_handler(session: Session, job: Job) -> dict[str, Any]:
    path = run_backup()
    return {"path": str(path)}


JOB_HANDLERS: dict[str, JobHandler] = {
    "noop": _noop_handler,
    "backup": _backup_handler,
}


def default_on_orphan(session: Session, job: Job) -> None:
    """Requeue a lease-expired job up to MAX_ORPHAN_ATTEMPTS, then fail it for good."""
    if job.attempts < MAX_ORPHAN_ATTEMPTS:
        job.status = "queued"
        job.lease_until = None
        job.progress = None
    else:
        job.status = "failed"
        job.error = "orphaned by restart"


ON_ORPHAN_HOOKS: dict[str, OrphanHook] = {
    "noop": default_on_orphan,
}
