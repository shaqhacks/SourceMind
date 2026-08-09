"""Bridge streamed provider activity into durable job heartbeats."""

from __future__ import annotations

import logging

from app.db.engine import get_session
from app.llm.completion_control import CompletionOptions, CompletionProgress

_HEARTBEAT_INTERVAL_SECONDS = 5

logger = logging.getLogger(__name__)

_ARTIFACT_LABELS = {
    "cards": "flashcards",
    "flashcards": "flashcards",
    "lesson": "lesson",
    "quiz": "quiz",
    "practice": "practice questions",
    "practice_assessment": "practice questions",
    "curriculum": "curriculum draft",
    "concept_practice": "concept practice",
}

_PHASE_VERBS = {
    "loading": "Preparing",
    "thinking": "Thinking",
    "generating": "Generating",
    "finalizing": "Finalizing",
}


def completion_options_for_job(
    job_id: str,
    *,
    artifact: str,
    response_schema: dict | None = None,
) -> CompletionOptions:
    """Return provider completion controls backed by independent job sessions."""
    label = _ARTIFACT_LABELS.get(artifact, "content")
    last_write_elapsed: int | None = None
    last_phase: str | None = None

    def progress(event: CompletionProgress) -> None:
        nonlocal last_write_elapsed, last_phase
        elapsed_seconds = max(0, int(event.elapsed_seconds))
        phase_changed = event.phase != last_phase
        if (
            not phase_changed
            and last_write_elapsed is not None
            and elapsed_seconds - last_write_elapsed < _HEARTBEAT_INTERVAL_SECONDS
        ):
            return

        session = get_session()
        try:
            from app.jobs.worker import job_progress

            job_progress(
                session,
                job_id,
                stage=event.phase,
                pct=None,
                message=_message_for_phase(event.phase, label, elapsed_seconds),
                elapsed_seconds=elapsed_seconds,
                last_activity_seconds=max(0, int(event.seconds_since_activity)),
            )
        except Exception:
            logger.exception("failed to write provider heartbeat")
        finally:
            session.close()

        last_write_elapsed = elapsed_seconds
        last_phase = event.phase

    def is_cancelled() -> bool:
        try:
            from app.services import jobs_service

            return jobs_service.is_cancel_requested(job_id)
        except Exception:
            logger.exception("failed to read job cancellation state")
            return True

    return CompletionOptions(
        progress=progress,
        is_cancelled=is_cancelled,
        response_schema=response_schema,
    )


def _message_for_phase(phase: str, label: str, elapsed_seconds: int) -> str:
    verb = _PHASE_VERBS.get(phase, "Working")
    if phase == "thinking":
        base = verb
    else:
        base = f"{verb} {label}"
    return f"{base} · {_format_elapsed(elapsed_seconds)}"


def _format_elapsed(total_seconds: int) -> str:
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds:02d}s"
