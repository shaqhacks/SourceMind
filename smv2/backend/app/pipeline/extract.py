"""Pure PDF IO primitives — no framework imports, no LLM calls.

Raises PdfExtractionError on unreadable/encrypted/corrupt PDFs so callers
(app/pipeline/ingest.py) can isolate a single bad asset without failing the
whole course. A scanned/image-only PDF is NOT an error here — it just
converts to sparse/empty per-page text, which the caller can detect and
flag on the Asset rather than treat as a hard failure.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pymupdf4llm


class PdfExtractionError(Exception):
    pass


def open_pdf(pdf_path: Path) -> fitz.Document:
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise PdfExtractionError(f"could not open PDF: {exc}") from exc

    if doc.is_encrypted and doc.needs_pass:
        doc.close()
        raise PdfExtractionError("PDF is password-protected")

    if doc.page_count <= 0:
        doc.close()
        raise PdfExtractionError("PDF has no pages")

    return doc


def get_toc(doc: fitz.Document) -> list[tuple[int, str, int]]:
    """Return (level, title, 0-based page) tuples from the PDF's embedded
    bookmarks. Empty list if there is none — never raises.
    """
    try:
        raw = doc.get_toc(simple=True) or []
    except Exception:
        return []

    entries: list[tuple[int, str, int]] = []
    for item in raw:
        try:
            level, title, page = int(item[0]), str(item[1]), int(item[2])
        except (TypeError, ValueError, IndexError):
            continue
        # get_toc pages are 1-based; convert to 0-based, clamp at 0.
        entries.append((level, title, max(0, page - 1)))
    return entries


def extract_markdown_pages(doc: fitz.Document) -> list[str]:
    """Convert every page to Markdown text via pymupdf4llm.

    use_layout(False) forces the classic heuristic converter instead of the
    onnxruntime-backed ML layout engine (pymupdf-layout) that pymupdf4llm
    defaults to when that package is importable — unnecessary and much
    slower for born-digital textbook PDFs, and it would make extraction
    non-deterministic in ways this pipeline can't tolerate.
    """
    try:
        pymupdf4llm.use_layout(False)
        chunks = pymupdf4llm.to_markdown(
            doc, page_chunks=True, write_images=False, table_strategy=None
        )
    except Exception as exc:
        raise PdfExtractionError(f"markdown conversion failed: {exc}") from exc

    if len(chunks) != doc.page_count:
        raise PdfExtractionError(
            f"pymupdf4llm returned {len(chunks)} chunks for {doc.page_count} pages"
        )
    return [chunk.get("text", "") or "" for chunk in chunks]
