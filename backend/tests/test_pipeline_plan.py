"""Tests for backend.pipeline.plan — plan generation with source-proportional targets."""
from __future__ import annotations

import pytest

from SourceMind.backend.extract.pdf import ExtractedPage
from SourceMind.backend.pipeline.outline import Section
from SourceMind.backend.pipeline.plan import (
    PlanItem,
    compute_target_words,
    default_plan,
    generate_plan,
)


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class FakeProvider:
    """Minimal LLMProvider stub: returns fixed per-section plan metadata."""

    def __init__(self, items_payload: list[dict]) -> None:
        self._payload = items_payload

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> str | dict:
        return {"items": self._payload}


# ---------------------------------------------------------------------------
# compute_target_words — pure unit tests
# ---------------------------------------------------------------------------


def test_core_expansion():
    assert compute_target_words(1000, "core") == 1600


def test_peripheral_expansion():
    assert compute_target_words(1000, "peripheral") == 800


def test_supporting_expansion():
    assert compute_target_words(1000, "supporting") == 1200


def test_unknown_importance_defaults_to_supporting():
    assert compute_target_words(1000, "mystery") == 1200


def test_clamp_low():
    # 100 * 0.8 = 80 → clamped to 400
    assert compute_target_words(100, "peripheral") == 400


def test_clamp_high():
    # 5000 * 1.6 = 8000 → clamped to 3000
    assert compute_target_words(5000, "core") == 3000


def test_returns_int():
    result = compute_target_words(1000, "core")
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# generate_plan — integration with stub provider
# ---------------------------------------------------------------------------


def _make_pages(page_number: int, word_count: int) -> ExtractedPage:
    """Create a page with exactly `word_count` words."""
    return ExtractedPage(
        page_number=page_number,
        text=" ".join(["word"] * word_count),
        image_paths=[],
    )


def test_generate_plan_returns_one_item_per_section():
    sections = [
        Section(section_id="s1", title="Introduction", page_start=1, page_end=2),
        Section(section_id="s2", title="Core Concepts", page_start=3, page_end=4),
    ]
    pages = [
        _make_pages(1, 200),
        _make_pages(2, 300),
        _make_pages(3, 400),
        _make_pages(4, 500),
    ]
    provider = FakeProvider([
        {
            "section_id": "s1",
            "objectives": ["Understand basics"],
            "importance": "supporting",
            "prerequisites": [],
        },
        {
            "section_id": "s2",
            "objectives": ["Master core ideas", "Apply concepts"],
            "importance": "core",
            "prerequisites": ["s1"],
        },
    ])

    result = generate_plan(sections, pages, provider)

    assert len(result) == 2
    assert all(isinstance(item, PlanItem) for item in result)


def test_generate_plan_maps_objectives_and_importance():
    sections = [
        Section(section_id="s1", title="Intro", page_start=1, page_end=1),
    ]
    pages = [_make_pages(1, 500)]
    provider = FakeProvider([
        {
            "section_id": "s1",
            "objectives": ["Goal A", "Goal B"],
            "importance": "core",
            "prerequisites": ["prereq1"],
        },
    ])

    result = generate_plan(sections, pages, provider)

    assert result[0].section_id == "s1"
    assert result[0].title == "Intro"
    assert result[0].objectives == ["Goal A", "Goal B"]
    assert result[0].importance == "core"
    assert result[0].prerequisites == ["prereq1"]


def test_generate_plan_computes_target_words_from_source():
    sections = [
        Section(section_id="s1", title="Intro", page_start=1, page_end=1),
    ]
    # Exactly 500 words on page 1
    pages = [_make_pages(1, 500)]
    provider = FakeProvider([
        {
            "section_id": "s1",
            "objectives": ["Learn"],
            "importance": "core",
            "prerequisites": [],
        },
    ])

    result = generate_plan(sections, pages, provider)

    # 500 * 1.6 = 800, within [400, 3000]
    assert result[0].target_words == compute_target_words(500, "core")
    assert result[0].target_words == 800


def test_generate_plan_preserves_input_order():
    sections = [
        Section(section_id="s3", title="Third", page_start=5, page_end=5),
        Section(section_id="s1", title="First", page_start=1, page_end=1),
        Section(section_id="s2", title="Second", page_start=3, page_end=3),
    ]
    pages = [
        _make_pages(1, 100),
        _make_pages(3, 200),
        _make_pages(5, 300),
    ]
    provider = FakeProvider([
        {"section_id": "s3", "objectives": [], "importance": "peripheral", "prerequisites": []},
        {"section_id": "s1", "objectives": [], "importance": "supporting", "prerequisites": []},
        {"section_id": "s2", "objectives": [], "importance": "core", "prerequisites": []},
    ])

    result = generate_plan(sections, pages, provider)

    assert [item.section_id for item in result] == ["s3", "s1", "s2"]


