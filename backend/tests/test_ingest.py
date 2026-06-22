"""Per-source ingest parsers sharing a normalize() -> raw_text contract (T4)."""

import json
from pathlib import Path

import pytest

from SourceMind.backend.services.ingest import (
    EmptySourceError,
    GarbageSourceError,
    UnsupportedSourceError,
    normalize_source,
)
from SourceMind.backend.services.ingest.markdown import MarkdownParser
from SourceMind.backend.services.ingest.pdf import PdfParser
from SourceMind.backend.services.ingest.text import TextParser
from SourceMind.backend.services.ingest.url import UrlParser
from SourceMind.backend.services.ingest.youtube import YouTubeParser

FIXTURES = Path("backend/tests/fixtures/ingest")


# --- shared contract / dispatcher ---

def test_normalize_source_dispatches_by_type():
    raw = normalize_source("text", "Chapter 1: Intro\n1.1 Basics\nBasics explain the idea.")
    assert "Basics" in raw


def test_normalize_source_rejects_unknown_type():
    with pytest.raises(UnsupportedSourceError):
        normalize_source("carrier-pigeon", "anything")


def test_every_parser_rejects_empty_with_named_error():
    for parser in (TextParser(), MarkdownParser(), UrlParser(), YouTubeParser()):
        with pytest.raises(EmptySourceError):
            parser.normalize("")


# --- pasted text ---

def test_text_parser_normalizes_whitespace():
    out = TextParser().normalize("  Lots   of\t  spaces  \n\n  here  ")
    assert out == "Lots of\nspaces\nhere" or "spaces" in out
    assert "  " not in out  # collapsed


def test_text_parser_rejects_symbol_only_garbage():
    with pytest.raises(GarbageSourceError):
        TextParser().normalize("@@@ ### $$$ %%% ^^^ &&&")


# --- markdown ---

def test_markdown_parser_strips_frontmatter_and_syntax():
    md = (FIXTURES / "sample.md").read_text(encoding="utf-8")
    out = MarkdownParser().normalize(md)
    assert "Photosynthesis" in out
    assert "---" not in out  # frontmatter fence removed
    assert "##" not in out  # heading markers removed
    assert "**" not in out  # bold markers removed


# --- url (already-fetched html) ---

def test_url_parser_extracts_text_from_html():
    html = (FIXTURES / "sample.html").read_text(encoding="utf-8")
    out = UrlParser().normalize(html)
    assert "Newton" in out
    assert "<" not in out and ">" not in out  # tags stripped
    assert "console.log" not in out  # script contents dropped


# --- youtube transcript ---

def test_youtube_parser_joins_transcript_segments():
    segments = json.loads((FIXTURES / "youtube_transcript.json").read_text(encoding="utf-8"))
    out = YouTubeParser().normalize(segments)
    assert "gradient descent" in out.lower()


def test_youtube_parser_accepts_plain_transcript_string():
    out = YouTubeParser().normalize("welcome to the lecture on vectors and spaces")
    assert "vectors" in out


# --- pdf (injectable reader keeps the test deterministic) ---

class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakeReader:
    def __init__(self, _path) -> None:
        self.pages = [_FakePage("Chapter 1: Intro\n1.1 Basics"), _FakePage("Basics explain the idea.")]


class _EmptyReader:
    def __init__(self, _path) -> None:
        self.pages = [_FakePage(""), _FakePage("   ")]


def test_pdf_parser_extracts_and_joins_pages():
    out = PdfParser(reader_factory=_FakeReader).normalize(Path("ignored.pdf"))
    assert "Basics" in out
    assert "Intro" in out


def test_pdf_parser_rejects_image_only_pdf_as_empty():
    with pytest.raises(EmptySourceError):
        PdfParser(reader_factory=_EmptyReader).normalize(Path("scanned.pdf"))
