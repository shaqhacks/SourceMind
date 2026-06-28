"""Chapter template prompt and body parsers for the SourceMind pipeline.

Exports
-------
PATH_TO_STAFF_TEMPLATE : str
    System/instruction prompt that tells an LLM how to write one chapter in
    the *Path to Staff* style.  Contains these format placeholders (filled by
    Task 8 via str.format):
        {objectives}    – bullet list of learning objectives for the section
        {importance}    – short string describing why the section matters
        {target_words}  – target word count (int) for the chapter prose
        {source_text}   – the raw extracted text of the section
        {image_urls}    – newline-separated list of image URLs (may be empty)

parse_quiz(body_md)         -> list[dict]
parse_cards(body_md)        -> list[dict]
count_words(body_md)        -> int
count_worked_examples(body_md) -> int
"""

from __future__ import annotations

import json
import re

# ---------------------------------------------------------------------------
# Instruction template
# ---------------------------------------------------------------------------

PATH_TO_STAFF_TEMPLATE: str = """\
You are an expert educator writing a chapter of a self-study textbook modelled
on *The Path to Staff*. Your job is to TEACH the reader the material in the
provided source text — not to quiz them on it, not to ask them to restate it,
and not to summarise it at arm's length. Expand it into a richly explained,
flowing, pedagogically complete chapter.

=== INPUTS ===

**Section objectives** (incorporate all of them):
{objectives}

**Why this section matters** (use as context for tone and emphasis):
{importance}

**Target word count** for prose (aim within ±15 %):
{target_words}

**Source text** (this is your primary content; expand, explain, and teach it):
{source_text}

**Available image URLs** (embed each at the point where the figure is relevant,
using standard Markdown: `![descriptive caption](url)`):
{image_urls}

=== OUTPUT FORMAT ===

Write the chapter as valid Markdown, following EXACTLY this 9-part structure
in order.  Do not omit any required part; do not add extra top-level sections.

---

**Part 1 — Hook**
One or two sentence epigraph (Markdown blockquote) explaining *why this topic
matters* or *where it shows up in the real world*.  Format:
> *Your compelling opening sentence here.*

---

**Part 2 — Objectives**
A short "By the end you can…" paragraph followed by 3–5 bullet points drawn
directly from the provided {objectives}.

---

**Part 3 — Narrative Teaching**
Several `##`-level sections (two or more) that build the reader's understanding
from intuition → mechanics → application.  Guidelines:
- Write flowing prose paragraphs, NOT fragmented bullet lists.
- GROUND every claim in the source text; expand and explain it rather than
  merely referencing it.
- Place images inline where the figure is conceptually relevant.
- Use Markdown tables where a comparison or structured view aids clarity.
- Length must be proportional to the source; prose word count should approach
  {target_words}.

---

**Part 4 — Worked Examples**
Include 2–3 worked examples, each under its own `### Worked Example` heading
(you may append a number and/or title, e.g. `### Worked Example 1: Iterative
Approach`).  For each example:
- State the problem clearly.
- Work it out step-by-step, annotating *why* each step is taken.
- DOMAIN-ADAPTIVE:
  - Programming topics → include a runnable code snippet in a fenced block.
  - Mathematics → show every algebraic / arithmetic step with explanation.
  - Other domains → use structured reasoning with labelled steps.

---

**Part 5 — Try It**
Interleave 1–3 short exercises throughout the chapter (not necessarily at the
end).  Each uses this format exactly:
> ✏️ Try it: <question text>
<details><summary>Answer</summary><answer text></details>

Place each prompt at the pedagogically natural moment — after introducing a
concept the reader can now practise.

---

**Part 6 — Common Pitfalls**
A concise `## Common Pitfalls` section (bullet list, 3–5 items) grounded in
mistakes learners actually make with this material.  Do not invent pitfalls;
derive them from the source or from standard teaching knowledge about the topic.

---

**Part 7 — 📝 Section Check**
A `## 📝 Section Check` heading followed by ONE fenced code block whose info
string is exactly `quiz` (three backticks, then `quiz`, no spaces):

```quiz
[
  {{
    "q": "Question text",
    "options": ["Option A", "Option B", "Option C", "Option D"],
    "answer": 0,
    "explain": "Why this answer is correct."
  }},
  ...
]
```

Include 4–6 items.  The `answer` field is the 0-based index into `options`.
Every item must have all four keys: `q`, `options`, `answer`, `explain`.
Questions must test conceptual understanding, not trivia or surface wording.

---

**Part 8 — Spaced-Repetition Cards**
A `## Spaced-Repetition Cards` heading followed by one bullet per card:
- **Q:** <question> **A:** <answer>

Include cards ONLY for important, core concepts.  For minor or introductory
sections you may include few or none.  Each card should be atomic — one idea
per card.

---

**Part 9 — Going Deeper** *(optional)*
If the source material naturally leads to follow-on reading or harder
extensions, add a `## Going Deeper` section with 2–4 references or pointers.
Omit this section entirely if there is nothing meaningful to add.

---

=== QUALITY RULES ===

1. Write as a thoughtful senior engineer or professor — authoritative, clear,
   and kind.  Assume the reader is intelligent but new to this specific topic.
2. Prose must be flowing and connected.  Avoid bullet-heavy sections for
   explanatory content; reserve bullets for lists that are genuinely list-like
   (pitfalls, objectives, card items).
3. Stay faithful to the source text's meaning.  Do not contradict it; do not
   invent facts not implied by it.
4. The quiz JSON must be valid JSON.  Escape any special characters inside
   strings.  Remember to use `{{` and `}}` for literal braces in JSON examples
   you might write in explanations outside the quiz block.
5. Do NOT include any preamble like "Sure, here is the chapter" — output only
   the Markdown chapter, starting with the Part 1 hook blockquote.
"""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_FENCED_BLOCK_RE = re.compile(
    r"^```[^\n]*\n.*?^```",
    re.MULTILINE | re.DOTALL,
)


