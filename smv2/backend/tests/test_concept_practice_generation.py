from __future__ import annotations

import json

import pytest

from app.db.engine import get_session
from app.db.models import EvidenceItemConceptLink, Job, PracticeQuestion
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult
from app.llm.structured_output import CONCEPT_PRACTICE_SCHEMA
from app.pipeline.concept_practice_generation import parse_concept_practice
from tests.test_study_api import _seed_mixed_queue


def _generated_question(claim_id: str) -> dict:
    return {
        "claim_id": claim_id,
        "stem_md": "Which ratio compares 4 to 5?",
        "choices": ["4:5", "5:4", "4:9", "9:4"],
        "correct_index": 0,
        "explanation_md": "4:5 compares 4 to 5.",
        "task_type": "multiple_choice",
        "cognitive_demand": "apply",
        "difficulty_band": "practice",
        "mapping_confidence": 0.9,
        "source_ref": "Ratios p. 1",
    }


def test_concept_practice_parser_rejects_invented_claim_ids():
    with pytest.raises(ValueError, match="unknown claim"):
        parse_concept_practice(json.dumps([_generated_question("invented")]), {"allowed"})


def test_concept_practice_schema_contains_required_parser_fields():
    item_required = set(CONCEPT_PRACTICE_SCHEMA["items"]["required"])
    assert {
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
    } <= item_required


def test_concept_practice_job_persists_grounded_deduplicated_pool(
    client, stub_provider
):
    session = get_session()
    try:
        course_id, concept_id = _seed_mixed_queue(session)
        existing_count = session.query(PracticeQuestion).filter_by(course_id=course_id).count()
        claim_id = session.query(EvidenceItemConceptLink.learning_claim_id).first()[0]
    finally:
        session.close()
    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([_generated_question(claim_id)]),
            input_tokens=100,
            output_tokens=50,
            model="stub-model",
        )
    ]

    started = client.post(
        f"/api/courses/{course_id}/study/concepts/{concept_id}/replenish"
    )
    assert started.status_code == 202
    assert run_due_jobs_once() is True

    session = get_session()
    try:
        completed = session.get(Job, started.json()["id"])
        assert completed.status == "succeeded", completed.error
        assert session.query(PracticeQuestion).filter_by(course_id=course_id).count() == existing_count + 1
        generated = session.query(PracticeQuestion).filter_by(
            course_id=course_id,
            extraction_version="concept-practice-v1",
            stem_md="Which ratio compares 4 to 5?",
        ).one()
        mapping = (
            session.query(EvidenceItemConceptLink)
            .filter_by(learning_claim_id=claim_id, task_type="multiple_choice")
            .order_by(EvidenceItemConceptLink.created_at.desc())
            .first()
        )
        assert mapping is not None
        assert mapping.review_state == "unverified"
        assert generated.stem_md == "Which ratio compares 4 to 5?"
    finally:
        session.close()


def test_concept_practice_schema_sent_on_first_and_repair_completion(
    client, stub_provider
):
    session = get_session()
    try:
        course_id, concept_id = _seed_mixed_queue(session)
        claim_id = session.query(EvidenceItemConceptLink.learning_claim_id).first()[0]
    finally:
        session.close()
    stub_provider.responses = [
        CompletionResult(text="not json", input_tokens=1, output_tokens=1, model="stub-model"),
        CompletionResult(
            text=json.dumps([_generated_question(claim_id)]),
            input_tokens=1,
            output_tokens=1,
            model="stub-model",
        ),
    ]

    started = client.post(
        f"/api/courses/{course_id}/study/concepts/{concept_id}/replenish"
    )
    assert started.status_code == 202
    assert run_due_jobs_once() is True

    assert stub_provider.complete_call_count == 2
    assert [option.response_schema for option in stub_provider.received_completion_options] == [
        CONCEPT_PRACTICE_SCHEMA,
        CONCEPT_PRACTICE_SCHEMA,
    ]
    repair_content = stub_provider.received_messages[1][-1]["content"]
    assert "valid JSON" in repair_content
    assert "not json" not in repair_content


def test_replenish_concept_practice_unconfigured_provider_fails_before_job_creation(client):
    session = get_session()
    try:
        course_id, concept_id = _seed_mixed_queue(session)
    finally:
        session.close()

    resp = client.post(f"/api/courses/{course_id}/study/concepts/{concept_id}/replenish")

    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"]["failure_category"] == "missing_credentials"
    assert "ANTHROPIC_API_KEY" in body["detail"]["remediation"]

    session = get_session()
    try:
        assert (
            session.query(Job)
            .filter(Job.type == "concept_practice_generation")
            .count()
            == 0
        )
    finally:
        session.close()
