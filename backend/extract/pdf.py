"""PyMuPDF-based PDF text and image extraction.

Page text is layout-aware Markdown (headings from font size, reflowed
paragraphs, lists) produced by ``pymupdf4llm`` when available and enabled —
see ADR-011. Falls back to PyMuPDF's plain-text extraction if pymupdf4llm is
missing, fails to import/convert, or is disabled via
``config.pdf_markdown_extraction()``. Never raises over formatting: worst
case is the same plain text this module has always produced.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from SourceMind.backend import config

logger = logging.getLogger(__name__)

# pymupdf4llm's classic converter infers <sup>/<sub>/<u> from a span's
# baseline offset relative to its line. Real textbook PDFs almost never have
# genuine superscripts/underlines there; a vertically-stacked fraction
# (numerator / division-bar / denominator, the standard textbook layout for
# division and fraction problems) gets misread as one instead — confirmed
# against a real algebra textbook, where this fires throughout the fractions
# and equation-solving chapters (ADR-011). The frontend renders raw HTML in
# Markdown (rehype-raw), so an unstripped tag shows as a visibly broken,
# disconnected underline/superscript rather than inert text. Stripping the
# tags (keeping their inner text) trades that glitch for the same
# numerator-then-denominator ambiguity plain-text extraction already has —
# no worse than before, and it costs nothing on pages that never hit the
# misfire.
_SPURIOUS_TAG_RE = re.compile(r"</?(?:u|sup|sub)>")


@dataclass
class ExtractedPage:
    page_number: int
    text: str
    image_paths: list[str] = field(default_factory=list)


def derive_title_from_pdf(pdf_path: Path, fallback_name: str = "") -> str:
    """Derive a human-readable course title from a PDF.

    Prefers the PDF's embedded metadata title; falls back to a prettified
    filename stem; finally returns 'Untitled Course'. Never raises.
    """
    meta_title = ""
    try:
        doc = fitz.open(str(pdf_path))
        try:
            meta_title = ((doc.metadata or {}).get("title") or "").strip()
        finally:
            doc.close()
    except Exception:
        meta_title = ""
    if meta_title:
        return meta_title
    stem = Path(fallback_name or str(pdf_path)).stem
    pretty = stem.replace("_", " ").replace("-", " ").strip()
    return pretty or "Untitled Course"


def extract_toc(pdf_path: Path) -> list[tuple[int, str, int]]:
    """Return the PDF's embedded table of contents (bookmarks).

    Each entry is ``(level, title, page_index)`` where ``level`` starts at 1 and
    ``page_index`` is 0-based. Returns an empty list if the PDF has no TOC or
    cannot be read. Never raises.
    """
    try:
        doc = fitz.open(str(pdf_path))
        try:
            raw = doc.get_toc(simple=True) or []
        finally:
            doc.close()
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


def _markdown_pages(doc: fitz.Document) -> list[str] | None:
    """Convert every page of *doc* to layout-aware Markdown via pymupdf4llm.

    Returns one Markdown string per page (same count/order as *doc*), or
    ``None`` if pymupdf4llm is unavailable, fails to convert, or returns an
    unexpected chunk count — callers fall back to plain text in that case.
    Never raises.

    Two deliberate deviations from pymupdf4llm's defaults:
    - ``use_layout(False)`` forces its classic heuristic converter (font-size
      headings, paragraph reflow from PyMuPDF's own text blocks) instead of
      its ML/OCR layout engine (the ``pymupdf-layout`` + onnxruntime path,
      which defaults on if that package is importable). The ML engine is
      slower and unnecessary for born-digital textbook PDFs.
    - ``table_strategy=None`` disables grid-table detection. Measured on a
      real 489-page algebra textbook this cut conversion time from 32s to
      ~20s with no loss of real tables (this book has none) — see ADR-011.
    """
    try:
        import pymupdf4llm
    except Exception as exc:
        logger.warning("pymupdf4llm unavailable, falling back to plain text: %s", exc)
        return None

    try:
        pymupdf4llm.use_layout(False)
        chunks = pymupdf4llm.to_markdown(
            doc, page_chunks=True, write_images=False, table_strategy=None,
        )
    except Exception as exc:
        logger.warning("pymupdf4llm conversion failed, falling back to plain text: %s", exc)
        return None

    if len(chunks) != len(doc):
        logger.warning(
            "pymupdf4llm returned %d chunks for %d pages, falling back to plain text",
            len(chunks), len(doc),
        )
        return None

    return [_SPURIOUS_TAG_RE.sub("", chunk.get("text", "")) for chunk in chunks]


def extract_pdf(pdf_path: Path, assets_dir: Path) -> list[ExtractedPage]:
    """Extract text and embedded images from every page of a PDF.

    Page text is layout-aware Markdown via pymupdf4llm when enabled (default;
    see ``config.pdf_markdown_extraction()``) and available, else PyMuPDF's
    plain-text extraction — see ``_markdown_pages`` for the fallback rules.
    Image extraction is always PyMuPDF's own (pymupdf4llm's image handling is
    disabled via ``write_images=False`` to avoid a second, conflicting image
    pipeline; this module's Asset extraction is unchanged either way).

    Args:
        pdf_path: Path to the source PDF file.
        assets_dir: Directory where extracted images are saved (created if absent).

    Returns:
        One ExtractedPage per page, in page order.
    """
    assets_dir = Path(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    pages: list[ExtractedPage] = []

    try:
        md_pages = _markdown_pages(doc) if config.pdf_markdown_extraction() else None

        for i, page in enumerate(doc):
            text = md_pages[i] if md_pages is not None else page.get_text("text")

            image_paths: list[str] = []
            for img_tuple in page.get_images(full=True):
                xref = img_tuple[0]
                pix = fitz.Pixmap(doc, xref)

                # Convert CMYK or pixmaps with alpha to plain RGB
                if pix.n - pix.alpha >= 4 or pix.alpha:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                out_path = assets_dir / f"page{i}_img{xref}.png"
                pix.save(str(out_path))
                image_paths.append(str(out_path))

            pages.append(ExtractedPage(
                page_number=i,
                text=text,
                image_paths=image_paths,
            ))
    finally:
        doc.close()

    return pages
