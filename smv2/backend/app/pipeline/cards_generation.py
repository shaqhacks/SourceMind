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
from typing import Any

from sqlalchemy.orm import Session

from app.db.identity import card_id_for
from app.db.models import Card, Job, Section
from app.llm.ledger import ensure_spend_cap, record_llm_call
from app.llm.prompts import load_prompt
from app.llm.provider import get_provider
from app.pipeline._common import report_progress as _report_progress
from app.pipeline._common import report_progress_in_session as _report_progress_in_session
from app.pipeline._common import strip_leading_fence as _strip_leading_fence

logger = logging.getLogger(__name__)

_MAX_TOKENS = 4096
_MAX_CARDS = 8


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

    _report_progress(job.id, stage="generating", pct=10, message=f"generating cards for {section.title}")

    system_prompt, messages = _build_messages(section)
    _, prompt_version = load_prompt("cards")
    provider = get_provider()

    # Same cap discipline as lesson generation (app/llm/ledger.ensure_spend_cap):
    # checked immediately before the call, no yield points in between.
    ensure_spend_cap(section.course_id)

    # wait_for_slot=True: durable job, not an interactive request — wait out
    # a busy limiter (bounded) rather than fail the job over transient chat
    # traffic saturating the same slots.
    result = provider.complete(
        messages,
        max_tokens=_MAX_TOKENS,
        purpose="cards",
        course_id=section.course_id,
        prompt_version=prompt_version,
        system=system_prompt,
        wait_for_slot=True,
    )

    try:
        cards_data = _parse_cards(result.text)
    except (json.JSONDecodeError, ValueError):
        # Bounded: one retry on a whole-response parse failure, then give up.
        _report_progress(job.id, stage="retrying", pct=50, message="retrying malformed response")
        result = provider.complete(
            messages,
            max_tokens=_MAX_TOKENS,
            purpose="cards",
            course_id=section.course_id,
            prompt_version=prompt_version,
            system=system_prompt,
            wait_for_slot=True,
        )
        try:
            cards_data = _parse_cards(result.text)
        except (json.JSONDecodeError, ValueError) as exc:
            # The provider wrapper already recorded this same call as
            # status='ok' (the completion succeeded at the transport level);
            # this is the semantic layer recording that its CONTENT was
            # unusable. cost_estimate stays None — that spend was already
            # counted by the 'ok' row, and double-recording it here would
            # double-count against course_spend_so_far().
            record_llm_call(
                purpose="cards",
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=0,
                cost_estimate=None,
                prompt_version=prompt_version,
                status="parse_failure",
                course_id=section.course_id,
            )
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

    # ADR-023: the delete side of this diff applies ONLY to origin=
    # 'generated' cards — a user-authored card, or one that started as
    # generated but was then edited (edit mints a NEW origin='user' card,
    # app/services/cards_service.py::update_card), must survive
    # regeneration untouched, same "don't clobber what a person
    # deliberately customized" philosophy as re-ingest's replace/remap
    # split (smv2-invariants law #2/#3).
    for existing_id, existing in list(existing_cards.items()):
        if existing.origin == "generated" and existing_id not in new_ids:
            session.delete(existing)  # cascades this card's ReviewState/ReviewLog only
    session.flush()

    for data in new_cards_by_id.values():
        existing = existing_cards.get(data["id"])
        if existing is not None:
            if existing.origin == "user":
                # A user-origin card happens to already BE this exact
                # content (e.g. the learner's own edit converged on the
                # same text the model just generated) — keep the user's
                # card as-is, skip the insert entirely rather than
                # touching a card the diff isn't supposed to manage.
                continue
            existing.position = data["position"]
            existing.prompt_version = prompt_version
        else:
            session.add(
                Card(
                    id=data["id"],
                    course_id=section.course_id,
                    section_id=section_id,
                    front_md=data["front"],
                    back_md=data["back"],
                    position=data["position"],
                    prompt_version=prompt_version,
                    origin="generated",
                )
            )

    # In-session (not report_progress): the card diff (deletes/inserts) is
    # already pending on this session — see report_progress_in_session's
    # docstring.
    _report_progress_in_session(job, stage="done", pct=100, message="cards ready")
    session.commit()

    return {"card_count": len(new_cards_by_id)}
