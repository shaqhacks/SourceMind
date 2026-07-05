"""Outline detection — segments a document into titled sections.

ADR-010: ingest is zero-LLM. Bookmark-first (``sections_from_toc``) and the
no-bookmark page-window fallback (``sections_from_page_windows``) are both
deterministic, as is front-matter carving (``detect_front_matter_pages`` /
``carve_front_matter``). ``detect_outline`` is the one LLM-based function
left — no longer called from ingest, kept for its test coverage and as a
possible building block for a future whole-book reprocessing feature.
"""
from __future__ import annotations

import os
import re
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

_RETRY_NOTE = (
    "\n\n=== YOUR PREVIOUS RESPONSE WAS EMPTY OR UNUSABLE ===\n"
    "Your previous response did not parse into any usable section entries. "
    "Return ONLY a JSON object matching the schema, with a non-empty "
    "'sections' array — no prose, no markdown code fences."
)

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


_MIN_TOC_CHAPTERS = 4
_MAX_TOC_CHAPTERS = 80


def _pick_toc_level(entries: list[tuple[int, str, int]]) -> int:
    """Pick the bookmark level that yields a sane chapter count.

    Bookmarks often nest (Part > Chapter > Section); using the shallowest level
    unconditionally can pick a "Part" level with only 2-3 entries when a much
    more useful "Chapter" level sits one level deeper. Prefers the DEEPEST level
    whose entry count falls in ``[_MIN_TOC_CHAPTERS, _MAX_TOC_CHAPTERS]`` (finer
    granularity wins among qualifying levels); levels below/between chosen-level
    entries are not turned into their own sections — they are effectively
    merged into their enclosing chapter's page range. Falls back to the
    shallowest level when no level's count falls in range (best-effort: still
    LLM-free, just possibly too coarse or too fine).
    """
    levels = sorted({lvl for lvl, _, _ in entries})
    counts = {lvl: sum(1 for l, _, _ in entries if l == lvl) for lvl in levels}
    qualifying = [lvl for lvl in levels if _MIN_TOC_CHAPTERS <= counts[lvl] <= _MAX_TOC_CHAPTERS]
    if qualifying:
        return max(qualifying)
    return levels[0]