def _strip_fenced_blocks(md: str) -> str:
    """Remove all fenced code blocks (``` ... ```) from *md*."""
    return _FENCED_BLOCK_RE.sub("", md)


# ---------------------------------------------------------------------------
# Public parsers
# ---------------------------------------------------------------------------


def parse_quiz(body_md: str) -> list[dict]:
    """Return all quiz items from ```quiz fenced blocks in *body_md*.

    Finds every fenced block whose info string is exactly ``quiz``.
    Attempts ``json.loads`` on the block body; skips the block silently on
    ``JSONDecodeError``.  If the parsed value is a list, its items are
    appended; if a dict, the dict itself is appended.
    """
    result: list[dict] = []
    pattern = re.compile(
        r"^```quiz\s*\n(.*?)^```",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(body_md):
        raw = match.group(1).strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            result.extend(parsed)
        elif isinstance(parsed, dict):
            result.append(parsed)
    return result


def parse_cards(body_md: str) -> list[dict]:
    """Return spaced-repetition cards from the ``## Spaced-Repetition Cards``
    section of *body_md*.

    Each bullet of the form ``- **Q:** question **A:** answer`` (with
    optional surrounding whitespace) is parsed into ``{"q": ..., "a": ...}``.
    Returns ``[]`` if the section is absent.
    """
    # Locate the section
    section_pattern = re.compile(
        r"^##\s+Spaced-Repetition Cards\s*\n(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    section_match = section_pattern.search(body_md)
    if not section_match:
        return []

    section_body = section_match.group(1)

    card_pattern = re.compile(
        r"-\s+\*\*Q:\*\*\s*(.*?)\s+\*\*A:\*\*\s*(.*?)(?=\n-\s+\*\*Q:|$)",
        re.DOTALL,
    )
    cards: list[dict] = []
    for m in card_pattern.finditer(section_body):
        q = m.group(1).strip()
        a = m.group(2).strip()
        if q or a:
            cards.append({"q": q, "a": a})
    return cards


def count_words(body_md: str) -> int:
    """Count words in *body_md*, excluding all fenced code blocks.

    All ``` ... ``` regions (including ```quiz and ```python blocks) are
    stripped before splitting on whitespace.
    """
    stripped = _strip_fenced_blocks(body_md)
    return len(stripped.split())


def count_worked_examples(body_md: str) -> int:
    """Count ``### Worked Example`` headings in *body_md*.

    Matches lines of the form ``### Worked Example`` optionally followed by
    additional text (e.g. a number or title).
    """
    pattern = re.compile(r"^###\s+Worked Example", re.MULTILINE)
    return len(pattern.findall(body_md))
