"""Multi-source ingestion: per-source parsers sharing a normalize() -> raw_text
contract, with a type-dispatched entrypoint and named rejection errors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from SourceMind.backend.services.ingest.base import (
    EmptySourceError,
    GarbageSourceError,
    IngestError,
    SourceParser,
    UnsupportedSourceError,
    clean_text,
    reject_if_unusable,
)
from SourceMind.backend.services.ingest.markdown import MarkdownParser
from SourceMind.backend.services.ingest.security import (
    SsrfError,
    sanitize_source,
    scan_for_prompt_injection,
    validate_public_url,
)
from SourceMind.backend.services.ingest.pdf import PdfParser
from SourceMind.backend.services.ingest.text import TextParser
from SourceMind.backend.services.ingest.url import UrlParser
from SourceMind.backend.services.ingest.youtube import YouTubeParser

__all__ = [
    "EmptySourceError",
    "GarbageSourceError",
    "IngestError",
    "MarkdownParser",
    "PdfParser",
    "SourceParser",
    "SsrfError",
    "TextParser",
    "UnsupportedSourceError",
    "UrlParser",
    "YouTubeParser",
    "clean_text",
    "normalize_source",
    "reject_if_unusable",
    "sanitize_source",
    "scan_for_prompt_injection",
    "validate_public_url",
    "SUPPORTED_SOURCE_TYPES",
]

# Aliases map user-facing labels to a canonical parser.
_REGISTRY: dict[str, SourceParser] = {
    "text": TextParser(),
    "pasted": TextParser(),
    "markdown": MarkdownParser(),
    "md": MarkdownParser(),
    "url": UrlParser(),
    "html": UrlParser(),
    "youtube": YouTubeParser(),
    "pdf": PdfParser(),
}

SUPPORTED_SOURCE_TYPES = ("text", "markdown", "url", "youtube", "pdf")


def normalize_source(source_type: str, payload: Any) -> str:
    """Normalize a source of the given type into raw_text.

    Raises :class:`UnsupportedSourceError` for unknown types and the parser's
    own :class:`EmptySourceError` / :class:`GarbageSourceError` for unusable input.
    """
    parser = _REGISTRY.get((source_type or "").strip().lower())
    if parser is None:
        raise UnsupportedSourceError(
            f"Unsupported source type: {source_type!r}. Supported: {', '.join(SUPPORTED_SOURCE_TYPES)}."
        )
    return parser.normalize(payload)
