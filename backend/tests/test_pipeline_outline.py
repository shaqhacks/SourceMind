"""Tests for backend.pipeline.outline — outline detection via LLM."""
from __future__ import annotations

import os

import pytest

from SourceMind.backend.extract.pdf import ExtractedPage
from SourceMind.backend.pipeline.outline import Section, detect_outline


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------

class FakeProvider:
    """Minimal LLMProvider stub: returns a fixed outline dict."""

    def __init__(self, sections_payload: list[dict]) -> None:
        self._payload = sections_payload
        self.calls: list[dict] = []

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> dict:
        self.calls.append({"prompt": prompt, "system": system, "schema": schema})
        return {"sections": self._payload}


FIXED_SECTIONS = [
    {"section_id": "s1", "title": "Introduction", "page_start": 0, "page_end": 0},
    {"section_id": "s2", "title": "Methods",      "page_start": 1, "page_end": 1},
    {"section_id": "s3", "title": "Conclusion",   "page_start": 2, "page_end": 2},
]

FAKE_PAGES = [
    ExtractedPage(page_number=0, text="Intro text"),
    ExtractedPage(page_number=1, text="Methods text"),
    ExtractedPage(page_number=2, text="Conclusion text"),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_detect_outline_returns_sections():
    """detect_outline parses the provider response into Section dataclass instances."""
    provider = FakeProvider(FIXED_SECTIONS)
    sections = detect_outline(FAKE_PAGES, provider)

    assert len(sections) == 3

    assert sections[0] == Section(section_id="s1", title="Introduction", page_start=0, page_end=0)
    assert sections[1] == Section(section_id="s2", title="Methods",      page_start=1, page_end=1)
    assert sections[2] == Section(section_id="s3", title="Conclusion",   page_start=2, page_end=2)


def test_detect_outline_passes_schema_to_provider():
    """detect_outline must call provider.complete with a JSON schema argument."""
    provider = FakeProvider(FIXED_SECTIONS)
    detect_outline(FAKE_PAGES, provider)

    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["schema"] is not None, "schema must be passed to provider.complete"
    # Schema must be an object (tool-input constraint — no top-level arrays)
    assert call["schema"].get("type") == "object"


def test_detect_outline_prompt_contains_page_text():
    """The prompt sent to the provider must include page text and page-number markers."""
    provider = FakeProvider(FIXED_SECTIONS)
    detect_outline(FAKE_PAGES, provider)

    prompt = provider.calls[0]["prompt"]
    assert "Intro text" in prompt
    assert "Methods text" in prompt
    assert "Conclusion text" in prompt
    # Page-number markers must be present so stripping them is caught early.
    assert "--- Page 0 ---" in prompt
    assert "--- Page 1 ---" in prompt
    assert "--- Page 2 ---" in prompt


def test_detect_outline_section_cap_truncates(monkeypatch):
    """When SOURCEMIND_MAX_OUTLINE_SECTIONS is set, excess sections are dropped."""
    many_sections = [
        {"section_id": f"s{i}", "title": f"Section {i}", "page_start": i, "page_end": i}
        for i in range(10)
    ]
    provider = FakeProvider(many_sections)
    monkeypatch.setenv("SOURCEMIND_MAX_OUTLINE_SECTIONS", "5")

    sections = detect_outline(FAKE_PAGES, provider)

    assert len(sections) == 5
    assert sections[0].section_id == "s0"
    assert sections[4].section_id == "s4"


def test_detect_outline_default_cap_allows_120():
    """Default cap is 120; 3 sections is well under that and should not be truncated."""
    monkeypatch_env = os.environ.pop("SOURCEMIND_MAX_OUTLINE_SECTIONS", None)
    try:
        provider = FakeProvider(FIXED_SECTIONS)
        sections = detect_outline(FAKE_PAGES, provider)
        assert len(sections) == 3
    finally:
        if monkeypatch_env is not None:
            os.environ["SOURCEMIND_MAX_OUTLINE_SECTIONS"] = monkeypatch_env


def test_section_is_dataclass():
    """Section must be a dataclass with the required fields."""
    import dataclasses
    assert dataclasses.is_dataclass(Section)
    fields = {f.name for f in dataclasses.fields(Section)}
    assert fields == {"section_id", "title", "page_start", "page_end"}


def test_detect_outline_skips_malformed_sections():
    """Malformed section dicts are handled gracefully: no crash, title-less entries dropped,
    entries missing page_end are kept with a defaulted int page_end."""
    malformed_sections = [
        # Valid entry — kept as-is.
        {"section_id": "s1", "title": "Introduction", "page_start": 0, "page_end": 2},
        # Missing page_end — kept; page_end defaults to page_start.
        {"section_id": "s2", "title": "Methods", "page_start": 3},
        # Missing title — must be skipped entirely.
        {"section_id": "s3", "page_start": 5, "page_end": 6},
    ]
    provider = FakeProvider(malformed_sections)

    # Must not raise.
    sections = detect_outline(FAKE_PAGES, provider)

    # Title-less entry is skipped → only 2 sections returned.
    assert len(sections) == 2

    # Valid entry is unchanged.
    assert sections[0] == Section(section_id="s1", title="Introduction", page_start=0, page_end=2)

    # Missing page_end entry is kept; page_end defaults to page_start (3).
    assert sections[1].title == "Methods"
    assert isinstance(sections[1].page_end, int)
    assert sections[1].page_end == sections[1].page_start


def test_detect_outline_chunks_cover_whole_document(monkeypatch):
    """Long documents are processed in word-budgeted chunks so EVERY page is
    covered — the bug where only the first context window's chapters appeared."""
    import re
    monkeypatch.setenv("SOURCEMIND_OUTLINE_CHUNK_WORDS", "3")  # tiny budget -> 1 page/chunk

    class ChunkAwareProvider:
        def __init__(self):
            self.calls = []

        def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
            self.calls.append(prompt)
            m = re.search(r"--- Page (\d+) ---", prompt)
            pg = int(m.group(1)) if m else 0
            return {"sections": [
                {"section_id": f"c{pg}", "title": f"Chapter {pg}",
                 "page_start": pg, "page_end": pg}
            ]}

    pages = [ExtractedPage(page_number=i, text=f"word{i} body here") for i in range(8)]
    provider = ChunkAwareProvider()
    sections = detect_outline(pages, provider)

    assert len(provider.calls) == 8, "expected one outline call per page-chunk"
    titles = {s.title for s in sections}
    assert "Chapter 0" in titles
    assert "Chapter 7" in titles  # last pages are NOT dropped
    assert len(sections) == 8
    assert len({s.section_id for s in sections}) == 8  # ids unique
