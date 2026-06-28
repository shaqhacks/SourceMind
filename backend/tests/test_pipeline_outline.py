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
    """The prompt sent to the provider must include page text and page numbers."""
    provider = FakeProvider(FIXED_SECTIONS)
    detect_outline(FAKE_PAGES, provider)

    prompt = provider.calls[0]["prompt"]
    assert "Intro text" in prompt
    assert "Methods text" in prompt
    assert "Conclusion text" in prompt


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
