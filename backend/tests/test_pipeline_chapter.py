"""Tests for backend/pipeline/chapter.py — source-grounded chapter generation."""
from __future__ import annotations

import pytest

from SourceMind.backend.pipeline.plan import PlanItem
from SourceMind.backend.pipeline.chapter import ChapterDraft, generate_chapter

# ---------------------------------------------------------------------------
# Sample chapter markdown returned by the fake provider
# ---------------------------------------------------------------------------

SAMPLE_CHAPTER_MD = """\
> *Understanding variables is the first step toward writing programs that remember things.*

By the end of this section you can:
- Declare and assign variables in Python
- Distinguish mutable from immutable types
- Trace the value of a variable through simple code

## What Is a Variable?

A variable is a named location in memory that holds a value. When you write
`x = 42` in Python, you are binding the name `x` to the integer object `42`.
This binding can be changed later — `x = "hello"` is perfectly valid.

Variables let programs remember intermediate results, pass data between functions,
and communicate intent through meaningful names.

## Mutable vs Immutable

Some objects in Python can be changed in place (lists, dicts) while others cannot
(integers, strings, tuples). This distinction matters when you share objects
between parts of a program.

> ✏️ Try it: What is the value of `x` after `x = 5; x = x + 1`?
<details><summary>Answer</summary>6 — the original binding is replaced.</details>

### Worked Example 1: Swapping Two Variables

Suppose you want to swap `a` and `b` without a temporary variable.

```python
a, b = 1, 2
a, b = b, a
print(a, b)  # 2 1
```

Python evaluates the right side fully before assigning, so this is safe.

### Worked Example 2: Accumulating a Sum

```python
total = 0
for n in [1, 2, 3, 4]:
    total += n
print(total)  # 10
```

Each iteration updates the binding; the previous value is discarded.

## Common Pitfalls

- Confusing assignment (`=`) with equality comparison (`==`).
- Expecting a copy when sharing a mutable object.
- Using a variable before assigning it — raises `NameError`.

## 📝 Section Check

```quiz
[
  {
    "q": "What does `x = 10` do in Python?",
    "options": ["Declares a constant", "Binds the name x to the integer 10", "Creates a new type", "Calls a function"],
    "answer": 1,
    "explain": "Assignment binds a name to an object; it does not declare a type or constant."
  },
  {
    "q": "Which type is immutable in Python?",
    "options": ["list", "dict", "set", "tuple"],
    "answer": 3,
    "explain": "Tuples cannot be modified after creation; lists, dicts, and sets are mutable."
  },
  {
    "q": "What error occurs if you use a variable before assigning it?",
    "options": ["TypeError", "ValueError", "NameError", "AttributeError"],
    "answer": 2,
    "explain": "Python raises NameError when a name has not been bound in the current scope."
  },
  {
    "q": "After `a, b = b, a`, what happens to the original values?",
    "options": ["Both are lost", "They are swapped", "a becomes None", "b becomes None"],
    "answer": 1,
    "explain": "Python evaluates the right side fully first, then unpacks into the left side."
  }
]
```

## Spaced-Repetition Cards

- **Q:** What is a variable in Python? **A:** A named binding to an object in memory.
- **Q:** What error is raised when using an unassigned name? **A:** NameError.
- **Q:** Name one mutable and one immutable built-in type. **A:** list (mutable), tuple (immutable).
"""

# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------

class FakeProvider:
    """Captures the prompt and returns a fixed markdown chapter."""

    def __init__(self) -> None:
        self.last_prompt: str = ""
        self.last_max_tokens: int = 0

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> str:
        self.last_prompt = prompt
        self.last_max_tokens = max_tokens
        return SAMPLE_CHAPTER_MD


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def plan_item() -> PlanItem:
    return PlanItem(
        section_id="ch01-variables",
        title="Variables and Bindings",
        objectives=["Declare and assign variables", "Distinguish mutable from immutable types"],
        importance="core",
        prerequisites=[],
        target_words=600,
    )


@pytest.fixture()
def provider() -> FakeProvider:
    return FakeProvider()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_chapter_draft_fields(plan_item, provider):
    """ChapterDraft carries section_id and title from PlanItem."""
    draft = generate_chapter(
        plan_item=plan_item,
        source_text="Python variables bind names to objects.",
        image_urls=[],
        provider=provider,
    )
    assert isinstance(draft, ChapterDraft)
    assert draft.section_id == "ch01-variables"
    assert draft.title == "Variables and Bindings"


def test_chapter_draft_body_md(plan_item, provider):
    """body_md is exactly what the provider returned."""
    draft = generate_chapter(
        plan_item=plan_item,
        source_text="Python variables bind names to objects.",
        image_urls=[],
        provider=provider,
    )
    assert draft.body_md == SAMPLE_CHAPTER_MD


