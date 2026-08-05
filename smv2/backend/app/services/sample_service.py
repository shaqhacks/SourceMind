"""First-run sample course: the first time the app starts with an empty
course list, seed a bundled "Learning with SourceMind" course so a new
user has something to read immediately (teach by doing) instead of a blank
dashboard.

Idempotent by TWO guards, not one: the courses-table-empty check alone
would resurrect the sample every time someone deletes it and restarts the
app, so a marker file (data_dir()/sample_seeded) additionally remembers
"this has already happened, ever" independent of the current state of the
courses table.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.config import data_dir, sample_course_enabled
from app.db.engine import get_session
from app.db.models import Course, utcnow
from app.services import assets_service, courses_service, jobs_service

logger = logging.getLogger(__name__)

# app/services/sample_service.py -> app/services -> app -> backend (NOT
# app.config.repo_root(), which points at the outer smv2 monorepo root —
# see the identical note in app/llm/prompts.py).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_SAMPLE_PDF_PATH = _BACKEND_ROOT / "assets" / "sample" / "welcome.pdf"

_SAMPLE_COURSE_TITLE = "Welcome to SourceMind"
_MARKER_FILENAME = "sample_seeded"
_MARKER_COURSE_ID_RE = re.compile(r"\bcourse_id=([^\s]+)")


def _marker_path() -> Path:
    return data_dir() / _MARKER_FILENAME


def _any_course_exists() -> bool:
    session = get_session()
    try:
        return session.query(Course).first() is not None
    finally:
        session.close()


def _course_id_from_marker(marker_text: str) -> str | None:
    match = _MARKER_COURSE_ID_RE.search(marker_text)
    if match is None:
        return None
    return match.group(1)


def reconcile_sample_course_marker() -> bool:
    """Mark the course recorded in the first-run marker as the bundled sample.

    The marker lives in the data directory, so this filesystem-dependent
    backfill belongs at startup instead of in an Alembic migration.
    """
    marker = _marker_path()
    try:
        marker_text = marker.read_text()
    except FileNotFoundError:
        return False
    except OSError:
        logger.exception("failed to read sample course marker")
        return False

    course_id = _course_id_from_marker(marker_text)
    if course_id is None:
        return False

    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            return False
        if course.is_sample:
            return False
        course.is_sample = True
        session.commit()
        return True
    finally:
        session.close()


class _LocalFileReader:
    """Adapts a plain on-disk file to the async-read duck type
    assets_service.save_upload expects (normally a FastAPI UploadFile) —
    the bundled sample PDF is small and already local, so a blocking read
    inside this async method is a non-issue.
    """

    def __init__(self, path: Path) -> None:
        self._f = path.open("rb")

    async def read(self, size: int = -1) -> bytes:
        return self._f.read(size)

    def close(self) -> None:
        self._f.close()


async def _seed() -> None:
    course = courses_service.create_course(_SAMPLE_COURSE_TITLE)
    _mark_course_as_sample(course.id)

    reader = _LocalFileReader(_SAMPLE_PDF_PATH)
    try:
        await assets_service.save_upload(course.id, "welcome.pdf", "application/pdf", reader)
    finally:
        reader.close()

    jobs_service.create_job("ingest", {"course_id": course.id})
    courses_service.set_course_status(course.id, "ingesting")

    marker = _marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"seeded course_id={course.id} at {utcnow().isoformat()}\n")


def _mark_course_as_sample(course_id: str) -> bool:
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            return False
        course.is_sample = True
        session.commit()
        return True
    finally:
        session.close()


async def seed_sample_course_if_first_run() -> None:
    """Called from app startup (lifespan), after reconcile_interrupted_jobs.
    Any failure here (e.g. the bundled PDF missing from a broken install) is
    logged and swallowed rather than propagated — this is a nice-to-have
    onboarding aid, never something that should block the app from
    starting.
    """
    if _marker_path().exists():
        reconcile_sample_course_marker()
        return
    if not sample_course_enabled():
        return
    if _any_course_exists():
        return

    try:
        await _seed()
    except Exception:
        logger.exception("failed to seed first-run sample course; continuing without it")
