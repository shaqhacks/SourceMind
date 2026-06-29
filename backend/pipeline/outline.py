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
    "You are a document analysis assistant that builds a fine-grained outline of "
    "a textbook or document. Create ONE separate entry for EVERY chapter, numbered "
    "section, or distinct named topic you can identify. Do NOT merge or group "
    "multiple chapters/sections into one entry, and do NOT summarise the document "
    "into a few broad parts — prefer finer granularity. If the text shows 20 "
    "chapters, return about 20 entries (more if chapters have sub-sections). "
    "Create entries only at the chapter and numbered-section level (for example "
    "'1.1' or '2.3'); do NOT create separate entries for individual objectives, "
    "bullet points, examples, or learning outcomes. Each entry needs a short id, "
    "the chapter/section title exactly as written, and the page range it spans. "
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
        "List EVERY chapter and numbered section as its own entry with the page "
        "range it spans. Do not combine multiple chapters into one entry.\n"
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


_DEFAULT_CHUNK_WORDS = 3000
_DEFAULT_OUTLINE_MAX_TOKENS = 8192


def _chunk_words() -> int:
    try:
        return int(os.environ.get("SOURCEMIND_OUTLINE_CHUNK_WORDS", _DEFAULT_CHUNK_WORDS))
    except (TypeError, ValueError):
        return _DEFAULT_CHUNK_WORDS


def _outline_max_tokens() -> int:
    """Token budget for each outline call. Generous so a chunk's section list
    isn't truncated mid-JSON (the parser salvages truncation too, but more room
    avoids dropping sections)."""
    try:
        return int(os.environ.get("SOURCEMIND_OUTLINE_MAX_TOKENS", _DEFAULT_OUTLINE_MAX_TOKENS))
    except (TypeError, ValueError):
        return _DEFAULT_OUTLINE_MAX_TOKENS


def sections_from_toc(
    toc_entries: list[tuple[int, str, int]],
    total_pages: int,
) -> list[Section]:
    """Build sections from a PDF's embedded table of contents (bookmarks).

    Uses the shallowest TOC level present as the "chapter" level. Each chapter
    spans from its own page up to the page before the next chapter (the last one
    runs to the end of the document). Returns ``[]`` if there is no usable TOC,
    so callers can fall back to LLM-based outline detection.

    Args:
        toc_entries: ``(level, title, page_index)`` tuples, page_index 0-based,
                     already mapped onto the global page numbering.
        total_pages: Total number of pages in the document.
    """
    entries = [
        (lvl, title.strip(), pg)
        for (lvl, title, pg) in toc_entries
        if title and title.strip()
    ]
    if not entries:
        return []

    top_level = min(lvl for lvl, _, _ in entries)
    chapters = sorted(
        ((lvl, t, pg) for (lvl, t, pg) in entries if lvl == top_level),
        key=lambda e: e[2],
    )

    last_page = max(total_pages - 1, 0)
    sections: list[Section] = []
    for i, (_lvl, title, page) in enumerate(chapters):
        start = max(0, min(page, last_page))
        if i + 1 < len(chapters):
            end = max(start, chapters[i + 1][2] - 1)
        else:
            end = last_page
        end = min(end, last_page)
        sections.append(Section(
            section_id=f"toc{i}",
            title=title,
            page_start=start,
            page_end=end,
        ))
    return sections


def _chunk_pages(pages: list[ExtractedPage], word_budget: int) -> list[list[ExtractedPage]]:
    """Group consecutive pages into batches that each stay under a word budget.

    A single oversized page becomes its own batch. This keeps each outline call
    within the model's context window so a long book is fully covered instead of
    silently truncated to the first context window's worth of pages.
    """
    chunks: list[list[ExtractedPage]] = []
    current: list[ExtractedPage] = []
    current_words = 0
    for page in pages:
        words = len((page.text or "").split())
        if current and current_words + words > word_budget:
            chunks.append(current)
            current, current_words = [], 0
        current.append(page)
        current_words += words
    if current:
        chunks.append(current)
    return chunks


def _parse_sections(result, start_index: int) -> list[Section]:
    raw_sections = result.get("sections", []) if isinstance(result, dict) else []
    sections: list[Section] = []
    for offset, s in enumerate(raw_sections):
        if not isinstance(s, dict):
            continue
        # A section with no title is useless — skip it rather than crash.
        title = s.get("title")
        if not title:
            continue
        section_id = s.get("section_id") or f"s{start_index + offset}"
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
    return sections


def detect_outline(pages: list[ExtractedPage], provider: LLMProvider) -> list[Section]:
    """Detect document outline sections from extracted pages.

    The pages are processed in word-budgeted chunks (one LLM call per chunk) so
    that long documents are covered in full rather than truncated to the model's
    context window. Results are merged in page order, de-duplicated, and assigned
    stable sequential ids. Capped at SOURCEMIND_MAX_OUTLINE_SECTIONS.
    """
    chunks = _chunk_pages(pages, _chunk_words()) or [pages]

    collected: list[Section] = []
    max_tokens = _outline_max_tokens()
    for chunk in chunks:
        prompt = _build_prompt(chunk)
        result = provider.complete(
            prompt, system=_SYSTEM_PROMPT, schema=OUTLINE_SCHEMA, max_tokens=max_tokens
        )
        collected.extend(_parse_sections(result, len(collected)))

    # Order by page, drop near-duplicate boundary repeats (same title + start page).
    collected.sort(key=lambda s: (s.page_start, s.page_end))
    deduped: list[Section] = []
    seen: set[tuple[str, int]] = set()
    for s in collected:
        key = (s.title.strip().lower(), s.page_start)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)

    # Guarantee unique ids: keep the model's id when unique (chunks can collide),
    # suffixing duplicates rather than reassigning everything.
    used: set[str] = set()
    for s in deduped:
        sid = s.section_id
        if sid in used:
            n = 2
            while f"{sid}_{n}" in used:
                n += 1
            sid = f"{sid}_{n}"
        s.section_id = sid
        used.add(sid)

    cap = _max_sections()
    return deduped[:cap]
