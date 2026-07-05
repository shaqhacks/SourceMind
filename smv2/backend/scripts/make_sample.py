#!/usr/bin/env python3
"""Generate the bundled first-run sample course PDF
(backend/assets/sample/welcome.pdf).

This is a real, deterministically-generated "Learning with SourceMind"
mini-book — 3 chapters, real bookmarks — that gets ingested automatically
the first time the app starts with an empty course list (see
app/services/sample_service.py). Its content teaches the app's actual
behavior (zero-LLM ingest, opt-in/cost-transparent generation, spaced
repetition, resume-on-return), not invented features — a reader taking
this at face value should never be misled about what SourceMind does.

Usage:
    python scripts/make_sample.py

Regenerate and re-commit the PDF whenever this script's content changes;
the PDF itself is deterministic (no_new_id, like the test fixtures), so a
regeneration with no content changes produces a byte-identical file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "assets" / "sample" / "welcome.pdf"

_FIXED_DATE = "D:20250101000000Z"
_PAGE_WIDTH, _PAGE_HEIGHT = 612, 792  # US Letter
_MARGIN = 72


def _set_fixed_metadata(doc: fitz.Document) -> None:
    doc.set_metadata(
        {
            "title": "Learning with SourceMind",
            "author": "SourceMind",
            "subject": "",
            "keywords": "",
            "creator": "",
            "producer": "",
            "creationDate": _FIXED_DATE,
            "modDate": _FIXED_DATE,
        }
    )


def _add_page(doc: fitz.Document, heading: str | None, paragraphs: list[str]) -> fitz.Page:
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    y = _MARGIN

    if heading:
        heading_rect = fitz.Rect(_MARGIN, y, _PAGE_WIDTH - _MARGIN, y + 36)
        page.insert_textbox(heading_rect, heading, fontsize=16, fontname="hebo", align=0)
        y += 48

    body_rect = fitz.Rect(_MARGIN, y, _PAGE_WIDTH - _MARGIN, _PAGE_HEIGHT - _MARGIN)
    body_text = "\n\n".join(paragraphs)
    leftover = page.insert_textbox(body_rect, body_text, fontsize=11, fontname="helv", align=0)
    if leftover < 0:
        raise RuntimeError(
            f"page content overflowed its textbox by {-leftover:.0f}pt "
            f"(heading={heading!r}) — split this page's content further"
        )
    return page


CHAPTER_1_PAGES = [
    (
        "Chapter 1: How SourceMind Works",
        [
            "SourceMind turns a PDF into a workbook in three steps: upload, outline, "
            "read. You upload a PDF, and within seconds you have a full table of "
            "contents and every chapter's original text ready to read - no waiting, "
            "no AI calls, no cost. This document you're reading right now was "
            "ingested exactly the same way.",
            "That speed is not an accident. Ingest is deterministic: SourceMind "
            "never asks an AI model to read your document just to figure out its "
            "structure. If your PDF has bookmarks (a table of contents embedded by "
            "whoever made the PDF), SourceMind uses those directly as chapter "
            "boundaries. If it doesn't, SourceMind falls back to even page windows "
            "- a fixed number of pages per chapter - so you always get a usable "
            "outline immediately, even from a raw scan with no bookmarks at all.",
            "Either way, the text you see in each chapter is the real, original "
            "text extracted from your PDF - never rewritten, summarized, or "
            "paraphrased by a model. SourceMind calls this body text immutable: "
            "once ingested, it never changes unless you re-upload or re-ingest the "
            "source. Anything generated later - a lesson, flashcards, a quiz - is "
            "stored separately, so your source material is always there, unedited, "
            "to check against.",
        ],
    ),
    (
        None,
        [
            "If a chapter title looks wrong, or a chapter split lands in an odd "
            "place, you can fix it. The outline supports renaming, reordering, "
            "merging adjacent chapters, and splitting one chapter into two - "
            "directly from the reader, without re-uploading anything.",
            "Why go to this much trouble to avoid using AI for something AI is "
            "arguably good at? Cost and reproducibility. Ingesting a 500-page "
            "textbook this way costs nothing and takes seconds, whether you do it "
            "once or a hundred times. Every dollar SourceMind spends on an AI "
            "model is a deliberate choice you make later - never a side effect of "
            "simply opening a file.",
            "That's it for ingest. The next chapter covers what SourceMind can "
            "generate for you once you decide you want it - lessons, flashcards, "
            "and quizzes - and how it keeps that spending visible and bounded.",
        ],
    ),
]

CHAPTER_2_PAGES = [
    (
        "Chapter 2: Lessons, Flashcards and Quizzes",
        [
            "Everything in this chapter is optional. SourceMind never calls an AI "
            "model on your behalf without you asking for it, chapter by chapter. "
            "Reading the raw source text costs nothing and always works - "
            "generation is there for when you want more: a plain-language lesson, "
            "a set of review flashcards, or a quiz to test yourself.",
            "Before you generate anything, SourceMind can estimate what it will "
            "cost, based on the length of the chapter and the model you've "
            "configured. Once you do generate something, the exact token usage "
            "and estimated cost for that call is recorded and visible - nothing "
            "is hidden after the fact.",
            "If you've set a spend cap for a course, SourceMind checks it "
            "immediately before every generation call and stops issuing new ones "
            "once the cap is reached, rather than letting a batch job run past a "
            "limit you set. A cap is a safety net, not a perfectly exact billing "
            "meter - but it means a runaway 'generate everything' click can't "
            "silently blow past what you were willing to spend.",
        ],
    ),
    (
        None,
        [
            "Flashcards work with spaced repetition: after you generate a set for "
            "a chapter, you review them and grade your recall on a simple "
            "four-point scale - Again, Hard, Good, or Easy. SourceMind uses that "
            "grade to schedule when the card comes back: cards you find hard "
            "resurface sooner, cards you know well drift further out.",
            "Quizzes are multiple-choice, scored automatically the moment you "
            "submit - answers are compared deterministically, so your score never "
            "depends on interpretation. You can retake a quiz on the same "
            "material as many times as you like.",
            "One more thing worth knowing: if you regenerate a chapter's "
            "flashcards later - after editing the outline, or just wanting a "
            "fresh set - any card whose question and answer come out identical to "
            "before keeps its review history. Only cards that actually changed "
            "start over. Your progress is never thrown away by accident.",
        ],
    ),
]

CHAPTER_3_PAGES = [
    (
        "Chapter 3: Reading Efficiently",
        [
            "SourceMind remembers where you left off. As you read, your position "
            "is saved automatically in the background - per chapter, as a "
            "fraction of how far down the page you've scrolled, not a raw pixel "
            "count, so it resumes correctly no matter your window size or zoom "
            "level. Close the tab, come back tomorrow, and you're back exactly "
            "where you stopped.",
            "The review queue works the same way. It's ordered by what's due, "
            "then by when each card was created - a fixed, stable order that "
            "doesn't reshuffle between visits. That means you can review ten "
            "cards, close the app, and come back later to pick up exactly where "
            "you left off in the queue, with no extra bookmarking required.",
        ],
    ),
    (
        None,
        [
            "SourceMind is built keyboard-first - press ? anywhere to open a "
            "shortcuts overlay for whatever screen you're on. In the reader: "
            "the left/right arrows (or j and k) move between chapters, s "
            "switches between the source text and its generated lesson, and c "
            "opens or closes the course chat. In a review session: Space "
            "reveals a card's answer, then 1 through 4 grade your recall "
            "(Again, Hard, Good, Easy). In a quiz: 1 through 4 pick an answer "
            "choice, and Enter moves to the next question - or submits the "
            "quiz on the last one. Every control also remains reachable with "
            "plain Tab and Enter if you prefer.",
            "That's the whole loop: upload a PDF, read it for free the moment "
            "it's ingested, and generate the extras - lessons, flashcards, "
            "quizzes - only when and where you actually want them, with your "
            "spending visible the whole way. This sample course will still be "
            "here under My Courses if you want to come back to it; deleting it "
            "won't bring it back automatically, so feel free to explore without "
            "worrying about tidying up afterward.",
        ],
    ),
]

CHAPTERS = [
    ("How SourceMind Works", CHAPTER_1_PAGES),
    ("Lessons, Flashcards and Quizzes", CHAPTER_2_PAGES),
    ("Reading Efficiently", CHAPTER_3_PAGES),
]


def make_sample() -> Path:
    doc = fitz.open()
    toc: list[list] = []
    page_index = 0

    for chapter_title, pages in CHAPTERS:
        toc.append([1, chapter_title, page_index + 1])  # set_toc pages are 1-based
        for heading, paragraphs in pages:
            _add_page(doc, heading, paragraphs)
            page_index += 1

    doc.set_toc(toc)
    _set_fixed_metadata(doc)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT_PATH), no_new_id=1)
    doc.close()
    return OUT_PATH


def main(argv: list[str]) -> int:
    out = make_sample()
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
