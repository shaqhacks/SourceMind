"""PDF source parser (extraction relocated out of the upload router).

Wraps pypdf to turn a PDF file into a single raw_text string, one cleaned line
group per page. The reader factory is injectable so the parser's normalize/guard
logic can be tested deterministically without a binary fixture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - pypdf is a declared dependency
    PdfReader = None

from SourceMind.backend.services.ingest.base import (
    EmptySourceError,
    clean_text,
    reject_if_unusable,
)


class PdfParser:
    source_type = "pdf"

    def __init__(self, reader_factory: Callable[[str], object] | None = None) -> None:
        self._reader_factory = reader_factory or PdfReader

    def normalize(self, payload: str | Path) -> str:
        if self._reader_factory is None:  # pragma: no cover - misconfiguration guard
            raise RuntimeError("pypdf is not installed; cannot parse PDF sources.")
        path = Path(payload)
        try:
            reader = self._reader_factory(str(path))
        except Exception as exc:
            raise EmptySourceError(
                f"Could not read PDF text from {path.name}. Confirm it is a valid, text-selectable PDF."
            ) from exc
        page_texts = [clean_text(page.extract_text() or "") for page in reader.pages]
        joined = "\n".join(text for text in page_texts if text)
        return reject_if_unusable(joined, source_type=self.source_type)