def test_chapter_draft_quiz(plan_item, provider):
    """parse_quiz extracts exactly 4 items from the sample chapter."""
    draft = generate_chapter(
        plan_item=plan_item,
        source_text="Python variables bind names to objects.",
        image_urls=[],
        provider=provider,
    )
    assert len(draft.quiz) == 4
    for item in draft.quiz:
        assert "q" in item
        assert "options" in item
        assert "answer" in item
        assert "explain" in item


def test_chapter_draft_cards(plan_item, provider):
    """parse_cards extracts exactly 3 spaced-repetition cards."""
    draft = generate_chapter(
        plan_item=plan_item,
        source_text="Python variables bind names to objects.",
        image_urls=[],
        provider=provider,
    )
    assert len(draft.cards) == 3
    for card in draft.cards:
        assert "q" in card
        assert "a" in card


def test_chapter_draft_word_count(plan_item, provider):
    """word_count is positive."""
    draft = generate_chapter(
        plan_item=plan_item,
        source_text="Python variables bind names to objects.",
        image_urls=[],
        provider=provider,
    )
    assert draft.word_count > 0


def test_prompt_contains_source_text(plan_item, provider):
    """The prompt sent to the provider contains the source_text verbatim."""
    source = "Python variables bind names to objects in memory."
    generate_chapter(
        plan_item=plan_item,
        source_text=source,
        image_urls=[],
        provider=provider,
    )
    assert source in provider.last_prompt


def test_prompt_contains_objectives(plan_item, provider):
    """The prompt sent to the provider contains each objective from the PlanItem."""
    generate_chapter(
        plan_item=plan_item,
        source_text="Some source text.",
        image_urls=[],
        provider=provider,
    )
    for obj in plan_item.objectives:
        assert obj in provider.last_prompt


def test_prompt_contains_image_urls(plan_item, provider):
    """Image URLs are included in the prompt when provided."""
    urls = ["https://example.com/fig1.png", "https://example.com/fig2.png"]
    generate_chapter(
        plan_item=plan_item,
        source_text="Some source text.",
        image_urls=urls,
        provider=provider,
    )
    for url in urls:
        assert url in provider.last_prompt


def test_prompt_no_image_urls_shows_none(plan_item, provider):
    """When image_urls is empty, the prompt contains the '(none)' placeholder."""
    generate_chapter(
        plan_item=plan_item,
        source_text="Some source text.",
        image_urls=[],
        provider=provider,
    )
    assert "(none)" in provider.last_prompt


def test_max_tokens_scales_with_target_words(plan_item, provider):
    """max_tokens passed to provider is proportional to target_words and >= target_words."""
    plan_item.target_words = 600
    generate_chapter(
        plan_item=plan_item,
        source_text="Some source text.",
        image_urls=[],
        provider=provider,
    )
    assert provider.last_max_tokens >= plan_item.target_words


# ---------------------------------------------------------------------------
# Bounded quiz-retry (empty ```quiz block -> one re-call, then degrade)
# ---------------------------------------------------------------------------


class QueuedProvider:
    """Returns each response from *responses* in order; counts calls."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
        self.calls += 1
        return self._responses[self.calls - 1]


NO_QUIZ_MD = """\
> *A minimal chapter with no quiz block at all.*

## Main Section

Some prose here, but there is no ```quiz fenced block anywhere in this body.
"""


def test_generate_chapter_retries_once_when_quiz_missing(plan_item):
    """First response has no quiz block; the retry's response does — the
    retry's body (with its quiz) is used."""
    provider = QueuedProvider([NO_QUIZ_MD, SAMPLE_CHAPTER_MD])

    draft = generate_chapter(
        plan_item=plan_item,
        source_text="Python variables bind names to objects.",
        image_urls=[],
        provider=provider,
    )

    assert provider.calls == 2
    assert len(draft.quiz) == 4  # from SAMPLE_CHAPTER_MD
    assert draft.body_md == SAMPLE_CHAPTER_MD


def test_generate_chapter_keeps_original_body_when_quiz_retry_also_fails(plan_item):
    """Both the initial call and the retry omit the quiz block — bounded to
    exactly one retry, and the ORIGINAL body/empty-quiz is kept (graceful
    degradation), not the retry's (also broken) body."""
    provider = QueuedProvider([NO_QUIZ_MD, NO_QUIZ_MD])

    draft = generate_chapter(
        plan_item=plan_item,
        source_text="Python variables bind names to objects.",
        image_urls=[],
        provider=provider,
    )

    assert provider.calls == 2  # bounded — not retried again
    assert draft.quiz == []
    assert draft.body_md == NO_QUIZ_MD
