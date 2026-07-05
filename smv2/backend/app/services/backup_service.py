"""SQLite backups via VACUUM INTO, pruned to a fixed retention count.

VACUUM INTO copies a consistent snapshot of the live database into a new
file without requiring exclusive access, so it's safe to run while the app
is serving traffic. It's executed on an AUTOCOMMIT connection because
VACUUM (in any form) refuses to run inside a pending transaction.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.config import backup_retention, backups_enabled, data_dir
from app.db.engine import get_engine

_BACKUP_GLOB = "smv2-*.db"
_STALE_AFTER_SECONDS = 24 * 60 * 60


def _backups_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _existing_backups(backups_dir: Path) -> list[Path]:
    return sorted(backups_dir.glob(_BACKUP_GLOB), key=lambda p: p.stat().st_mtime)


def _next_backup_path(backups_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = backups_dir / f"smv2-{timestamp}.db"
    if not base.exists():
        return base
    # Same-second retries (e.g. rapid test loops) must not collide with —
    # and silently fail to overwrite — an existing snapshot.
    suffix = 1
    while True:
        candidate = backups_dir / f"smv2-{timestamp}-{suffix}.db"
        if not candidate.exists():
            return candidate
        suffix += 1


def run_backup() -> Path:
    backups_dir = _backups_dir()
    dest = _next_backup_path(backups_dir)

    engine = get_engine()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("VACUUM INTO :dest"), {"dest": str(dest)})

    _prune_backups(backups_dir)
    return dest


def _prune_backups(backups_dir: Path) -> None:
    keep = backup_retention()
    backups = _existing_backups(backups_dir)
    if len(backups) <= keep:
        return
    for stale in backups[: len(backups) - keep]:
        stale.unlink(missing_ok=True)


def should_run_backup() -> bool:
    if not backups_enabled():
        return False
    backups = _existing_backups(_backups_dir())
    if not backups:
        return True
    newest = backups[-1]
    age_seconds = time.time() - newest.stat().st_mtime
    return age_seconds > _STALE_AFTER_SECONDS
