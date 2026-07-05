"""Tests for backend.extract.pdf — Task 4 TDD."""
import os
from pathlib import Path

import fitz  # PyMuPDF
import pytest

from SourceMind.backend.extract.pdf import ExtractedPage, extract_pdf


def _build_sample_pdf(tmp_path: Path) -> Path:
    """Create a minimal 1-page PDF with text and an embedded image."""
    pdf_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "INTEGERS ARE WHOLE NUMBERS")

    # Build a tiny 10x10 RGB pixmap (red square) and embed it
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    pix.set_rect(fitz.IRect(0, 0, 10, 10), (255, 0, 0))
    rect = fitz.Rect(100, 100, 150, 150)
    page.insert_image(rect, pixmap=pix)

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_extract_pdf_returns_one_page_per_page(tmp_path):
    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)
    assert len(results) == 1


def test_extract_pdf_page_number(tmp_path):
    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)
    assert results[0].page_number == 0


def test_extract_pdf_text_contains_inserted_string(tmp_path):
    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)
    assert "INTEGERS" in results[0].text


def test_extract_pdf_image_paths_is_list(tmp_path):
    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)
    assert isinstance(results[0].image_paths, list)


def test_extract_pdf_image_round_trip(tmp_path):
    """At least one image must be saved to disk."""
    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)
    paths = results[0].image_paths
    assert len(paths) >= 1, "Expected at least one extracted image"
    for p in paths:
        assert os.path.exists(p), f"Image file missing: {p}"


def test_extract_pdf_assets_dir_created(tmp_path):
    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets" / "sub"
    extract_pdf(pdf_path, assets_dir)
    assert assets_dir.exists()


def test_extracted_page_is_dataclass(tmp_path):
    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)
    page = results[0]
    assert hasattr(page, "page_number")
    assert hasattr(page, "text")
    assert hasattr(page, "image_paths")
    assert isinstance(page, ExtractedPage)


# ---------------------------------------------------------------------------
# ADR-011: layout-aware Markdown extraction (pymupdf4llm)
# ---------------------------------------------------------------------------

def _build_heading_pdf(tmp_path: Path) -> Path:
    """A 1-page PDF with a large-font heading line and a smaller-font body
    paragraph — enough font-size contrast for pymupdf4llm's heuristic to tell
    them apart."""
    pdf_path = tmp_path / "headings.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Chapter One: Integers", fontsize=24)
    page.insert_text((72, 110), "This is a regular paragraph of body text.", fontsize=11)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_extract_pdf_markdown_renders_heading(tmp_path):
    """A large-font line becomes a markdown heading; body text stays intact."""
    pdf_path = _build_heading_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)
    text = results[0].text
    assert "#" in text, f"Expected a markdown heading marker, got: {text!r}"
    assert "Chapter One: Integers" in text
    assert "This is a regular paragraph of body text." in text


def test_extract_pdf_strips_spurious_sup_underline_tags(tmp_path, monkeypatch):
    """pymupdf4llm's baseline-offset heuristic can misread a vertically-stacked
    fraction (numerator / bar / denominator) as <sup>/<u> spans — confirmed
    against a real algebra textbook (ADR-011). Since the frontend renders raw
    HTML in Markdown (rehype-raw), an unstripped tag would show as visibly
    broken underline/superscript formatting rather than inert text.
    extract_pdf must strip the tags, keeping their inner text."""
    import pymupdf4llm

    def _fake_to_markdown(doc, *, page_chunks, **kwargs):
        return [{"text": "<sup><u>42</u></sup>\n12"} for _ in range(len(doc))]

    monkeypatch.setattr(pymupdf4llm, "to_markdown", _fake_to_markdown)

    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)
    text = results[0].text
    assert "<sup>" not in text and "</sup>" not in text
    assert "<u>" not in text and "</u>" not in text
    assert "42" in text and "12" in text


def test_extract_pdf_markdown_disabled_by_config(tmp_path, monkeypatch):
    """SOURCEMIND_PDF_MARKDOWN=false skips pymupdf4llm entirely — plain text,
    same as before ADR-011."""
    monkeypatch.setenv("SOURCEMIND_PDF_MARKDOWN", "false")
    pdf_path = _build_heading_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)
    text = results[0].text
    assert "#" not in text
    assert "Chapter One: Integers" in text


def test_extract_pdf_falls_back_to_plain_text_on_conversion_failure(tmp_path, monkeypatch):
    """If pymupdf4llm raises during conversion, extract_pdf must fall back to
    plain text rather than propagate the failure — ingest must never fail
    over formatting."""
    import pymupdf4llm

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated pymupdf4llm failure")

    monkeypatch.setattr(pymupdf4llm, "to_markdown", _boom)

    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)  # must not raise
    assert "INTEGERS" in results[0].text
    assert "#" not in results[0].text


def test_extract_pdf_falls_back_when_pymupdf4llm_missing(tmp_path, monkeypatch):
    """If pymupdf4llm can't even be imported, extract_pdf still returns plain
    text rather than raising."""
    import sys

    monkeypatch.setitem(sys.modules, "pymupdf4llm", None)  # forces ImportError on import

    pdf_path = _build_sample_pdf(tmp_path)
    assets_dir = tmp_path / "assets"
    results = extract_pdf(pdf_path, assets_dir)  # must not raise
    assert "INTEGERS" in results[0].text
