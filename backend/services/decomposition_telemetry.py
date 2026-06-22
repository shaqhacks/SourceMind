"""Structured logging for every decomposition (T6).

Emits one JSON record per decomposition on the ``sourcemind.decomposition``
logger, capturing the source hash, the raw model output (if any), the parsed
competency tree, and the eval rubric score. This is the audit trail that lets us
reconstruct *why* any course came out the way it did from a source we no longer
hold, and to spot quality regressions over time.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from SourceMind.backend.services.decomposition_eval import score_competency_tree

if TYPE_CHECKING:  # pragma: no cover - typing only
    from SourceMind.backend.services.course_engine import CompetencyTree

logger = logging.getLogger("sourcemind.decomposition")

# Cap how much raw model output we copy into a log record.
_RAW_OUTPUT_LOG_LIMIT = 4000


def source_hash(source_text: str) -> str:
    return hashlib.sha256((source_text or "").encode("utf-8")).hexdigest()


def build_record(
    source_text: str,
    tree: CompetencyTree,
    *,
    raw_llm_output: str | None = None,
    capped: bool = False,
    page_count: int | None = None,
) -> dict[str, Any]:
    score = score_competency_tree(tree)
    raw = None
    if raw_llm_output is not None:
        raw = raw_llm_output[:_RAW_OUTPUT_LOG_LIMIT]
    return {
        "event": "decomposition",
        "created_at": datetime.now(UTC).isoformat(),
        "source_sha256": source_hash(source_text),
        "source_chars": len(source_text or ""),
        "page_count": page_count,
        "capped": capped,
        "raw_llm_output": raw,
        "chapters_count": len(tree.chapters),
        "competencies": [
            {"id": c.id, "title": c.title, "prerequisite_ids": list(c.prerequisite_ids)}
            for c in tree.competencies
        ],
        "eval": score.to_dict(),
    }


def log_decomposition(
    source_text: str,
    tree: CompetencyTree,
    *,
    raw_llm_output: str | None = None,
    capped: bool = False,
    page_count: int | None = None,
) -> dict[str, Any]:
    """Build, emit (as JSON on the decomposition logger), and return the record."""
    record = build_record(
        source_text,
        tree,
        raw_llm_output=raw_llm_output,
        capped=capped,
        page_count=page_count,
    )
    logger.info(json.dumps(record))
    return record