def sections_from_toc(
    toc_entries: list[tuple[int, str, int]],
    total_pages: int,
) -> list[Section]:
    """Build sections from a PDF's embedded table of contents (bookmarks).

    Picks the bookmark level yielding a sane chapter count (see
    ``_pick_toc_level``) as the "chapter" level. Each chapter spans from its own
    page up to the page before the next chapter (the last one runs to the end
    of the document). Returns ``[]`` if there is no usable TOC, so callers can
    fall back to a deterministic outline (see ``sections_from_page_windows``).

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

    chapter_level = _pick_toc_level(entries)
    chapters = sorted(
        ((lvl, t, pg) for (lvl, t, pg) in entries if lvl == chapter_level),
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


def sections_from_page_windows(total_pages: int, pages_per_chapter: int) -> list[Section]:
    """Deterministic no-bookmark outline: fixed page-range windows (ADR-010).

    Used at ingest when ``sections_from_toc`` finds no usable embedded TOC —
    keeps ingest entirely LLM-free (see ``config.fallback_pages_per_chapter``
    for the default window size). Titles are explicit placeholders
    ("Pages A-B", 1-based for readability) so callers can tell them apart from
    real chapter titles and lazily refine them on first read (see
    ``Chapter.title_status`` / ``pipeline.service.maybe_refine_title``).

    Args:
        total_pages:      Total number of pages in the document.
        pages_per_chapter: Window size; clamped to at least 1.
    """
    if total_pages <= 0:
        return []
    pages_per_chapter = max(1, pages_per_chapter)

    sections: list[Section] = []
    start = 0
    while start < total_pages:
        end = min(start + pages_per_chapter - 1, total_pages - 1)
        sections.append(Section(
            section_id=f"pages{start}",
            title=f"Pages {start + 1}–{end + 1}",
            page_start=start,
            page_end=end,
        ))
        start = end + 1
    return sections


# ─── Front matter (ADR-010 addendum): never fold title/copyright/dedication/
# printed-TOC pages into "Chapter 1", whether the outline came from bookmarks
# or the page-window fallback. Detection is a cheap, deterministic regex/
# keyword heuristic — no LLM — scoped to the LEADING run of pages only, so it
# can never reach into the middle of the real book. ───────────────────────────

_FRONT_MATTER_KEYWORDS = (
    "table of contents", "copyright", "all rights reserved", "isbn",
    "creative commons", "cc-by", "thanks to", "acknowledg", "dedicat",
    "preface", "foreword",
)
# A printed table-of-contents line: some title text, then a dot-leader or run
# of spaces, then a trailing page number ("1.1 Integers .............. 7").
_TOC_LINE_RE = re.compile(r"^.{3,}[.\s]{4,}\d{1,4}\s*$")
_MAX_FRONT_MATTER_PAGES = 30


def _looks_like_front_matter(text: str) -> bool:
    """A page "looks like" front matter if it names itself as boilerplate
    (copyright/ISBN/Creative Commons/dedication/"Table of Contents") or at
    least half its non-blank lines are printed-TOC dot-leader lines.

    Deliberately does NOT use a low-word-count/"sparse page" signal: real
    textbook pages are routinely short too (an image-heavy chapter-opening
    page, a worked-example page that's mostly a diagram), and a false
    positive there would swallow real chapter content into "Front Matter" —
    a worse failure than under-detecting an unusual, keyword-free bare title
    page. A false negative here just means the (harmless, already-readable)
    title page stays part of "chapter 1" as before this function existed.
    """
    lowered = (text or "").lower()
    if any(kw in lowered for kw in _FRONT_MATTER_KEYWORDS):
        return True
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return False
    toc_lines = sum(1 for ln in lines if _TOC_LINE_RE.match(ln.strip()))
    return toc_lines >= max(2, len(lines) // 2)


def detect_front_matter_pages(pages: list[ExtractedPage]) -> int:
    """Return how many LEADING pages (in document order) look like front matter.

    Stops at the first page that doesn't match (a contiguous run from the
    start of the document only — this can never misfire on content deep in
    the book), capped at ``_MAX_FRONT_MATTER_PAGES`` as a safety valve.
    Returns 0 when the very first page already looks like real content.
    """
    count = 0
    for page in pages[:_MAX_FRONT_MATTER_PAGES]:
        if not _looks_like_front_matter(page.text):
            break
        count += 1
    return count


def carve_front_matter(sections: list[Section], front_matter_pages: int) -> list[Section]:
    """Materialize a leading "Front Matter" section covering pages
    ``[0, front_matter_pages - 1]``, never folding those pages into "chapter 1".

    Callers pass the boundary appropriate to their outline source: for a
    bookmark-derived outline that's simply the first chapter's own
    ``page_start`` (whatever precedes the first real bookmark is by
    definition front matter — no heuristic needed); for the page-window
    fallback (which always starts its first window at page 0, so it has no
    such natural boundary) that's ``detect_front_matter_pages``'s content-based
    estimate.

    Any leading sections wholly contained within the front-matter range are
    dropped (only possible with a page-window size much smaller than the
    front matter itself); a section straddling the boundary is clipped to
    start right after it instead. Page-window placeholder titles ("Pages
    A-B") are regenerated for the clipped range; real bookmark titles are
    left as-is (clipping a page or two off a real chapter's start doesn't
    change what it's called).
    """
    if front_matter_pages <= 0 or not sections:
        return sections

    front = Section(
        section_id="front_matter",
        title="Front Matter",
        page_start=0,
        page_end=front_matter_pages - 1,
    )

    rest = list(sections)
    while rest and rest[0].page_end < front_matter_pages:
        rest.pop(0)  # wholly inside the front matter — drop it

    if rest and rest[0].page_start < front_matter_pages:
        first = rest[0]
        new_start = front_matter_pages
        new_title = first.title
        if new_title.startswith("Pages "):
            new_title = f"Pages {new_start + 1}–{first.page_end + 1}"
        rest[0] = Section(
            section_id=first.section_id,
            title=new_title,
            page_start=new_start,
            page_end=first.page_end,
        )

    return [front, *rest]


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
        sections = _parse_sections(result, len(collected))
        if not sections:
            # Bounded retry: this chunk produced NOTHING usable — one re-call
            # noting the failure before falling back to today's graceful
            # degradation (this chunk simply contributes no sections).
            result = provider.complete(
                prompt + _RETRY_NOTE, system=_SYSTEM_PROMPT, schema=OUTLINE_SCHEMA,
                max_tokens=max_tokens,
            )
            sections = _parse_sections(result, len(collected))
        collected.extend(sections)

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
