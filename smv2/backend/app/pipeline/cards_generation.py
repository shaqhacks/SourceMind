"""Card generation pipeline: ONE bounded LLM call per section, producing
4-8 Q/A flashcards as a JSON array. Cards are content-addressed
(card_id_for(section_id, front, back)) so re-generation diffs against the
existing set exactly like re-ingest diffs sections: unchanged front/back
text keeps the same id, and everything hanging off that id (ReviewState,
ReviewLog) survives untouched via ON DELETE CASCADE only ever removing
cards that actually disappeared.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.identity import card_id_for
from app.db.models import Card, Job, Section, utcnow
from app.llm.prompts import load_prompt
from app.llm.provider import get_provider

logger = logging.getLogger(__name__)

_PROGRESS_LEASE_EXTENSION_SECONDS = 60
_MAX_TOKENS = 4096
_MAX_CARDS = 8


def _report_progress(session: Session, job: Job, stage: str, pct: int, message: str) -> None:
    job.progress = {"stage": stage, "pct": pct, "message": message}
    job.lease_until = utcnow() + timedelta(seconds=_PROGRESS_LEASE_EXTENSION_SECONDS)
    session.commit()


def _strip_leading_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines:
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _build_messages(section: Section) -> tuple[str, list[dict]]:
    system_prompt, _ = load_prompt("cards")
    user_content = f"Chapter title: {section.title}\n\n<source_text>\n{section.body_md}\n</source_text>"
    return system_prompt, [{"role": "user", "content": user_content}]


def _parse_cards(text: str) -> list[dict[str, str]]:
    """Parses the model's JSON array defensively: a top-level parse
    failure raises (caller retries once); individual malformed items are
    dropped (logged) rather than failing the whole batch.
    """
    data = json.loads(_strip_leading_fence(text))
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of cards")

    cards: list[dict[str, str]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("dropping malformed card item %d: not an object", i)
            continue
        front, back = item.get("front"), item.get("back")
        if not isinstance(front, str) or not front.strip() or not isinstance(back, str) or not back.strip():
            logger.warning("dropping malformed card item %d: missing/empty front or back", i)
            continue
        cards.append({"front": front.strip(), "back": back.strip()})

    return cards


def run_card_generation(session: Session, job: Job, section_id: str) -> dict[str, Any]:
    section = session.get(Section, section_id)
    if section is None:
        raise ValueError(f"section not found: {section_id}")

    _report_progress(
        session, job, stage="generating", pct=10, message=f"generating cards for {section.title}"
    )

    system_prompt, messages = _build_messages(section)
    _, prompt_version = load_prompt("cards")
    provider = get_provider()

    result = provider.complete(
        messages,
        max_tokens=_MAX_TOKENS,
        purpose="cards",
        course_id=section.course_id,
        prompt_version=prompt_version,
        system=system_prompt,
    )

    try:
        cards_data = _parse_cards(result.text)
    except (json.JSONDecodeError, ValueError):
        # Bounded: one retry on a whole-response parse failure, then give up.
        _report_progress(session, job, stage="retrying", pct=50, message="retrying malformed response")
        result = provider.complete(
            messages,
            max_tokens=_MAX_TOKENS,
            purpose="cards",
            course_id=section.course_id,
            prompt_version=prompt_version,
            system=system_prompt,
        )
        try:
            cards_data = _parse_cards(result.text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"card generation produced unparseable output after one retry: {exc}") from exc

    if not cards_data:
        raise ValueError("card generation produced zero usable cards")

    # Content-addressed diff, same pattern as re-ingest: unchanged
    # front/back -> same id -> ReviewState/ReviewLog survive untouched.
    # Two model-produced cards with identical front+back would otherwise
    # collide on the same id — deduping here (first occurrence wins) keeps
    # that a no-op instead of a primary-key violation at insert time.
    new_cards_by_id: dict[str, dict[str, Any]] = {}
    for c in cards_data[:_MAX_CARDS]:
        card_id = card_id_for(section_id, c["front"], c["back"])
        if card_id not in new_cards_by_id:
            new_cards_by_id[card_id] = {
                "id": card_id,
                "front": c["front"],
                "back": c["back"],
                "position": len(new_cards_by_id),
            }

    existing_cards = {c.id: c for c in session.query(Card).filter(Card.section_id == section_id).all()}
    new_ids = set(new_cards_by_id)

    for existing_id, existing in list(existing_cards.items()):
        if existing_id not in new_ids:
            session.delete(existing)  # cascades this card's ReviewState/ReviewLog only
    session.flush()

    for data in new_cards_by_id.values():
        existing = existing_cards.get(data["id"])
        if existing is not None:
            existing.position = data["position"]
        else:
            session.add(
                Card(
                    id=data["id"],
                    course_id=section.course_id,
                    section_id=section_id,
                    front_md=data["front"],
                    back_md=data["back"],
                    position=data["position"],
                )
            )

    _report_progress(session, job, stage="done", pct=100, message="cards ready")
    session.commit()

    return {"card_count": len(new_cards_by_id)}
