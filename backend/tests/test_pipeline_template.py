"""Tests for backend.pipeline.template — chapter template prompt + body parsers."""
from __future__ import annotations

import pytest

from SourceMind.backend.pipeline.template import (
    PATH_TO_STAFF_TEMPLATE,
    count_worked_examples,
    count_words,
    parse_cards,
    parse_quiz,
)

# ---------------------------------------------------------------------------
# Sample chapter markdown
# ---------------------------------------------------------------------------

SAMPLE_CHAPTER = """\
> *Why does this matter? Because understanding binary search unlocks O(log n) thinking.*

## Objectives

By the end you can:
- Implement binary search iteratively and recursively
- Identify when binary search applies
- Analyse the time complexity in each case

## Intuition

Binary search works by repeatedly halving the search space. You compare the target
to the middle element and discard the half that cannot contain the answer.

### Worked Example 1: Iterative Binary Search

Given a sorted list `[1, 3, 5, 7, 9]` and target `7`, walk through each step.

Step 1: lo=0, hi=4, mid=2, arr[2]=5 < 7 → search right half.
Step 2: lo=3, hi=4, mid=3, arr[3]=7 == target → return 3.

Why: each step discards half the elements, giving O(log n) iterations.

### Worked Example 2: Recursive Binary Search

```python
def binary_search(arr, target, lo=0, hi=None):
    if hi is None:
        hi = len(arr) - 1
    if lo > hi:
        return -1
    mid = (lo + hi) // 2
    if arr[mid] == target:
        return mid
    elif arr[mid] < target:
        return binary_search(arr, target, lo=mid+1, hi=hi)
    else:
        return binary_search(arr, target, lo=lo, hi=mid-1)
```

The recursive call mirrors the invariant: target lives in [lo, hi].

> ✏️ Try it: What is the maximum number of comparisons for a list of 1024 elements?
<details><summary>Answer</summary>log2(1024) = 10 comparisons.</details>

## Common Pitfalls

- Off-by-one: use `lo <= hi`, not `lo < hi`.
- Forgetting to update `lo` or `hi` causes infinite loops.

## 📝 Section Check

```quiz
[
  {"q": "What is the time complexity of binary search?", "options": ["O(n)", "O(log n)", "O(n log n)", "O(1)"], "answer": 1, "explain": "Each step halves the search space, yielding O(log n)."},
  {"q": "Binary search requires the input array to be:", "options": ["Unsorted", "Sorted", "Reversed", "Non-empty"], "answer": 1, "explain": "Binary search only works on sorted arrays."},
  {"q": "Which update is correct for the left half?", "options": ["hi = mid", "lo = mid", "hi = mid - 1", "lo = mid + 1"], "answer": 3, "explain": "We already checked mid, so the new lower bound is mid+1."},
  {"q": "What does binary search return when the target is absent?", "options": ["0", "-1", "None", "Raises exception"], "answer": 1, "explain": "Convention: return -1 to signal not found."}
]
```

## Spaced-Repetition Cards

- **Q:** What invariant does binary search maintain? **A:** The target, if present, lies within [lo, hi].
- **Q:** Why is the mid formula `(lo + hi) // 2` sometimes replaced with `lo + (hi - lo) // 2`? **A:** To avoid integer overflow in languages with fixed-width integers.
- **Q:** What is the space complexity of recursive binary search? **A:** O(log n) due to call-stack depth.
"""

MALFORMED_QUIZ_MD = """\
## 📝 Section Check

```quiz
this is not valid json at all {{{
```
"""

# ---------------------------------------------------------------------------
# parse_quiz
# ---------------------------------------------------------------------------


def test_parse_quiz_returns_four_items():
    items = parse_quiz(SAMPLE_CHAPTER)
    assert len(items) == 4


def test_parse_quiz_item_keys():
    items = parse_quiz(SAMPLE_CHAPTER)
    for item in items:
        assert "q" in item
        assert "options" in item
        assert "answer" in item
        assert "explain" in item