def test_generate_plan_defaults_missing_importance_to_supporting():
    sections = [
        Section(section_id="s1", title="Intro", page_start=1, page_end=1),
    ]
    pages = [_make_pages(1, 1000)]
    provider = FakeProvider([
        {
            "section_id": "s1",
            "objectives": ["Learn"],
            # importance intentionally omitted
            "prerequisites": [],
        },
    ])

    result = generate_plan(sections, pages, provider)

    assert result[0].importance == "supporting"
    assert result[0].target_words == compute_target_words(1000, "supporting")


def test_generate_plan_defaults_missing_objectives_and_prerequisites():
    sections = [
        Section(section_id="s1", title="Intro", page_start=1, page_end=1),
    ]
    pages = [_make_pages(1, 300)]
    provider = FakeProvider([
        {
            "section_id": "s1",
            # objectives and prerequisites intentionally omitted
            "importance": "peripheral",
        },
    ])

    result = generate_plan(sections, pages, provider)

    assert result[0].objectives == []
    assert result[0].prerequisites == []


def test_planitem_is_dataclass():
    import dataclasses
    assert dataclasses.is_dataclass(PlanItem)
    fields = {f.name for f in dataclasses.fields(PlanItem)}
    assert fields == {"section_id", "title", "objectives", "importance", "prerequisites", "target_words"}


# ---------------------------------------------------------------------------
# Bounded retry (empty parse -> one re-call, then degrade)
# ---------------------------------------------------------------------------


class QueuedProvider:
    """Returns each response from *responses* in order; counts calls."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
        self.calls += 1
        return self._responses[self.calls - 1]


def test_generate_plan_retries_once_on_empty_items():
    """First response has no usable items; the retry's response does."""
    sections = [Section(section_id="s1", title="Intro", page_start=1, page_end=1)]
    pages = [_make_pages(1, 500)]
    provider = QueuedProvider([
        {"items": []},
        {"items": [{"section_id": "s1", "objectives": ["Learn"], "importance": "core", "prerequisites": []}]},
    ])

    result = generate_plan(sections, pages, provider)

    assert provider.calls == 2
    assert result[0].importance == "core"
    assert result[0].objectives == ["Learn"]


def test_generate_plan_bounded_retry_still_degrades_gracefully():
    """Both the initial call and the retry are empty — bounded to exactly one
    retry, then falls back to today's per-section defaults instead of
    retrying indefinitely."""
    sections = [Section(section_id="s1", title="Intro", page_start=1, page_end=1)]
    pages = [_make_pages(1, 500)]
    provider = QueuedProvider([{"items": []}, {"items": []}])

    result = generate_plan(sections, pages, provider)

    assert provider.calls == 2  # bounded — not retried again
    assert result[0].importance == "supporting"  # default
    assert result[0].objectives == []


# ---------------------------------------------------------------------------
# default_plan — zero-LLM ingest-time plan (ADR-010)
# ---------------------------------------------------------------------------


def test_default_plan_makes_no_provider_call():
    """default_plan takes no provider argument at all — it cannot call an LLM."""
    import inspect

    assert "provider" not in inspect.signature(default_plan).parameters


def test_default_plan_uses_deterministic_defaults():
    sections = [
        Section(section_id="s1", title="Intro", page_start=1, page_end=1),
        Section(section_id="s2", title="Advanced", page_start=2, page_end=2),
    ]
    pages = [_make_pages(1, 1000), _make_pages(2, 500)]

    result = default_plan(sections, pages)

    assert [p.section_id for p in result] == ["s1", "s2"]
    for p in result:
        assert p.objectives == []
        assert p.importance == "supporting"
        assert p.prerequisites == []
    # target_words uses the same "supporting" expansion factor as generate_plan's
    # own fallback, computed from each section's real source word count.
    assert result[0].target_words == compute_target_words(1000, "supporting")
    assert result[1].target_words == compute_target_words(500, "supporting")


def test_default_plan_preserves_section_titles_and_order():
    """Page-window placeholder titles ("Pages A-B") pass through unchanged —
    default_plan never rewrites a Section's title."""
    sections = [
        Section(section_id="pages0", title="Pages 1–15", page_start=0, page_end=14),
        Section(section_id="pages15", title="Pages 16–20", page_start=15, page_end=19),
    ]
    pages = [_make_pages(i, 100) for i in range(20)]

    result = default_plan(sections, pages)

    assert [p.title for p in result] == ["Pages 1–15", "Pages 16–20"]


def test_default_plan_empty_sections():
    assert default_plan([], []) == []
