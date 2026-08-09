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
from dataclasses import replace
from typing import Any

from sqlalchemy.orm import Session

from app.db.identity import card_id_for
from app.db.models import Card, Job, Section
from app.jobs.llm_job_control import completion_options_for_job
from app.llm.ledger import ensure_spend_cap, record_llm_call
from app.llm.prompts import load_prompt
from app.llm.provider import get_provider
from app.llm.structured_output import CARDS_SCHEMA, InvalidModelOutputError, repair_messages
from app.pipeline._common import report_progress as _report_progress
from app.pipeline._common import (
    report_progress_in_session as _report_progress_in_session,
)
from app.pipeline._common import strip_leading_fence as _strip_leading_fence
from app.services import evidence_items_service

logger = logging.getLogger(__name__)

_MAX_TOKENS = 4096
_MAX_CARDS = 8


def _build_messages(
    section: Section, claim_options: list[dict[str, Any]] | None = None
) -> tuple[str, list[dict]]:
    system_prompt, _ = load_prompt("cards")
    user_content = (
        f"Chapter title: {section.title}\n\n"
        f"<allowed_claims>\n{json.dumps(claim_options or [], ensure_ascii=False)}\n"
        f"</allowed_claims>\n\n<source_text>\n{section.body_md}\n</source_text>"
    )
    return system_prompt, [{"role": "user", "content": user_content}]


def _parse_cards(
    text: str, allowed_claim_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    """Parses the model's JSON array defensively: a top-level parse
    failure raises (caller retries once); individual malformed items are
    dropped (logged) rather than failing the whole batch.
    """
    data = json.loads(_strip_leading_fence(text))
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of cards")

    cards: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("dropping malformed card item %d: not an object", i)
            continue
        front, back = item.get("front"), item.get("back")
        if not isinstance(front, str) or not front.strip() or not isinstance(back, str) or not back.strip():
            logger.warning("dropping malformed card item %d: missing/empty front or back", i)
            continue
        card = {"front": front.strip(), "back": back.strip()}
        if allowed_claim_ids:
            claim_id = item.get("claim_id")
            if not isinstance(claim_id, str) or claim_id not in allowed_claim_ids:
                raise ValueError(f"card {i} references an unknown claim id")
            mapping_confidence = item.get("mapping_confidence")
            if (
                isinstance(mapping_confidence, bool)
                or not isinstance(mapping_confidence, (int, float))
                or not 0 <= mapping_confidence <= 1
            ):
                raise ValueError(f"card {i} has invalid mapping confidence")
            for field in ("task_type", "cognitive_demand", "difficulty_band", "source_ref"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ValueError(f"card {i} is missing {field}")
            card.update(
                {
                    "claim_id": claim_id,
                    "task_type": item["task_type"].strip(),
                    "cognitive_demand": item["cognitive_demand"].strip(),
                    "difficulty_band": item["difficulty_band"].strip(),
                    "mapping_confidence": float(mapping_confidence),
                    "source_ref": item["source_ref"].strip(),
                }
            )
        cards.append(card)

    return cards


def run_card_generation(session: Session, job: Job, section_id: str) -> dict[str, Any]:
    section = session.get(Section, section_id)
    if section is None:
        raise ValueError(f"section not found: {section_id}")

    _report_progress(job.id, stage="loading", pct=None, message=f"preparing flashcards for {section.title}")

    curriculum_version_id, claim_options = evidence_items_service.claim_options_for_sections(
        session, section.course_id, [section.id]
    )
    allowed_claim_ids = {option["claim_id"] for option in claim_options}
    system_prompt, messages = _build_messages(section, claim_options)
    _, prompt_version = load_prompt("cards")
    provider = get_provider()
    completion_options = replace(
        completion_options_for_job(job.id, artifact="flashcards"),
        response_schema=CARDS_SCHEMA,
    )

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
        options=completion_options,
    )

    try:
        cards_data = _parse_cards(result.text, allowed_claim_ids)
    except (json.JSONDecodeError, ValueError) as exc:
        # Bounded: one retry on a whole-response parse failure, then give up.
        _report_progress(job.id, stage="retrying", pct=50, message="retrying malformed response")
        repair_request = repair_messages(messages, exc)
        result = provider.complete(
            repair_request,
            max_tokens=_MAX_TOKENS,
            purpose="cards",
            course_id=section.course_id,
            prompt_version=prompt_version,
            system=system_prompt,
            wait_for_slot=True,
            options=completion_options,
        )
        try:
            cards_data = _parse_cards(result.text, allowed_claim_ids)
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
            raise InvalidModelOutputError(exc) from exc

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
                "mapping": {key: c[key] for key in (
                    "claim_id",
                    "task_type",
                    "cognitive_demand",
                    "difficulty_band",
                    "mapping_confidence",
                    "source_ref",
                ) if key in c},
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
        card_row = existing
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
            card_row = Card(
                    id=data["id"],
                    course_id=section.course_id,
                    section_id=section_id,
                    front_md=data["front"],
                    back_md=data["back"],
                    position=data["position"],
                    prompt_version=prompt_version,
                    origin="generated",
            )
            session.add(card_row)
        assert card_row is not None
        evidence_item = evidence_items_service.snapshot_item(
            session,
            course_id=section.course_id,
            item_type="flashcard",
            source_record_id=card_row.id,
            source_index=-1,
            content={"front": data["front"], "back": data["back"]},
            source_ref=data["mapping"].get("source_ref", section.title),
            prompt_version=prompt_version,
            model=result.model,
        )
        mapping = data["mapping"]
        if mapping and curriculum_version_id is not None:
            evidence_items_service.map_item_to_claim(
                session,
                evidence_item,
                curriculum_version_id=curriculum_version_id,
                learning_claim_id=mapping["claim_id"],
                role="primary",
                task_type=mapping["task_type"],
                cognitive_demand=mapping["cognitive_demand"],
                authored_difficulty_band=mapping["difficulty_band"],
                mapping_confidence=mapping["mapping_confidence"],
                source_ref=mapping["source_ref"],
                prompt_version=prompt_version,
                model=result.model,
                review_state="unverified",
            )

    # In-session (not report_progress): the card diff (deletes/inserts) is
    # already pending on this session — see report_progress_in_session's
    # docstring.
    _report_progress_in_session(job, stage="done", pct=100, message="cards ready")
    session.commit()

    return {"card_count": len(new_cards_by_id)}
