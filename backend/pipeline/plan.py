"""Plan generation — assigns learning objectives and source-proportional word targets."""
from __future__ import annotations

from dataclasses import dataclass, field

from SourceMind.backend.extract.pdf import ExtractedPage
from SourceMind.backend.llm.provider import LLMProvider
from SourceMind.backend.pipeline.outline import Section

_EXPANSION: dict[str, float] = {
    "core": 1.6,
    "supporting": 1.2,
    "peripheral": 0.8,
}

_CLAMP_MIN = 400
_CLAMP_MAX = 3000

PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_id":    {"type": "string"},
                    "objectives":    {"type": "array", "items": {"type": "string"}},
                    "importance":    {"type": "string", "enum": ["core", "supporting", "peripheral"]},
                    "prerequisites": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["section_id"],
            },
        }
    },
    "required": ["items"],
}

_SYSTEM_PROMPT = (
    "You are a curriculum design assistant. "
    "Given a list of document sections, return a JSON object with key 'items' — "
    "an array where each element provides: section_id, objectives (list of learning outcomes), "
    "importance (one of: core, supporting, peripheral), and prerequisites (list of section_ids). "
    "Return ONLY a JSON object matching the provided schema — no prose, no markdown fences."
)


@dataclass
class PlanItem:
    section_id: str
    title: str
    objectives: list[str] = field(default_factory=list)
    importance: str = "supporting"
    prerequisites: list[str] = field(default_factory=list)
    target_words: int = 0


def compute_target_words(source_words: int, importance: str) -> int:
    """Return the target word count for a section, clamped to [400, 3000].

    Args:
        source_words: Number of words in the source text for the section.
        importance:   One of "core", "supporting", "peripheral"; unknown values
                      default to the "supporting" expansion factor (1.2).

    Returns:
        Integer target word count clamped to [400, 3000].
    """
    expansion = _EXPANSION.get(importance, _EXPANSION["supporting"])
    result = source_words * expansion
    return int(max(_CLAMP_MIN, min(_CLAMP_MAX, result)))


def _source_words_for_section(section: Section, pages: list[ExtractedPage]) -> int:
    """Sum word counts for all pages that fall within section.page_start..page_end."""
    total = 0
    for page in pages:
        if section.page_start <= page.page_number <= section.page_end:
            total += len(page.text.split())
    return total


def _build_prompt(sections: list[Section]) -> str:
    lines: list[str] = [
        "Below is the list of document sections. "
        "For each section, provide learning objectives, importance level, "
        "and any prerequisite section IDs.\n"
    ]
    for s in sections:
        lines.append(f"- section_id: {s.section_id!r}, title: {s.title!r}")
    return "\n".join(lines)


def generate_plan(
    sections: list[Section],
    pages: list[ExtractedPage],
    provider: LLMProvider,
) -> list[PlanItem]:
    """Generate a learning plan for each section, with source-proportional word targets.

    Makes a single LLM call to retrieve objectives, importance, and prerequisites for
    all sections at once. Maps the response back by section_id (tolerates missing keys).

    Args:
        sections: Ordered list of document sections.
        pages:    All extracted pages (used to count source words per section).
        provider: LLM backend conforming to LLMProvider Protocol.

    Returns:
        One PlanItem per input section, in input order.
    """
    prompt = _build_prompt(sections)
    response = provider.complete(prompt, system=_SYSTEM_PROMPT, schema=PLAN_SCHEMA)

    # Build lookup by section_id from provider response
    raw_items: list[dict] = []
    if isinstance(response, dict):
        raw_items = response.get("items", [])
    metadata: dict[str, dict] = {}
    for item in raw_items:
        sid = item.get("section_id")
        if sid:
            metadata[sid] = item

    plan: list[PlanItem] = []
    for section in sections:
        meta = metadata.get(section.section_id, {})
        importance = meta.get("importance", "supporting") or "supporting"
        objectives = meta.get("objectives") or []
        prerequisites = meta.get("prerequisites") or []

        source_words = _source_words_for_section(section, pages)
        target_words = compute_target_words(source_words, importance)

        plan.append(PlanItem(
            section_id=section.section_id,
            title=section.title,
            objectives=list(objectives),
            importance=importance,
            prerequisites=list(prerequisites),
            target_words=target_words,
        ))

    return plan
