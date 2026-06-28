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
