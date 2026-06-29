"""Tests for deriving a course title from a PDF when none is supplied."""
from __future__ import annotations

import fitz

from SourceMind.backend.extract.pdf import derive_title_from_pdf


def _make_pdf(path, *, meta_title=None, text="Hello"):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    if meta_title is not None:
        doc.set_metadata({"title": meta_title})
    doc.save(str(path))
    doc.close()


def test_derive_prefers_metadata_title(tmp_path):
    pdf = tmp_path / "whatever.pdf"
    _make_pdf(pdf, meta_title="Beginning Algebra")
    assert derive_title_from_pdf(pdf, "whatever.pdf") == "Beginning Algebra"


def test_derive_falls_back_to_prettified_filename(tmp_path):
    pdf = tmp_path / "intro_to-calculus.pdf"
    _make_pdf(pdf, meta_title=None)  # no metadata title
    # underscores/hyphens become spaces
    assert derive_title_from_pdf(pdf, "intro_to-calculus.pdf") == "intro to calculus"


def test_derive_handles_blank_metadata_title(tmp_path):
    pdf = tmp_path / "my_book.pdf"
    _make_pdf(pdf, meta_title="   ")  # whitespace-only -> ignored
    assert derive_title_from_pdf(pdf, "my_book.pdf") == "my book"


def test_derive_never_raises_on_bad_path(tmp_path):
    missing = tmp_path / "nope.pdf"
    # No file on disk; should fall back to filename stem, not raise.
    assert derive_title_from_pdf(missing, "nope.pdf") == "nope"
