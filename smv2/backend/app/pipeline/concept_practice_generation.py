from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    Concept,
    ConceptSourceLink,
    CurriculumVersion,
    Job,
    LearningClaimRevision,
    PracticeQuestion,
    Section,
)
from app.jobs.llm_job_control import completion_options_for_job
from app.llm.ledger import ensure_spend_cap, record_llm_call
from app.llm.prompts import load_prompt
from app.llm.provider import get_provider
from app.pipeline._common import report_progress_in_session, strip_leading_fence
from app.services import evidence_items_service

_MAX_SOURCE_CHARS = 12_000
_MAX_TOKENS = 4096
_MAX_QUESTIONS = 8


def parse_concept_practice(text: str, allowed_claim_ids: set[str]) -> list[dict[str, Any]]:
    data = json.loads(strip_leading_fence(text), parse_constant=_reject_constant)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of concept practice questions")
    parsed = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"question {index} must be an object")
        claim_id = item.get("claim_id")
        if claim_id not in allowed_claim_ids:
            raise ValueError(f"question {index} references an unknown claim id")
        choices = item.get("choices")
        correct_index = item.get("correct_index")
        if (
            not isinstance(item.get("stem_md"), str)
            or not item["stem_md"].strip()
            or not isinstance(choices, list)
            or len(choices) != 4
            or not all(isinstance(choice, str) and choice.strip() for choice in choices)
            or isinstance(correct_index, bool)
            or not isinstance(correct_index, int)
            or not 0 <= correct_index < 4
        ):
            raise ValueError(f"question {index} has invalid content")
        confidence = item.get("mapping_confidence")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= confidence <= 1
        ):
            raise ValueError(f"question {index} has invalid mapping confidence")
        required_strings = (
            "explanation_md",
            "task_type",
            "cognitive_demand",
            "difficulty_band",
            "source_ref",
        )
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in required_strings):
            raise ValueError(f"question {index} is missing mapping metadata")
        parsed.append(
            {
                "claim_id": claim_id,
                "stem_md": item["stem_md"].strip(),
                "choices": [choice.strip() for choice in choices],
                "correct_index": correct_index,
                "explanation_md": item["explanation_md"].strip(),
                "task_type": item["task_type"].strip(),
                "cognitive_demand": item["cognitive_demand"].strip(),
                "difficulty_band": item["difficulty_band"].strip(),
                "mapping_confidence": float(confidence),
                "source_ref": item["source_ref"].strip(),
            }
        )
    return parsed[:_MAX_QUESTIONS]


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _fingerprint(question: dict[str, Any]) -> str:
    encoded = json.dumps(question, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def run_concept_practice_generation(
    session: Session,
    job: Job,
    course_id: str,
    concept_id: str,
    curriculum_version_id: str,
) -> dict[str, Any]:
    version = session.get(CurriculumVersion, curriculum_version_id)
    concept = session.get(Concept, concept_id)
    if (
        version is None
        or concept is None
        or version.course_id != course_id
        or concept.course_id != course_id
        or not version.is_current
    ):
        raise ValueError("concept practice job references a non-current curriculum concept")
    claim_rows = (
        session.query(LearningClaimRevision, ConceptSourceLink, Section)
        .join(
            ConceptSourceLink,
            ConceptSourceLink.learning_claim_id == LearningClaimRevision.learning_claim_id,
        )
        .join(Section, Section.id == ConceptSourceLink.section_id)
        .filter(
            LearningClaimRevision.curriculum_version_id == version.id,
            LearningClaimRevision.concept_id == concept_id,
            LearningClaimRevision.is_active.is_(True),
            LearningClaimRevision.review_state != "rejected",
            ConceptSourceLink.curriculum_version_id == version.id,
            ConceptSourceLink.stale.is_(False),
            ConceptSourceLink.review_state != "rejected",
        )
        .all()
    )
    if not claim_rows:
        raise ValueError("concept has no active source-grounded claims")
    options = {
        revision.learning_claim_id: {
            "claim_id": revision.learning_claim_id,
            "statement": revision.statement,
            "success_criteria_md": revision.success_criteria_md,
            "source_ref": source.source_ref,
        }
        for revision, source, _section in claim_rows
    }
    source_text = "\n\n".join(
        f"## {section.title}\n{(source.excerpt_md or section.body_md)[:4000]}"
        for _revision, source, section in claim_rows
    )[:_MAX_SOURCE_CHARS]
    system_prompt, prompt_version = load_prompt("concept_practice")
    messages = [
        {
            "role": "user",
            "content": (
                f"<allowed_claims>\n{json.dumps(list(options.values()))}\n</allowed_claims>\n\n"
                f"<source_text>\n{source_text}\n</source_text>"
            ),
        }
    ]
    provider = get_provider()
    completion_options = completion_options_for_job(job.id, artifact="concept_practice")
    questions = None
    result = None
    for attempt in range(2):
        ensure_spend_cap(course_id)
        result = provider.complete(
            messages,
            max_tokens=_MAX_TOKENS,
            purpose="concept_practice",
            course_id=course_id,
            prompt_version=prompt_version,
            system=system_prompt,
            wait_for_slot=True,
            options=completion_options,
        )
        try:
            questions = parse_concept_practice(result.text, set(options))
            break
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt == 1:
                record_llm_call(
                    purpose="concept_practice",
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    latency_ms=0,
                    cost_estimate=None,
                    prompt_version=prompt_version,
                    status="parse_failure",
                    course_id=course_id,
                )
                raise ValueError(
                    f"concept practice produced unparseable output after one retry: {exc}"
                ) from exc
    assert questions is not None and result is not None
    created = 0
    for index, question_data in enumerate(questions):
        matching = next(
            row for row in claim_rows if row[0].learning_claim_id == question_data["claim_id"]
        )
        _revision, source, section = matching
        fingerprint = _fingerprint(question_data)
        question = session.query(PracticeQuestion).filter_by(
            course_id=course_id,
            section_id=section.id,
            source_fingerprint=fingerprint,
        ).one_or_none()
        if question is None:
            question = PracticeQuestion(
                course_id=course_id,
                chapter_label=section.chapter_label,
                section_id=section.id,
                concept_id=concept_id,
                problem_number=f"adaptive-{index + 1}",
                source_ref=question_data["source_ref"],
                stem_md=question_data["stem_md"],
                choices=question_data["choices"],
                correct_index=question_data["correct_index"],
                explanation_md=question_data["explanation_md"],
                source_fingerprint=fingerprint,
                extraction_version="concept-practice-v1",
                confidence=question_data["mapping_confidence"],
                status="ready",
            )
            session.add(question)
            session.flush()
            created += 1
        evidence_item = evidence_items_service.snapshot_item(
            session,
            course_id=course_id,
            item_type="practice_question",
            source_record_id=question.id,
            source_index=-1,
            content={
                "stem_md": question.stem_md,
                "choices": question.choices,
                "correct_index": question.correct_index,
                "explanation_md": question.explanation_md,
            },
            source_ref=source.source_ref,
            prompt_version=prompt_version,
            model=result.model,
        )
        evidence_items_service.map_item_to_claim(
            session,
            evidence_item,
            curriculum_version_id=version.id,
            learning_claim_id=question_data["claim_id"],
            role="primary",
            task_type=question_data["task_type"],
            cognitive_demand=question_data["cognitive_demand"],
            authored_difficulty_band=question_data["difficulty_band"],
            mapping_confidence=question_data["mapping_confidence"],
            source_ref=question_data["source_ref"],
            prompt_version=prompt_version,
            model=result.model,
            review_state="unverified",
        )
    report_progress_in_session(job, stage="done", pct=100, message="concept practice ready")
    return {"created_count": created, "question_count": len(questions)}
