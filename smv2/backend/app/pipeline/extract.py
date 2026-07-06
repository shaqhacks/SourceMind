"""Pure PDF IO primitives — no framework imports, no LLM calls.

Raises PdfExtractionError on unreadable/encrypted/corrupt PDFs so callers
(app/pipeline/ingest.py) can isolate a single bad asset without failing the
whole course. A scanned/image-only PDF is NOT an error here — it just
converts to sparse/empty per-page text, which the caller can detect and
flag on the Asset rather than treat as a hard failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

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


# Bit 4 (value 16) of a PyMuPDF text span's `flags` field is the bold bit —
# see fitz.TEXT_FONT_BOLD; the other bits (italic/serifed/monospaced/
# superscript) aren't relevant to heading detection.
_BOLD_FLAG_BIT = 16


def extract_heading_candidates(doc: fitz.Document) -> list[tuple[int, str, float, bool]]:
    """Every text line in the document, in reading order, as
    (0-based page, line text, representative font size, is_bold) tuples —
    raw structural material for app/pipeline/outline_detect.py's
    heading-detection tier. Pure PDF IO (page.get_text("dict") spans), no
    heading/candidate decision-making here — that logic is deliberately
    kept in outline_detect.py as plain-data pure functions, same split as
    get_toc (structure) vs sections_from_toc (decision).

    A line's representative size is the largest span size on that line
    (headings are typically rendered in one uniform larger size covering
    the whole line); is_bold is True if ANY span on the line has the bold
    flag set. Blank/whitespace-only lines are skipped entirely.
    """
    candidates: list[tuple[int, str, float, bool]] = []
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # skip image blocks
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(span.get("text", "") for span in spans)
                if not text.strip():
                    continue
                size = max(span.get("size", 0.0) for span in spans)
                bold = any(bool(int(span.get("flags", 0)) & _BOLD_FLAG_BIT) for span in spans)
                candidates.append((page_index, text, size, bold))
    return candidates


def extract_markdown_pages_in_batches(
    doc: fitz.Document,
    *,
    batch_pages: int,
    on_batch: Callable[[int, int], None] | None = None,
) -> list[str]:
    """Same conversion as extract_markdown_pages, but processes `batch_pages`
    pages at a time and calls on_batch(pages_done, total_pages) after each
    batch completes — lets a caller (ingest.py) report real, incremental
    progress during a long conversion instead of one heartbeat before a
    single blocking call covering the whole document.

    Batching by page subset does NOT change the extracted text: pymupdf4llm
    passed `pages=[...]` still scans the WHOLE document (not just the
    requested subset) to build its header/font-size classification
    (IdentifyHeaders), independent of which pages a given call requests —
    verified empirically to produce byte-identical per-page output to a
    single whole-document call.
    """
    total_pages = doc.page_count
    if total_pages == 0:
        return []
    batch_pages = max(1, batch_pages)
    pymupdf4llm.use_layout(False)

    pages_text: list[str] = []
    for start in range(0, total_pages, batch_pages):
        end = min(start + batch_pages, total_pages)
        page_indices = list(range(start, end))
        try:
            chunks = pymupdf4llm.to_markdown(
                doc, pages=page_indices, page_chunks=True, write_images=False, table_strategy=None
            )
        except Exception as exc:
            raise PdfExtractionError(f"markdown conversion failed: {exc}") from exc

        if len(chunks) != len(page_indices):
            raise PdfExtractionError(
                f"pymupdf4llm returned {len(chunks)} chunks for {len(page_indices)} requested pages"
            )
        pages_text.extend(chunk.get("text", "") or "" for chunk in chunks)
        if on_batch is not None:
            on_batch(end, total_pages)
    return pages_text
