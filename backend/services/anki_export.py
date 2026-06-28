"""Anki TSV export for SourceMind courses — Task 11."""
from __future__ import annotations

from SourceMind.backend.db import base, models


def _escape(value: str) -> str:
    """Replace tab/newline characters so each field stays within a single column."""
    return value.replace("\t", " ").replace("\r", "").replace("\n", "<br>")


def build_anki_tsv(course_id: str) -> str:
    """Build a 3-column Anki TSV deck (Front, Back, Tags) for all chapters.

    For each chapter:

    * **Quiz items** — Front = question + lettered options (A, B, C …);
      Back = correct option text + ``<br>`` + explanation.
    * **Spaced-repetition cards** — Front = ``q``; Back = ``a``.

    Tag column is ``sourcemind::{course_id}::{section_id}``.

    HTML-unsafe characters inside fields are escaped (tabs → space,
    newlines → ``<br>``).

    Returns the full TSV string with rows joined by ``\\n``; empty string when
    the course has no chapters or all chapters have empty quiz/cards.
    """
    rows: list[str] = []

    with base.get_session() as session:
        chapters = (
            session.query(models.Chapter)
            .filter_by(course_id=course_id)
            .all()
        )

        for chapter in chapters:
            section_id = chapter.section_id or ""
            tag = f"sourcemind::{course_id}::{section_id}"

            # ── Quiz items ──────────────────────────────────────────────────
            for item in (chapter.quiz or []):
                q: str = item.get("q", "")
                options: list[str] = item.get("options") or []
                answer_idx: int = item.get("answer", 0)
                explain: str = item.get("explain", "")

                front_parts = [q]
                for i, opt in enumerate(options):
                    front_parts.append(f"{chr(65 + i)}. {opt}")
                front = "<br>".join(front_parts)

                answer_text = (
                    options[answer_idx]
                    if 0 <= answer_idx < len(options)
                    else ""
                )
                back_parts = [answer_text]
                if explain:
                    back_parts.append(explain)
                back = "<br>".join(back_parts)

                rows.append(f"{_escape(front)}\t{_escape(back)}\t{tag}")

            # ── Spaced-repetition cards ────────────────────────────────────
            for card in (chapter.cards or []):
                q = card.get("q", "")
                a = card.get("a", "")
                rows.append(f"{_escape(q)}\t{_escape(a)}\t{tag}")

    return "\n".join(rows)
