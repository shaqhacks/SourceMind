"""Shared ingest contract: named errors, the normalize() protocol, and the
empty/garbage guard every parser applies before returning raw_text.

Each parser turns one source modality into a single ``raw_text`` string that the
decomposition seam (:meth:`CourseEngine.decompose`) can consume. Parsers reject
empty or garbage input at the door with named errors so the upload layer can map
them to a clear 4xx instead of silently building an unusable course.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable


class IngestError(RuntimeError):
    """Base class for all source-ingestion failures."""


class EmptySourceError(IngestError):
    """The source produced no usable text (e.g. an image-only PDF)."""


class GarbageSourceError(IngestError):
    """The source produced text with no real linguistic content."""


class UnsupportedSourceError(IngestError):
    """No parser is registered for the requested source type."""


@runtime_checkable
class SourceParser(Protocol):
    source_type: str

    def normalize(self, payload) -> str:  # pragma: no cover - structural
        ...


_WS_RUN = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")
_WORD = re.compile(r"[A-Za-z]{2,}")


def clean_text(text: str) -> str:
    """Collapse intra-line whitespace and blank-line runs, then strip."""
    lines = [(_WS_RUN.sub(" ", line)).strip() for line in (text or "").split("\n")]
    joined = "\n".join(line for line in lines if line)
    return _BLANK_LINES.sub("\n", joined).strip()


def reject_if_unusable(text: str, *, source_type: str) -> str:
    """Raise a named error if ``text`` is empty or has no real words.

    Returns the text unchanged when it is usable, so callers can write
    ``return reject_if_unusable(clean_text(raw), source_type=...)``.
    """
    if not text or not text.strip():
        raise EmptySourceError(f"The {source_type} source contained no extractable text.")
    words = _WORD.findall(text)
    # Require a minimum of real (>=2 letter) words; symbol/noise-only input fails.
    if len(words) < 3:
        raise GarbageSourceError(
            f"The {source_type} source did not contain enough readable text to structure."
        )
    return text