def test_parse_quiz_answer_values():
    items = parse_quiz(SAMPLE_CHAPTER)
    assert items[0]["answer"] == 1
    assert items[1]["answer"] == 1
    assert items[2]["answer"] == 3
    assert items[3]["answer"] == 1


def test_parse_quiz_skips_malformed_block():
    """parse_quiz must not raise on a quiz block with invalid JSON."""
    items = parse_quiz(MALFORMED_QUIZ_MD)
    assert items == []


def test_parse_quiz_no_quiz_block():
    items = parse_quiz("# Just prose\n\nNo quiz here.")
    assert items == []


# ---------------------------------------------------------------------------
# parse_cards
# ---------------------------------------------------------------------------


def test_parse_cards_returns_three_items():
    cards = parse_cards(SAMPLE_CHAPTER)
    assert len(cards) == 3


def test_parse_cards_structure():
    cards = parse_cards(SAMPLE_CHAPTER)
    for card in cards:
        assert "q" in card
        assert "a" in card
        assert card["q"]
        assert card["a"]


def test_parse_cards_first_card():
    cards = parse_cards(SAMPLE_CHAPTER)
    assert "invariant" in cards[0]["q"].lower() or "binary" in cards[0]["q"].lower()


def test_parse_cards_no_section():
    cards = parse_cards("# Chapter\n\nNo cards section here.")
    assert cards == []


# ---------------------------------------------------------------------------
# count_worked_examples
# ---------------------------------------------------------------------------


def test_count_worked_examples_two():
    assert count_worked_examples(SAMPLE_CHAPTER) == 2


def test_count_worked_examples_none():
    assert count_worked_examples("# Intro\n\nNo examples.") == 0


def test_count_worked_examples_optional_title():
    md = "### Worked Example\n\nSome content.\n\n### Worked Example: Extended case\n\nMore.\n"
    assert count_worked_examples(md) == 2


# ---------------------------------------------------------------------------
# count_words
# ---------------------------------------------------------------------------


def test_count_words_excludes_code_and_quiz():
    """Word count must exclude fenced code blocks (python) and quiz JSON."""
    prose_only = (
        "> *Why does this matter? Because understanding binary search unlocks O(log n) thinking.*\n\n"
        "Binary search works by repeatedly halving the search space.\n"
    )
    prose_count = count_words(prose_only)
    full_count = count_words(SAMPLE_CHAPTER)
    # Full chapter has fenced blocks; word count should still be reasonable and
    # NOT inflated by JSON quiz content or code lines.
    # The prose-only snippet is much shorter, so full count > prose_count,
    # but the quiz JSON alone has ~100+ words that must be excluded.
    assert full_count > prose_count  # chapter has more prose
    # Sanity: quiz JSON keywords like "explain" should NOT contribute to count
    # (they appear only inside the quiz block).
    # We verify count_words < (count_words with blocks included).
    raw_word_count = len(SAMPLE_CHAPTER.split())
    assert full_count < raw_word_count


def test_count_words_empty():
    assert count_words("") == 0


def test_count_words_only_code():
    md = "```python\ndef foo():\n    return 42\n```\n"
    assert count_words(md) == 0


# ---------------------------------------------------------------------------
# PATH_TO_STAFF_TEMPLATE
# ---------------------------------------------------------------------------


def test_template_is_string():
    assert isinstance(PATH_TO_STAFF_TEMPLATE, str)
    assert len(PATH_TO_STAFF_TEMPLATE) > 500


def test_template_contains_structure_markers():
    """Template must mention the 9-part structure."""
    t = PATH_TO_STAFF_TEMPLATE.lower()
    assert "worked example" in t
    assert "section check" in t or "📝" in PATH_TO_STAFF_TEMPLATE
    assert "spaced-repetition" in t or "spaced repetition" in t


def test_template_has_placeholders():
    """Template must contain the documented placeholder names."""
    assert "{source_text}" in PATH_TO_STAFF_TEMPLATE
    assert "{objectives}" in PATH_TO_STAFF_TEMPLATE
    assert "{target_words}" in PATH_TO_STAFF_TEMPLATE
