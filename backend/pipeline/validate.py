"""Validation and repair loop for generated chapter drafts.

Exports
-------
Issue
    Dataclass representing a single quality failure: ``code`` (machine-readable
    string) and ``detail`` (human-readable explanation).
Report
    Dataclass returned by ``validate``: ``ok`` bool and ``issues`` list.
GROUNDING_SCHEMA
    JSON schema for the grounding-judge LLM call (``grounded``, ``unsupported``).
validate(draft, plan_item, source_text, provider, *, had_figures) -> Report
    Runs all six quality checks and returns a Report.
generate_validated(plan_item, source_text, image_urls, provider, *, ...) -> ChapterDraft
    Generates a chapter then repairs it until it passes or max_rounds exhausted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from SourceMind.backend.llm.provider import LLMProvider
from SourceMind.backend.pipeline.chapter import ChapterDraft, generate_chapter
from SourceMind.backend.pipeline.plan import PlanItem
from SourceMind.backend.pipeline.template import (
    count_words,
    count_worked_examples,
    parse_cards,
    parse_quiz,
)

# ---------------------------------------------------------------------------
# JSON schema for the grounding-judge response
# ---------------------------------------------------------------------------

GROUNDING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "grounded": {"type": "boolean"},
        "unsupported": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["grounded", "unsupported"],
}

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)")

_GROUNDING_PROMPT_TEMPLATE = """\
You are a grounding judge for an educational chapter. Your task is to determine
whether the chapter faithfully teaches the provided source material without
introducing unsupported or contradicted claims.

=== SOURCE TEXT ===
{source_text}

=== CHAPTER BODY ===
{chapter_body}

=== INSTRUCTIONS ===
Review each factual claim in the chapter body and determine:
1. Is the chapter grounded in the source text — i.e., does it avoid making
   claims not supported by or directly contradicted by the source?
2. List any specific claims in the chapter that are NOT supported by or are
   contradicted by the source text.

Respond with a JSON object with exactly these two keys:
- "grounded": true if the chapter faithfully teaches the source material
  (set to false if there are unsupported or contradicted claims).
- "unsupported": an array of strings, each describing one unsupported or
  contradicted claim (empty array when grounded is true).
"""

_REPAIR_PROMPT_TEMPLATE = """\
The following chapter draft has quality issues that must be fixed.
Fix ONLY the listed issues while preserving everything else intact.
Return the COMPLETE corrected chapter as valid Markdown, maintaining
all formatting conventions (quiz block, spaced-repetition cards,
worked examples, section headings, etc.).

=== ISSUES TO FIX ===
{issues_text}

