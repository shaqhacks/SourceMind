"""Source-grounded chapter generation for the SourceMind pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field

from SourceMind.backend.llm.provider import LLMProvider
from SourceMind.backend.pipeline.plan import PlanItem
from SourceMind.backend.pipeline.template import (
    PATH_TO_STAFF_TEMPLATE,
    count_words_total,
    parse_cards,
    parse_quiz,
)
from SourceMind.backend.services.ingest.security import sanitize_source

_MAX_TOKENS_CEILING = 8192
_TOKENS_PER_WORD = 3

_QUIZ_RETRY_NOTE = """\


=== YOUR PREVIOUS RESPONSE WAS MISSING THE QUIZ ===
Your previous response did not include a valid ```quiz fenced JSON block (or
it could not be parsed). Return the COMPLETE chapter again, following ALL of
the instructions above exactly, and this time include the required
`## 📝 Section Check` section with a ```quiz fenced block containing 4-6
well-formed items.
"""


@dataclass
class ChapterDraft:
    section_id: str
    title: str
    body_md: str
    quiz: list[dict] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    word_count: int = 0


def generate_chapter(
    plan_item: PlanItem,
    source_text: str,
    image_urls: list[str],
    provider: LLMProvider,
) -> ChapterDraft:
    """Generate a chapter draft grounded in *source_text* for *plan_item*.

    Builds the chapter prompt from PATH_TO_STAFF_TEMPLATE, calls the provider
    for freeform markdown (no schema), then parses quiz items, spaced-repetition
    cards, and word count from the returned body.

    Args:
        plan_item:   Metadata about the section to write (objectives, importance, etc.).
        source_text: Raw extracted text from the source document for this section.
        image_urls:  URLs of figures available for inline embedding; may be empty.
        provider:    LLM backend conforming to LLMProvider Protocol.

    Returns:
        ChapterDraft with body_md, quiz, cards, and word_count populated.
    """
    # Defense-in-depth: strip prompt-injection imperatives from the untrusted
    # source document before it is interpolated into the generation prompt.
    clean_source_text, _ = sanitize_source(source_text)

    prompt = PATH_TO_STAFF_TEMPLATE.format(
        objectives="\n".join(f"- {o}" for o in plan_item.objectives),
        importance=plan_item.importance,
        target_words=plan_item.target_words,
        source_text=clean_source_text,
        image_urls="\n".join(image_urls) if image_urls else "(none)",
    )

    max_tokens = min(plan_item.target_words * _TOKENS_PER_WORD, _MAX_TOKENS_CEILING)
    max_tokens = max(max_tokens, 4096)  # always at least 4096

    body = provider.complete(prompt, max_tokens=max_tokens)
    if not isinstance(body, str):
        raise TypeError(
            f"provider.complete must return str without a schema, got {type(body).__name__}"
        )

    quiz = parse_quiz(body)
    if not quiz:
        # Bounded retry: the model's markdown omitted (or malformed) the
        # required ```quiz fenced block entirely. One re-call noting the
        # failure, before falling back to today's graceful degradation (an
        # empty quiz — validate()'s repair loop is the backstop if this
        # retry also comes up empty).
        retry_body = provider.complete(prompt + _QUIZ_RETRY_NOTE, max_tokens=max_tokens)
        if isinstance(retry_body, str) and parse_quiz(retry_body):
            body = retry_body

    return ChapterDraft(
        section_id=plan_item.section_id,
        title=plan_item.title,
        body_md=body,
        quiz=parse_quiz(body),
        cards=parse_cards(body),
        word_count=count_words_total(body),
    )
