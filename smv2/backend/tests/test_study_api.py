from __future__ import annotations

import uuid
from datetime import timedelta

from app.db.engine import get_session
from app.db.models import (
    Card,
    Concept,
    ConceptRevision,
    ConceptSourceLink,
    Course,
    CurriculumVersion,
    EvidenceItem,
    EvidenceItemConceptLink,
    LearnerConceptState,
    LearningClaim,
    LearningClaimRevision,
    PracticeQuestion,
    ReviewState,
    Section,
    utcnow,
)
from app.services import learner_context


LEARNER_ID = "20000000-0000-0000-0000-000000000001"


def _seed_mixed_queue(session):
    course = Course(title="Mixed study", status="ready")
    session.add(course)
    session.flush()
    section = Section(
        id=f"section-{uuid.uuid4()}",
        course_id=course.id,
        order_index=0,
        title="Ratios",
        body_md="A ratio compares quantities.",
        content_hash="ratios-source",
    )
    concept = Concept(course_id=course.id, slug="ratios", label="Ratios")
    version = CurriculumVersion(course_id=course.id, status="published", is_current=True)
    session.add_all([section, concept, version])
    session.flush()
    claim = LearningClaim(course_id=course.id, concept_id=concept.id, stable_key="use-ratios")
    session.add(claim)
    session.flush()
    session.add_all(
        [
            ConceptRevision(
                curriculum_version_id=version.id,
                concept_id=concept.id,
                label="Ratios",
                description_md="Use ratios.",
                aliases=[],
                review_state="verified",
            ),
            LearningClaimRevision(
                curriculum_version_id=version.id,
                learning_claim_id=claim.id,
                concept_id=concept.id,
                statement="Use a ratio.",
                success_criteria_md="Chooses the matching ratio.",
                aliases=[],
                review_state="verified",
            ),
            ConceptSourceLink(
                course_id=course.id,
                curriculum_version_id=version.id,
                concept_id=concept.id,
                learning_claim_id=claim.id,
                section_id=section.id,
                source_ref="Ratios p. 1",
                source_content_hash=section.content_hash,
                review_state="verified",
            ),
        ]
    )
    profile = learner_context.ensure_course_learning_profile(session, LEARNER_ID, course.id)
    state = LearnerConceptState(
        course_id=course.id,
        course_learning_profile_id=profile.id,
        curriculum_version_id=version.id,
        concept_id=concept.id,
        state_scope="concept",
        state_key=f"concept:{concept.id}",
        readiness_estimate=0.3,
        lower_bound=0.15,
        upper_bound=0.45,
        uncertainty=0.3,
        effective_evidence_count=4,
        distinct_item_count=4,
        distinct_session_count=3,
        trend="declining",
        status="likely_struggling",
        forgetting_risk=0.4,
        calculated_through=utcnow(),
        model_version="transparent-beta-v1",
    )
    card = Card(
        id=f"card-{uuid.uuid4()}",
        course_id=course.id,
        section_id=section.id,
        front_md="What is a ratio?",
        back_md="A comparison of quantities.",
        position=0,
    )
    question = PracticeQuestion(
        course_id=course.id,
        section_id=section.id,
        concept_id=concept.id,
        problem_number="adaptive-1",
        source_ref="Ratios p. 1",
        stem_md="Which ratio compares 2 to 3?",
        choices=["2:3", "3:2"],
        correct_index=0,
        explanation_md="2:3 compares 2 to 3.",
        source_fingerprint=f"adaptive-{uuid.uuid4()}",
        extraction_version="concept-practice-v1",
        confidence=1,
    )
    session.add_all([state, card, question])
    session.flush()
    session.add(
        ReviewState(
            course_learning_profile_id=profile.id,
            card_id=card.id,
            course_id=course.id,
            due_at=utcnow() - timedelta(days=1),
            interval_days=1,
            ease=2.5,
            reps=1,
            lapses=0,
        )
    )
    for item_type, source_id, content in (
        ("flashcard", card.id, {"front": card.front_md, "back": card.back_md}),
        (
            "practice_question",
            question.id,
            {"stem_md": question.stem_md, "choices": question.choices},
        ),
    ):
        item = EvidenceItem(
            course_id=course.id,
            item_type=item_type,
            source_record_id=source_id,
            source_index=-1,
            content_json=content,
            content_fingerprint=f"{item_type}-{source_id}",
            mapping_status="mapped",
        )
        session.add(item)
        session.flush()
        session.add(
            EvidenceItemConceptLink(
                course_id=course.id,
                evidence_item_id=item.id,
                curriculum_version_id=version.id,
                learning_claim_id=claim.id,
                role="primary",
                task_type="recall" if item_type == "flashcard" else "multiple_choice",
                review_state="verified",
            )
        )
    session.commit()
    return course.id, concept.id


def test_mixed_study_queue_is_concept_grounded_and_does_not_call_llm(client, monkeypatch):
    session = get_session()
    try:
        course_id, concept_id = _seed_mixed_queue(session)
    finally:
        session.close()
    client.cookies.set(learner_context.LEARNER_COOKIE, LEARNER_ID)

    def fail_provider():
        raise AssertionError("study queue must not call an LLM")

    monkeypatch.setattr("app.llm.provider.get_provider", fail_provider)
    response = client.get(f"/api/courses/{course_id}/study/queue")

    assert response.status_code == 200
    body = response.json()
    assert {activity["activity_type"] for activity in body["activities"]} == {
        "flashcard",
        "question",
    }
    assert {activity["concept_id"] for activity in body["activities"]} == {concept_id}
    assert all(activity["reason"] == "targeted_remediation" for activity in body["activities"])
    question = next(item for item in body["activities"] if item["activity_type"] == "question")
    assert "correct_index" not in question["payload"]
    assert "explanation_md" not in question["payload"]


def test_mixed_study_queue_returns_empty_for_course_without_items(client):
    response = client.post("/api/courses", json={"title": "Empty study"})
    course_id = response.json()["id"]

    queue = client.get(f"/api/courses/{course_id}/study/queue")

    assert queue.status_code == 200
    assert queue.json() == {"activities": []}


def test_mixed_study_queue_404s_for_unknown_course(client):
    assert client.get("/api/courses/missing/study/queue").status_code == 404
