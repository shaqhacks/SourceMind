"""Deterministic outline boundary detection: bookmarks -> heading detection
-> page windows. No LLM calls, ever (ingest prime directive).

ADR-013: front-matter skipping. Title/publisher/copyright pages and
table-of-contents pages are dropped deterministically before sectioning,
via a NARROW set of signals chosen to minimize false positives (preface,
foreword, introduction, and index are deliberately never dropped — real
content risk). See smv2/docs/decisions.md ADR-013 for the full rationale.

ADR-015: heading-detection middle tier. When a document has no usable
bookmarks, a page-window fallback alone can slice mid-chapter (a chapter
boundary landing inside a fixed-size window rather than at its own page).
sections_from_headings detects chapter boundaries from large-font lines
(read from the PDF's raw page dict — see
app/pipeline/extract.py::extract_heading_candidates) before falling all
the way back to page windows. See smv2/docs/decisions.md ADR-015.

ADR-017: section kind + chapter grouping. classify_section_kind and
assign_chapter_labels classify each already-detected section by title text
alone (practice sheet / answer key / ordinary content) and group every
section under the chapter marker it belongs to, so a course's practice
sections and answer keys can be surfaced as one testing/review surface per
chapter. See smv2/docs/decisions.md ADR-017.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MIN_TOC_SECTIONS = 3
_MIN_USABLE_SECTIONS = 2

# --- Bookmark-path denylist (narrow on purpose) -----------------------------
# Matched case-insensitively against the FULL, whitespace-collapsed bookmark
# title. Deliberately excludes preface/foreword/introduction/index: those
# routinely contain real, citable content.
_FRONT_MATTER_TITLE_RES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^(table of )?contents$",
        r"^copyright( page)?$",
        r"^title page$",
        r"^colophon$",
        r"^dedication$",
        r"^acknowledgm?ents?$",
    )
]

# --- Page-window-path leading-page skip -------------------------------------
_FRONT_MATTER_SCAN_LIMIT = 10
_TOC_LINE_MIN_COUNT = 5
_TOC_LINE_FRACTION = 0.4
_NEAR_EMPTY_CHAR_THRESHOLD = 120

_COPYRIGHT_SIGNAL_RE = re.compile(r"all rights reserved|isbn|©\s?\d{4}", re.IGNORECASE)
_TRAILING_PAGE_NUMBER_RE = re.compile(r"\d+\s*$")

# --- Heading-detection tier --------------------------------------------------
_HEADING_BODY_SIZE_MULTIPLIER = 1.25
_HEADING_BOOSTED_SIZE_MULTIPLIER = 1.1
_HEADING_MIN_LEN = 3
_HEADING_MAX_LEN = 80
_MIN_HEADING_SECTIONS = 3
# Base/hard caps for the scaled upper bound — see _max_heading_sections.
_MAX_HEADING_SECTIONS_CAP = 80
_MAX_HEADING_SECTIONS_HARD_CAP = 300
_MIN_HEADING_PAGE_COVERAGE = 0.6

_HEADING_BOOST_RE = re.compile(
    r"^(chapter|section|part|unit|lesson|module)\s+"
    r"([0-9ivxlc]+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_NUMBERED_HEADING_RE = re.compile(r"^\d+(\.\d+)?\s+\S")
_TRAILING_DISQUALIFYING_PUNCT_RE = re.compile(r"[.,:;]$")
# A dot-leader run (2+ dots, as in a ToC-style "....") optionally followed by
# a page number — NOT a bare trailing digit alone, which could legitimately
# be part of a real title ("Chapter 2"). Narrow on purpose, same reasoning
# as the front-matter denylist above.
_TRAILING_DOT_LEADER_RE = re.compile(r"(?:\.\s*){2,}\d*\s*$")

# --- Section kind + chapter grouping (ADR-017) ------------------------------
# Deliberately narrow: bare "problems" used to match, misfiling ordinary
# lesson titles like "Age Problems"/"Word Problems" as practice sheets — a
# lesson misfiled as practice is worse than a worksheet shown as content, so
# "problems" only counts as part of "problem set(s)", never alone.
_PRACTICE_TITLE_RE = re.compile(
    r"\bpractice\b|\bexercises?\b|\bproblem sets?\b|\breview questions\b|\bworksheets?\b", re.IGNORECASE
)
_ANSWERS_TITLE_RE = re.compile(r"^answers?\b|\banswer key\b", re.IGNORECASE)
# Anchored: a section's OWN title IS a chapter marker.
_CHAPTER_MARKER_RE = re.compile(r"^chapter\s+([0-9ivxlc]+)\b", re.IGNORECASE)
# Unanchored: a chapter reference appearing anywhere in a title (e.g. an
# answer key naming the chapter it belongs to, "Answers - Chapter 8").
_CHAPTER_REFERENCE_RE = re.compile(r"chapter\s+([0-9ivxlc]+)\b", re.IGNORECASE)


@dataclass
class SectionBounds:
    title: str
    page_start: int  # 0-based, inclusive
    page_end: int  # 0-based, inclusive


def _is_front_matter_title(title: str) -> bool:
    normalized = " ".join(title.split())
    return any(p.match(normalized) for p in _FRONT_MATTER_TITLE_RES)


def _choose_level(
    entries: list[tuple[int, str, int]],
) -> list[tuple[int, str, int]]:
    """Level-1 entries as the section boundaries, unless level-1 has fewer
    than _MIN_TOC_SECTIONS entries, in which case level-2 is used instead (a
    deliberately simple two-level rule — no fancy level-picking heuristic).
    """
    level1 = sorted((e for e in entries if e[0] == 1), key=lambda e: e[2])
    level2 = sorted((e for e in entries if e[0] == 2), key=lambda e: e[2])
    if len(level1) >= _MIN_TOC_SECTIONS:
        return level1
    if level2:
        return level2
    return level1


def _looks_like_copyright_page(text: str) -> bool:
    return bool(_COPYRIGHT_SIGNAL_RE.search(text))


def _looks_like_toc_page(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    numbered = sum(1 for ln in lines if _TRAILING_PAGE_NUMBER_RE.search(ln))
    return numbered >= _TOC_LINE_MIN_COUNT and (numbered / len(lines)) >= _TOC_LINE_FRACTION


def _looks_near_empty(text: str) -> bool:
    return len(text.strip()) < _NEAR_EMPTY_CHAR_THRESHOLD


def _is_front_matter_page(text: str) -> bool:
    return (
        _looks_like_copyright_page(text)
        or _looks_like_toc_page(text)
        or _looks_near_empty(text)
    )


def first_content_page_index(pages: list[str]) -> int:
    """Index of the first page (0-based) that looks like real content,
    scanning at most the first _FRONT_MATTER_SCAN_LIMIT pages and skipping
    while a page matches any front-matter signal (copyright/ISBN, ToC-shaped
    dotted page-number lines, or near-empty).

    If the scan window never clears (every scanned page still looks like
    front matter), returns 0 rather than blindly consuming the whole scan
    window — a false positive here would silently eat real content, which
    is worse than under-skipping a few genuine front-matter pages.
    """
    limit = min(len(pages), _FRONT_MATTER_SCAN_LIMIT)
    for i in range(limit):
        if not _is_front_matter_page(pages[i]):
            return i
    return 0


def front_matter_bookmark_titles(toc_entries: list[tuple[int, str, int]]) -> list[str]:
    """Titles, among the bookmark level sections_from_toc would use, that
    its denylist would drop. Used only so ingest.py can log what was
    skipped; sections_from_toc applies the same denylist directly rather
    than calling back into this helper.
    """
    entries = [(lvl, title.strip(), pg) for (lvl, title, pg) in toc_entries if title and title.strip()]
    if not entries:
        return []
    chosen = _choose_level(entries)
    return [title for (_lvl, title, _pg) in chosen if _is_front_matter_title(title)]


def _round_size(size: float) -> int:
    return round(size)


def _body_font_size(candidates: list[tuple[int, str, float, bool]]) -> float:
    """Modal font size, weighted by text length: the rounded size bucket
    with the most total (non-whitespace-stripped) characters wins — a
    short large-font heading shouldn't out-vote a whole page of ordinary
    body text just because it's one "line". Falls back to 12pt (an
    arbitrary but harmless default) if there's nothing to measure.
    """
    weights: dict[int, int] = {}
    for _page, text, size, _bold in candidates:
        length = len(text.strip())
        if length == 0:
            continue
        bucket = _round_size(size)
        weights[bucket] = weights.get(bucket, 0) + length
    if not weights:
        return 12.0
    return float(max(weights, key=weights.get))


def _is_mostly_digits(text: str) -> bool:
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return False
    digit_count = sum(1 for c in non_space if c.isdigit())
    return digit_count / len(non_space) > 0.5


def _matches_heading_boost(text: str) -> bool:
    return bool(_HEADING_BOOST_RE.match(text) or _NUMBERED_HEADING_RE.match(text))


def _qualifies_as_heading(stripped: str, size: float, body_size: float) -> bool:
    length = len(stripped)
    if not (_HEADING_MIN_LEN <= length <= _HEADING_MAX_LEN):
        return False
    if _TRAILING_DISQUALIFYING_PUNCT_RE.search(stripped):
        return False
    if _is_mostly_digits(stripped):
        return False
    threshold = (
        _HEADING_BOOSTED_SIZE_MULTIPLIER
        if _matches_heading_boost(stripped)
        else _HEADING_BODY_SIZE_MULTIPLIER
    )
    return size >= threshold * body_size


def _clean_heading_title(text: str) -> str:
    collapsed = " ".join(text.split())
    cleaned = _TRAILING_DOT_LEADER_RE.sub("", collapsed).strip()
    return cleaned or collapsed


def _sections_from_heading_entries(
    entries: list[tuple[int, str]], last_page: int
) -> list[SectionBounds]:
    """entries: (page, title) pairs already sorted ascending by page, all
    from the SAME rounded font-size bucket (one candidate "tier").

    Same-page collision rule: if two headings in this tier land on the
    identical page (two chapters starting on one physical page — page
    granularity can't split any finer), the first one claims that page as
    its start; the second is bumped to start on the very next page instead
    of being dropped, so both still surface as distinct, correctly-ordered
    sections rather than one silently swallowing the other.
    """
    starts: list[tuple[int, str]] = []
    for page, title in entries:
        start = page
        if starts and start <= starts[-1][0]:
            start = starts[-1][0] + 1
        starts.append((min(start, last_page), title))

    sections: list[SectionBounds] = []
    for i, (start, title) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else last_page
        end = max(start, min(end, last_page))
        sections.append(SectionBounds(title=title, page_start=start, page_end=end))
    return sections


def _max_heading_sections(total_pages: int) -> int:
    """Upper section-count bound scales with document length: a long real
    book can legitimately have 100+ lesson-level headings (e.g. a 489-page
    algebra textbook with 177 section heads). A fixed 80-section cap
    rejects exactly that tier outright, in favor of whatever smaller,
    sparser tier happens to qualify instead — never worth it, so the cap
    grows with the document (never past _MAX_HEADING_SECTIONS_HARD_CAP).
    """
    return max(_MAX_HEADING_SECTIONS_CAP, min(_MAX_HEADING_SECTIONS_HARD_CAP, total_pages // 2))


def _heading_tier_qualifies(
    sections: list[SectionBounds], effective_total_pages: int, total_pages: int
) -> bool:
    count = len(sections)
    if not (_MIN_HEADING_SECTIONS <= count <= _max_heading_sections(total_pages)):
        return False
    if effective_total_pages <= 0:
        return False
    covered_pages = sections[-1].page_end - sections[0].page_start + 1
    return (covered_pages / effective_total_pages) >= _MIN_HEADING_PAGE_COVERAGE


def sections_from_headings(
    candidates: list[tuple[int, str, float, bool]],
    total_pages: int,
    *,
    skip_before_page: int = 0,
    skip_front_matter: bool = True,
) -> list[SectionBounds]:
    """Middle tier between bookmarks and page windows (ADR-015): detects
    chapter boundaries from large-font lines when a document has no usable
    bookmarks, instead of falling straight to fixed page windows that can
    slice a chapter boundary mid-window.

    Candidates are (page, line text, font size, is_bold) tuples — see
    app/pipeline/extract.py::extract_heading_candidates for how they're
    read off the PDF. A line qualifies as a heading candidate if its font
    size is >= 1.25x the document's body size (or >= 1.1x when it matches
    a "Chapter N" / numbered-heading shape), its stripped length is 3-80,
    it doesn't end in .,:; (excludes a trap like a pull-quote), and it
    isn't mostly digits (excludes bare page numbers).

    Qualifying lines are grouped into "tiers" by rounded font size (the
    different heading LEVELS a document might use). Among every tier whose
    OWN candidates alone form a plausible outline (3 to _max_heading_sections
    sections spanning >=60% of the document), the one with the MOST
    sections wins — not simply the largest font size. A sparse tier of a
    few oversized one-off lines (a pull-quote-sized "N.N Practice" sheet
    header, say) can trivially "qualify" on coverage alone, because the
    last section always runs to the document's final page by construction
    regardless of how little real structure that tier represents; picking
    by section count instead prefers whichever tier actually captures the
    book's real, granular structure. Once a tier wins, its final section
    boundaries are the UNION of its own candidates and every candidate from
    a STRICTLY LARGER tier (a document's coarser heading level — chapter
    markers over lesson headers, say — still deserves to be a boundary
    even where that coarser level alone is too sparse to pass the
    standalone check on its own). Same-page collisions are resolved across
    this union exactly as within a single tier (first wins, second bumped
    to the next page).

    Returns [] if no tier qualifies, so callers fall back to
    sections_from_page_windows exactly as they would with zero candidates.

    skip_before_page mirrors the page-window fallback's own front-matter
    skip (first_content_page_index) — candidates on skipped leading pages
    never become headings. skip_front_matter also filters detected heading
    TITLES through the same denylist sections_from_toc uses for bookmark
    titles (e.g. a detected "Table of Contents" heading is dropped too).

    No-drop guard: if the winning tier's (unioned) first boundary starts
    after skip_before_page, a leading section is prepended covering
    [skip_before_page, first_boundary_page) rather than silently dropping
    those pages — titled after the longest heading-candidate line (from
    ANY tier) that lands on skip_before_page itself, or "Introduction" if
    none does.
    """
    if not candidates or total_pages <= 0:
        return []

    relevant = [c for c in candidates if c[0] >= skip_before_page]
    if not relevant:
        return []
    effective_total_pages = total_pages - skip_before_page

    body_size = _body_font_size(relevant)

    # Every qualifying (page, size bucket, cleaned title) triple, denylist
    # filtered, in original (page) order — not yet grouped into tiers.
    qualifying: list[tuple[int, int, str]] = []
    for page, text, size, _bold in relevant:
        stripped = text.strip()
        if not _qualifies_as_heading(stripped, size, body_size):
            continue
        title = _clean_heading_title(stripped)
        if skip_front_matter and _is_front_matter_title(title):
            continue
        qualifying.append((page, _round_size(size), title))

    if not qualifying:
        return []

    by_bucket: dict[int, list[tuple[int, str]]] = {}
    for page, bucket, title in qualifying:
        by_bucket.setdefault(bucket, []).append((page, title))

    last_page = max(total_pages - 1, 0)

    winning_bucket: int | None = None
    winning_sections: list[SectionBounds] = []
    for bucket, entries in by_bucket.items():
        sorted_entries = sorted(entries, key=lambda e: e[0])
        candidate_sections = _sections_from_heading_entries(sorted_entries, last_page)
        if not _heading_tier_qualifies(candidate_sections, effective_total_pages, total_pages):
            continue
        is_better = winning_bucket is None or len(candidate_sections) > len(winning_sections) or (
            len(candidate_sections) == len(winning_sections) and bucket > winning_bucket
        )
        if is_better:
            winning_bucket, winning_sections = bucket, candidate_sections

    if winning_bucket is None:
        return []

    union_entries: list[tuple[int, str]] = list(by_bucket[winning_bucket])
    for bucket, entries in by_bucket.items():
        if bucket > winning_bucket:
            union_entries.extend(entries)
    union_entries.sort(key=lambda e: e[0])

    sections = _sections_from_heading_entries(union_entries, last_page)

    if sections and sections[0].page_start > skip_before_page:
        same_page_titles = [title for page, _bucket, title in qualifying if page == skip_before_page]
        leading_title = max(same_page_titles, key=len) if same_page_titles else "Introduction"
        leading = SectionBounds(
            title=leading_title, page_start=skip_before_page, page_end=sections[0].page_start - 1
        )
        sections = [leading, *sections]

    return sections


def sections_from_toc(
    toc_entries: list[tuple[int, str, int]],
    total_pages: int,
    *,
    skip_front_matter: bool = True,
) -> list[SectionBounds]:
    """Bookmark-first: see _choose_level for the level-1-vs-level-2 rule.
    Returns [] if there are no usable bookmarks at all, so callers fall back
    to sections_from_page_windows.

    Content before the first (surviving) bookmark's target page is never
    covered by any section — this falls out of the loop below for free
    (bounds start at chosen[0]'s own page), which is what drops leading
    title/publisher pages that have no bookmark of their own. When
    skip_front_matter is on, entries whose title matches the front-matter
    denylist are additionally dropped before bounds are built, so e.g. a
    "Table of Contents" bookmark's own page range disappears too.
    """
    entries = [(lvl, title.strip(), pg) for (lvl, title, pg) in toc_entries if title and title.strip()]
    if not entries:
        return []

    chosen = _choose_level(entries)
    if skip_front_matter:
        chosen = [e for e in chosen if not _is_front_matter_title(e[1])]
    if not chosen:
        return []

    last_page = max(total_pages - 1, 0)
    sections: list[SectionBounds] = []
    for i, (_lvl, title, page) in enumerate(chosen):
        start = max(0, min(page, last_page))
        if i + 1 < len(chosen):
            end = max(start, min(chosen[i + 1][2] - 1, last_page))
        else:
            end = last_page
        sections.append(SectionBounds(title=title, page_start=start, page_end=end))
    return sections


def sections_from_page_windows(total_pages: int, pages_per_window: int) -> list[SectionBounds]:
    """No-bookmark fallback: fixed page-range windows with 1-based-readable
    placeholder titles.
    """
    if total_pages <= 0:
        return []
    pages_per_window = max(1, pages_per_window)

    sections: list[SectionBounds] = []
    start = 0
    while start < total_pages:
        end = min(start + pages_per_window - 1, total_pages - 1)
        sections.append(
            SectionBounds(title=f"Pages {start + 1}–{end + 1}", page_start=start, page_end=end)
        )
        start = end + 1
    return sections


def detect_sections(
    toc_entries: list[tuple[int, str, int]],
    total_pages: int,
    pages_per_window: int,
    *,
    pages: list[str] | None = None,
    heading_candidates: list[tuple[int, str, float, bool]] | None = None,
    skip_front_matter: bool = True,
) -> list[SectionBounds]:
    """Three tiers, in order: bookmarks -> heading detection -> page windows
    (ADR-015). Each tier falls through to the next only when it can't
    produce a usable outline — bookmarks need >= _MIN_USABLE_SECTIONS
    entries, heading detection needs a font-size tier that passes
    sections_from_headings' plausibility check; page windows are the last
    resort and always succeed.

    `pages` (markdown text per page) and `heading_candidates` (raw
    page-dict line data — see extract.py::extract_heading_candidates) are
    both optional. Omitting `pages` disables the front-matter leading-page
    skip everywhere (window fallback AND heading detection); omitting
    `heading_candidates` skips straight from bookmarks to page windows,
    exactly as before this tier existed.
    """
    toc_sections = sections_from_toc(toc_entries, total_pages, skip_front_matter=skip_front_matter)
    if len(toc_sections) >= _MIN_USABLE_SECTIONS:
        return toc_sections

    skip = first_content_page_index(pages) if (skip_front_matter and pages) else 0

    if heading_candidates:
        heading_sections = sections_from_headings(
            heading_candidates,
            total_pages,
            skip_before_page=skip,
            skip_front_matter=skip_front_matter,
        )
        if heading_sections:
            return heading_sections

    if skip == 0:
        return sections_from_page_windows(total_pages, pages_per_window)

    windows = sections_from_page_windows(total_pages - skip, pages_per_window)
    shifted: list[SectionBounds] = []
    for w in windows:
        abs_start = w.page_start + skip
        abs_end = w.page_end + skip
        shifted.append(
            SectionBounds(title=f"Pages {abs_start + 1}–{abs_end + 1}", page_start=abs_start, page_end=abs_end)
        )
    return shifted


def classify_section_kind(title: str) -> str:
    """'practice' if the title names a practice sheet (practice/exercise(s)/
    problem set(s)/review questions/worksheet(s)), 'answers' if it names an
    answer key (starts with "answer(s)" or contains "answer key"), else
    'content'. Deterministic, title-only — no LLM, no body text inspection.
    """
    if _PRACTICE_TITLE_RE.search(title):
        return "practice"
    if _ANSWERS_TITLE_RE.search(title):
        return "answers"
    return "content"


def assign_chapter_labels(titles: list[str]) -> list[str | None]:
    """titles: section titles in course order (order_index). Returns one
    chapter_label per title, same order — the exact title text of the
    chapter-marker section (one matching ^chapter N) each section belongs
    under, grouping a book's practice sheets and answer keys with the
    chapter they belong to.

    Primary rule: a section's label is the nearest PRECEDING section whose
    own title is itself a chapter marker — a marker section's label is its
    own title (it's the first member of its own group), not looked up
    further back. Sections before the very first chapter marker in the
    whole title list backfill to that first marker's title, so front
    matter/preamble content joins the chapter it introduces rather than
    being left ungrouped. If the title list has no chapter marker at all,
    every label is None (grouped client-side as "Front matter").

    Answer-key override: when a section's OWN title embeds a chapter
    reference anywhere (e.g. "Answers - Chapter 8"), that reference wins
    over the position-based label — answer keys typically cluster at a
    book's end and would otherwise all inherit the LAST chapter's label
    regardless of which chapter they actually answer. Falls back to a
    synthesized "Chapter N" if no marker section with that exact number
    exists.
    """
    labels: list[str | None] = [None] * len(titles)
    marker_title_by_id: dict[str, str] = {}
    current_label: str | None = None
    first_marker_label: str | None = None

    for i, title in enumerate(titles):
        marker_match = _CHAPTER_MARKER_RE.match(title)
        if marker_match is not None:
            current_label = title
            marker_id = marker_match.group(1).lower()
            marker_title_by_id.setdefault(marker_id, title)
            if first_marker_label is None:
                first_marker_label = title
        labels[i] = current_label

    if first_marker_label is not None:
        labels = [label if label is not None else first_marker_label for label in labels]

    for i, title in enumerate(titles):
        ref_match = _CHAPTER_REFERENCE_RE.search(title)
        if ref_match is None:
            continue
        ref_id = ref_match.group(1).lower()
        labels[i] = marker_title_by_id.get(ref_id, f"Chapter {ref_match.group(1)}")

    return labels
