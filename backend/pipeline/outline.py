"""Outline detection — segments a document into titled sections via an LLM."""
from __future__ import annotations

import os
from dataclasses import dataclass

from SourceMind.backend.extract.pdf import ExtractedPage
from SourceMind.backend.llm.provider import LLMProvider

_DEFAULT_MAX_SECTIONS = 120

OUTLINE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_id":  {"type": "string"},
                    "title":       {"type": "string"},
                    "page_start":  {"type": "integer"},
                    "page_end":    {"type": "integer"},
                },
                "required": ["section_id", "title", "page_start", "page_end"],
            },
        }
    },
    "required": ["sections"],
}

_SYSTEM_PROMPT = (
    "You are a document analysis assistant. "
    "Given the text of a document split by page, identify the major sections. "
    "Return ONLY a JSON object matching the provided schema — no prose, no markdown fences."
)


@dataclass
class Section:
    section_id: str
    title: str
    page_start: int
    page_end: int


def _build_prompt(pages: list[ExtractedPage]) -> str:
    lines: list[str] = [
        "Below is the document text, organised by page number. "
        "Identify each major section and the page range it spans.\n"
    ]
    for page in pages:
        lines.append(f"--- Page {page.page_number} ---")
        lines.append(page.text or "(no text)")
    return "\n".join(lines)


def _max_sections() -> int:
    try:
        return int(os.environ.get("SOURCEMIND_MAX_OUTLINE_SECTIONS", _DEFAULT_MAX_SECTIONS))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_SECTIONS


def detect_outline(pages: list[ExtractedPage], provider: LLMProvider) -> list[Section]:
    """Detect document outline sections from extracted pages.

    Args:
        pages: Ordered list of ExtractedPage objects (one per PDF page).
        provider: An LLMProvider instance used to call the model.

    Returns:
        A list of Section dataclass instances, capped at SOURCEMIND_MAX_OUTLINE_SECTIONS.
    """
    prompt = _build_prompt(pages)
    result = provider.complete(prompt, system=_SYSTEM_PROMPT, schema=OUTLINE_SCHEMA)

    raw_sections: list[dict] = result.get("sections", [])  # type: ignore[union-attr]

    sections: list[Section] = []
    for index, s in enumerate(raw_sections):
        # A section with no title is useless — skip it rather than crash.
        title = s.get("title")
        if not title:
            continue

        section_id = s.get("section_id") or f"s{index}"

        try:
            page_start = int(s["page_start"])
        except (KeyError, TypeError, ValueError):
            page_start = 0

        try:
            page_end = int(s["page_end"])
        except (KeyError, TypeError, ValueError):
            page_end = page_start

        sections.append(Section(
            section_id=section_id,
            title=title,
            page_start=page_start,
            page_end=page_end,
        ))

    cap = _max_sections()
    return sections[:cap]