=== CURRENT CHAPTER BODY ===
{body_md}
"""

_REPAIR_MAX_TOKENS = 8192


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    """A single quality failure detected by ``validate``."""

    code: str
    detail: str


@dataclass
class Report:
    """Aggregate result returned by ``validate``."""

    ok: bool
    issues: list[Issue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_grounding_prompt(source_text: str, chapter_body: str) -> str:
    return _GROUNDING_PROMPT_TEMPLATE.format(
        source_text=source_text,
        chapter_body=chapter_body,
    )


def _build_repair_prompt(draft: ChapterDraft, report: Report) -> str:
    issues_text = "\n".join(
        f"- [{issue.code}] {issue.detail}" for issue in report.issues
    )
    return _REPAIR_PROMPT_TEMPLATE.format(
        issues_text=issues_text,
        body_md=draft.body_md,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate(
    draft: ChapterDraft,
    plan_item: PlanItem,
    source_text: str,
    provider: LLMProvider,
    *,
    had_figures: bool,
) -> Report:
    """Run all quality checks on *draft*, collecting an Issue for each failure.

    Checks (issue code in parentheses):

    1. ``word_count``      — draft.word_count within ±25 % of plan_item.target_words.
                             Skipped when target_words <= 0.
    2. ``worked_examples`` — count_worked_examples(body_md) >= 2.
    3. ``quiz``            — len(quiz) >= 1 AND every item has a non-empty ``explain``.
    4. ``cards``           — if importance == "core", len(cards) >= 1.
    5. ``image``           — if had_figures, body_md must contain ≥1 ``![...](...)``.
    6. ``grounding``       — LLM judge call; fails when returned dict has grounded=False.

    Args:
        draft:       Chapter draft to validate.
        plan_item:   Metadata for the section (target_words, importance, …).
        source_text: Raw source text used to generate the chapter (for grounding).
        provider:    LLM backend (used for the grounding judge call).
        had_figures: Whether figures were available in the source document.

    Returns:
        Report with ok=True only when zero issues were found.
    """
    issues: list[Issue] = []

    # 1. Word count band (±25 % of target)
    target = plan_item.target_words
    if target > 0:
        lo = 0.75 * target
        hi = 1.25 * target
        wc = draft.word_count
        if not (lo <= wc <= hi):
            issues.append(Issue(
                code="word_count",
                detail=(
                    f"word_count {wc} is outside ±25% band "
                    f"[{lo:.0f}, {hi:.0f}] for target {target}"
                ),
            ))

    # 2. Worked examples
    n_examples = count_worked_examples(draft.body_md)
    if n_examples < 2:
        issues.append(Issue(
            code="worked_examples",
            detail=f"found {n_examples} worked example(s); need at least 2",
        ))

    # 3. Quiz completeness
    quiz = draft.quiz
    if len(quiz) < 1:
        issues.append(Issue(code="quiz", detail="quiz has no items"))
    else:
        missing = [i for i, item in enumerate(quiz) if not item.get("explain")]
        if missing:
            issues.append(Issue(
                code="quiz",
                detail=f"quiz items at indices {missing} are missing non-empty 'explain'",
            ))

    # 4. Spaced-repetition cards (core sections only)
    if plan_item.importance == "core" and len(draft.cards) < 1:
        issues.append(Issue(
            code="cards",
            detail="core section must have at least 1 spaced-repetition card",
        ))

    # 5. Inline image (when source had figures)
    if had_figures and not _IMAGE_RE.search(draft.body_md):
        issues.append(Issue(
            code="image",
            detail="had_figures=True but body contains no markdown image ![...](...)",
        ))

    # 6. Grounding judge (LLM call with structured schema)
    g_prompt = _build_grounding_prompt(source_text, draft.body_md)
    g_result = provider.complete(g_prompt, schema=GROUNDING_SCHEMA)
    if isinstance(g_result, dict) and not g_result.get("grounded", True):
        unsupported = g_result.get("unsupported", [])
        issues.append(Issue(
            code="grounding",
            detail=f"chapter contains unsupported claims: {unsupported}",
        ))

    return Report(ok=len(issues) == 0, issues=issues)


def generate_validated(
    plan_item: PlanItem,
    source_text: str,
    image_urls: list[str],
    provider: LLMProvider,
    *,
    had_figures: bool = False,
    max_rounds: int = 2,
) -> ChapterDraft:
    """Generate a chapter and iteratively repair it until validation passes.

    Round 1 is the initial generate_chapter call.  Each subsequent round sends
    a targeted repair prompt listing the current issues and re-parses the
    returned markdown into a fresh ChapterDraft.  Stops as soon as the draft
    is ok or max_rounds total rounds have been used.

    The final draft is always returned, even when it still has issues after
    max_rounds — the caller is responsible for logging / escalating.

    Args:
        plan_item:   Section metadata.
        source_text: Raw source text for the section.
        image_urls:  Figure URLs available for inline embedding.
        provider:    LLM backend (generation, repair, and grounding calls).
        had_figures: Whether figures were present in the source.
        max_rounds:  Maximum total rounds (1 initial + max_rounds-1 repairs).

    Returns:
        The final ChapterDraft after generation and any repair rounds.
    """
    draft = generate_chapter(plan_item, source_text, image_urls, provider)
    report = validate(draft, plan_item, source_text, provider, had_figures=had_figures)

    repairs_remaining = max_rounds - 1
    while not report.ok and repairs_remaining > 0:
        repairs_remaining -= 1

        repair_prompt = _build_repair_prompt(draft, report)
        repaired_body = provider.complete(repair_prompt, max_tokens=_REPAIR_MAX_TOKENS)
        assert isinstance(repaired_body, str), (
            "Repair provider call must return str (called without schema)"
        )

        draft = ChapterDraft(
            section_id=plan_item.section_id,
            title=plan_item.title,
            body_md=repaired_body,
            quiz=parse_quiz(repaired_body),
            cards=parse_cards(repaired_body),
            word_count=count_words(repaired_body),
        )
        report = validate(draft, plan_item, source_text, provider, had_figures=had_figures)

    return draft
