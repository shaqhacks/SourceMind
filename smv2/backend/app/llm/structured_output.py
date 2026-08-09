from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

SAFE_INVALID_MODEL_OUTPUT_DETAIL = {
    "code": "invalid_model_output",
    "message": "The model returned an invalid question format.",
    "failure_category": "structured_output_invalid",
}

logger = logging.getLogger(__name__)


class InvalidModelOutputError(Exception):
    def __init__(self, validation_error: BaseException):
        super().__init__(SAFE_INVALID_MODEL_OUTPUT_DETAIL["message"])
        self.error_detail = dict(SAFE_INVALID_MODEL_OUTPUT_DETAIL)
        self.__cause__ = validation_error
        logger.warning(
            "structured LLM output failed validation",
            exc_info=(
                type(validation_error),
                validation_error,
                validation_error.__traceback__,
            ),
        )


def repair_messages(messages: list[dict], validation_error: BaseException) -> list[dict]:
    """Ask for one format-only correction without echoing raw model output."""
    del validation_error
    repaired = deepcopy(messages)
    repaired.append(
        {
            "role": "user",
            "content": (
                "Your previous response could not be parsed or validated. "
                "Return the requested question format. "
                "Return only valid JSON matching the supplied response schema. "
                "Do not include markdown fences, prose, or extra keys. "
                "Use only allowed claim IDs and source IDs from the prompt."
            ),
        }
    )
    return repaired


def _string_schema(*, nullable: bool = False) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if nullable:
        schema["type"] = ["string", "null"]
    return schema


_source_schema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["section_id", "source_ref", "excerpt_md"],
    "properties": {
        "section_id": _string_schema(),
        "source_ref": _string_schema(),
        "excerpt_md": _string_schema(),
    },
}


CARDS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "front",
            "back",
            "claim_id",
            "task_type",
            "cognitive_demand",
            "difficulty_band",
            "mapping_confidence",
            "source_ref",
        ],
        "properties": {
            "front": _string_schema(),
            "back": _string_schema(),
            "claim_id": _string_schema(),
            "task_type": _string_schema(),
            "cognitive_demand": _string_schema(),
            "difficulty_band": _string_schema(),
            "mapping_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source_ref": _string_schema(),
        },
    },
}

QUIZ_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "question",
            "choices",
            "correct_index",
            "explanation",
            "claim_id",
            "task_type",
            "cognitive_demand",
            "difficulty_band",
            "mapping_confidence",
            "source_ref",
        ],
        "properties": {
            "question": _string_schema(),
            "choices": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": _string_schema(),
            },
            "correct_index": {"type": "integer", "minimum": 0, "maximum": 3},
            "explanation": _string_schema(),
            "claim_id": _string_schema(),
            "task_type": _string_schema(),
            "cognitive_demand": _string_schema(),
            "difficulty_band": _string_schema(),
            "mapping_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source_ref": _string_schema(),
        },
    },
}

PRACTICE_ASSESSMENT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "problem_number",
            "stem_md",
            "textbook_answer_md",
            "choices",
            "correct_index",
            "explanation_md",
            "concept_slug",
            "concept_label",
            "answer_source_ref",
            "confidence",
            "claim_id",
        ],
        "properties": {
            "problem_number": _string_schema(),
            "stem_md": _string_schema(),
            "textbook_answer_md": _string_schema(),
            "choices": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": _string_schema(),
            },
            "correct_index": {"type": "integer", "minimum": 0, "maximum": 3},
            "explanation_md": _string_schema(),
            "concept_slug": _string_schema(),
            "concept_label": _string_schema(),
            "answer_source_ref": _string_schema(),
            "confidence": {"type": "number", "minimum": 0.7, "maximum": 1},
            "claim_id": _string_schema(),
        },
    },
}

CURRICULUM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["concepts", "claims", "relations"],
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "stable_key",
                    "label",
                    "description_md",
                    "aliases",
                    "chapter_label",
                    "sources",
                    "confidence",
                    "rationale_md",
                ],
                "properties": {
                    "stable_key": _string_schema(),
                    "label": _string_schema(),
                    "description_md": _string_schema(),
                    "aliases": {"type": "array", "items": _string_schema()},
                    "chapter_label": _string_schema(nullable=True),
                    "sources": {"type": "array", "items": _source_schema, "minItems": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale_md": _string_schema(),
                },
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "stable_key",
                    "concept_key",
                    "statement",
                    "success_criteria_md",
                    "aliases",
                    "cognitive_demand",
                    "sources",
                    "confidence",
                    "rationale_md",
                ],
                "properties": {
                    "stable_key": _string_schema(),
                    "concept_key": _string_schema(),
                    "statement": _string_schema(),
                    "success_criteria_md": _string_schema(),
                    "aliases": {"type": "array", "items": _string_schema()},
                    "cognitive_demand": _string_schema(),
                    "sources": {"type": "array", "items": _source_schema, "minItems": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale_md": _string_schema(),
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "from_key",
                    "to_key",
                    "kind",
                    "external_ref",
                    "confidence",
                    "rationale_md",
                ],
                "properties": {
                    "from_key": _string_schema(),
                    "to_key": _string_schema(nullable=True),
                    "kind": _string_schema(),
                    "external_ref": _string_schema(nullable=True),
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale_md": _string_schema(),
                },
            },
        },
    },
}

CONCEPT_PRACTICE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "claim_id",
            "stem_md",
            "choices",
            "correct_index",
            "explanation_md",
            "task_type",
            "cognitive_demand",
            "difficulty_band",
            "mapping_confidence",
            "source_ref",
        ],
        "properties": {
            "claim_id": _string_schema(),
            "stem_md": _string_schema(),
            "choices": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": _string_schema(),
            },
            "correct_index": {"type": "integer", "minimum": 0, "maximum": 3},
            "explanation_md": _string_schema(),
            "task_type": _string_schema(),
            "cognitive_demand": _string_schema(),
            "difficulty_band": _string_schema(),
            "mapping_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source_ref": _string_schema(),
        },
    },
}
