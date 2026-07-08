"""Textbook-backed practice assessment extraction.

The parser is deliberately fail-closed: generated distractors are allowed,
but the persisted correct answer must exactly match the model's explicit
textbook-answer field, which is instructed to come from the answer key.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Concept, Job, PracticeExtractionRun, PracticeQuestion, Section
from app.llm.ledger import ensure_spend_cap
from app.llm.prompts import load_prompt
from app.llm.provider import get_provider
from app.pipeline._common import report_progress_in_session as _report_progress_in_session
from app.pipeline._common import strip_leading_fence as _strip_leading_fence

logger = logging.getLogger(__name__)

_MAX_TOKENS = 4096


def parse_practice_questions(text: str) -> list[dict[str, Any]]:
    data = json.loads(_strip_leading_fence(text))
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of practice questions")

    questions: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        parsed = _parse_practice_question_item(item)
        if parsed is None:
            logger.warning("dropping malformed practice question item %d", i)
            continue
        questions.append(parsed)
    return questions


def _parse_practice_question_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    problem_number = _non_empty_str(item.get("problem_number"))
    stem_md = _non_empty_str(item.get("stem_md"))
    textbook_answer_md = _non_empty_str(item.get("textbook_answer_md"))
    choices = item.get("choices")
    correct_index = item.get("correct_index")
    explanation_md = _non_empty_str(item.get("explanation_md"))
    concept_slug = _non_empty_str(item.get("concept_slug"))
    concept_label = _non_empty_str(item.get("concept_label"))
    answer_source_ref = _non_empty_str(item.get("answer_source_ref"))
    confidence = item.get("confidence")

    if not all(
        [
            problem_number,
            stem_md,
            textbook_answer_md,
            explanation_md,
            concept_slug,
            concept_label,
            answer_source_ref,
        ]
    ):
        return None
    if not isinstance(choices, list) or len(choices) != 4:
        return None
    if not all(isinstance(choice, str) and choice.strip() for choice in choices):
        return None
    if not isinstance(correct_index, int) or isinstance(correct_index, bool):
        return None
    if not 0 <= correct_index <= 3:
        return None
    normalized_choices = [choice.strip() for choice in choices]
    if normalized_choices[correct_index] != textbook_answer_md.strip():
        return None
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return None
    if confidence < 0.7:
        return None

    return {
        "problem_number": problem_number,
        "stem_md": stem_md,
        "choices": normalized_choices,
        "correct_index": correct_index,
        "explanation_md": explanation_md,
        "concept_slug": concept_slug,
        "concept_label": concept_label,
        "answer_source_ref": answer_source_ref,
        "confidence": float(confidence),
    }


def _non_empty_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def run_practice_extraction(
    session: Session,
    job: Job,
    course_id: str,
    section_id: str,
    run_id: str,
) -> dict[str, Any]:
    run = session.get(PracticeExtractionRun, run_id)
    if run is None:
        raise ValueError("practice extraction run not found")
    if run.course_id != course_id or run.section_id != section_id:
        raise ValueError("practice extraction run payload mismatch")

    section = session.get(Section, section_id)
    if section is None or section.course_id != course_id:
        raise ValueError("practice section not found")
    if section.kind != "practice":
        raise ValueError("section is not a practice section")

    answer_sections = (
        session.query(Section)
        .filter(
            Section.course_id == course_id,
            Section.kind == "answers",
            Section.chapter_label == section.chapter_label,
        )
        .order_by(Section.order_index)
        .all()
    )

    run.status = "running"
    run.error = None
    _report_progress_in_session(job, stage="extracting", pct=10, message="extracting practice")

    if not answer_sections:
        raise ValueError("no answer key sections found for practice section")

    system_prompt, prompt_version = load_prompt("practice_assessment")
    messages = [{"role": "user", "content": _build_user_message(section, answer_sections)}]
    provider = get_provider()

    ensure_spend_cap(course_id)
    result = provider.complete(
        messages,
        max_tokens=_MAX_TOKENS,
        purpose="practice_assessment",
        course_id=course_id,
        prompt_version=prompt_version,
        system=system_prompt,
        wait_for_slot=True,
    )

    questions = parse_practice_questions(result.text)
    if not questions:
        raise ValueError("practice assessment extraction produced zero usable questions")

    answer_section = answer_sections[0]
    ready_count = 0
    for item in questions:
        concept = _upsert_concept(session, section, item)
        source_fingerprint = _source_fingerprint(section, item, prompt_version)
        question = (
            session.query(PracticeQuestion)
            .filter(
                PracticeQuestion.course_id == course_id,
                PracticeQuestion.section_id == section.id,
                PracticeQuestion.source_fingerprint == source_fingerprint,
            )
            .one_or_none()
        )
        if question is None:
            question = PracticeQuestion(course_id=course_id, section_id=section.id)
            session.add(question)
        _apply_question_fields(
            question,
            section=section,
            answer_section=answer_section,
            concept=concept,
            item=item,
            prompt_version=prompt_version,
            source_fingerprint=source_fingerprint,
        )
        ready_count += 1

    run.status = "ready"
    run.question_count = ready_count
    run.error = None
    _report_progress_in_session(job, stage="done", pct=100, message="practice ready")
    return {"question_count": ready_count}


def _build_user_message(section: Section, answer_sections: list[Section]) -> str:
    practice_body = "\n".join(
        [
            "<practice_section>",
            f"<title>{section.title}</title>",
            "<body_md>",
            section.body_md or "",
            "</body_md>",
            "</practice_section>",
        ]
    )
    answer_parts = [_section_tag(answer_section) for answer_section in answer_sections]
    return "\n".join(
        [
            practice_body,
            "<answer_key_sections>",
            "\n".join(answer_parts),
            "</answer_key_sections>",
        ]
    )


def _section_tag(section: Section) -> str:
    return "\n".join(
        [
            "<answer_key_section>",
            f"<title>{section.title}</title>",
            "<body_md>",
            section.body_md or "",
            "</body_md>",
            "</answer_key_section>",
        ]
    )


def _upsert_concept(session: Session, section: Section, item: dict[str, Any]) -> Concept:
    concept = (
        session.query(Concept)
        .filter(Concept.course_id == section.course_id, Concept.slug == item["concept_slug"])
        .one_or_none()
    )
    if concept is None:
        concept = Concept(
            course_id=section.course_id,
            slug=item["concept_slug"],
            label=item["concept_label"],
            chapter_label=section.chapter_label,
            section_id=section.id,
        )
        session.add(concept)
        session.flush()
        return concept

    concept.label = item["concept_label"]
    if concept.chapter_label is None:
        concept.chapter_label = section.chapter_label
    if concept.section_id is None:
        concept.section_id = section.id
    return concept


def _source_fingerprint(section: Section, item: dict[str, Any], prompt_version: str) -> str:
    digest = hashlib.sha256()
    for value in (
        section.content_hash,
        item["problem_number"],
        item["answer_source_ref"],
        prompt_version,
    ):
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _apply_question_fields(
    question: PracticeQuestion,
    *,
    section: Section,
    answer_section: Section,
    concept: Concept,
    item: dict[str, Any],
    prompt_version: str,
    source_fingerprint: str,
) -> None:
    question.chapter_label = section.chapter_label
    question.concept_id = concept.id
    question.source_asset_id = section.asset_id
    question.source_page_start = section.page_start
    question.source_page_end = section.page_end
    question.problem_number = item["problem_number"]
    question.source_ref = f"{section.title} #{item['problem_number']}"
    question.answer_section_id = answer_section.id
    question.answer_source_ref = item["answer_source_ref"]
    question.stem_md = item["stem_md"]
    question.choices = item["choices"]
    question.correct_index = item["correct_index"]
    question.explanation_md = item["explanation_md"]
    question.source_fingerprint = source_fingerprint
    question.extraction_version = prompt_version
    question.confidence = item["confidence"]
    question.status = "ready"
