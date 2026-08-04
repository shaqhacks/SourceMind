from __future__ import annotations

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptRevision,
    Course,
    CurriculumVersion,
    LearnerConceptState,
)
from app.services import learner_context
from app.services.diagnostic_validation_service import agreement_summary, cohens_kappa


def _seed_validation_case(course_id: str, learner_id: str) -> tuple[str, str]:
    session = get_session()
    try:
        course = session.get(Course, course_id)
        assert course is not None
        profile = learner_context.ensure_course_learning_profile(session, learner_id, course_id)
        version = CurriculumVersion(
            course_id=course_id,
            status="published",
            is_current=True,
            label="Reviewed curriculum",
        )
        concept = Concept(course_id=course_id, slug="fractions", label="Fractions")
        session.add_all([version, concept])
        session.flush()
        session.add(
            ConceptRevision(
                curriculum_version_id=version.id,
                concept_id=concept.id,
                label="Fractions",
                description_md="Represent and compare fractions.",
                aliases=[],
                review_state="verified",
            )
        )
        session.add(
            LearnerConceptState(
                course_id=course_id,
                course_learning_profile_id=profile.id,
                curriculum_version_id=version.id,
                concept_id=concept.id,
                learning_claim_id=None,
                state_scope="concept",
                state_key=f"concept:{concept.id}",
                readiness_estimate=0.28,
                quiz_estimate=0.2,
                review_estimate=0.4,
                lower_bound=0.12,
                upper_bound=0.44,
                uncertainty=0.32,
                effective_evidence_count=5.0,
                distinct_item_count=5,
                distinct_session_count=3,
                trend="declining",
                status="likely_struggling",
                forgetting_risk=0.25,
                calculated_through=version.created_at,
                model_version="transparent-beta-v1",
            )
        )
        session.commit()
        return concept.id, version.id
    finally:
        session.close()


def test_blinded_validation_does_not_reveal_model_until_judgment(client):
    course_id = client.post("/api/courses", json={"title": "Math"}).json()["id"]
    learner_id = learner_context.LEGACY_LOCAL_LEARNER_ID
    client.cookies.set(learner_context.LEARNER_COOKIE, learner_id)
    concept_id, _ = _seed_validation_case(course_id, learner_id)

    blind = client.get(f"/api/courses/{course_id}/diagnostics/validation/next")
    assert blind.status_code == 200
    assert blind.json()["concept_id"] == concept_id
    assert "model_state" not in blind.json()
    assert "readiness_estimate" not in blind.json()

    judged = client.post(
        f"/api/courses/{course_id}/diagnostics/validation/judgments",
        json={"concept_id": concept_id, "judgment": "likely_struggling"},
    )
    assert judged.status_code == 201
    assert judged.json()["model_state"] == "likely_struggling"
    assert judged.json()["agreement"] is True


def test_disagreement_requires_a_reason_after_the_blinded_reveal(client):
    course_id = client.post("/api/courses", json={"title": "Math"}).json()["id"]
    learner_id = learner_context.LEGACY_LOCAL_LEARNER_ID
    client.cookies.set(learner_context.LEARNER_COOKIE, learner_id)
    concept_id, _ = _seed_validation_case(course_id, learner_id)

    response = client.post(
        f"/api/courses/{course_id}/diagnostics/validation/judgments",
        json={"concept_id": concept_id, "judgment": "not_struggling"},
    )
    assert response.status_code == 201
    assert response.json()["agreement"] is False
    assert response.json()["requires_disagreement_reason"] is True

    completed = client.patch(
        f"/api/courses/{course_id}/diagnostics/validation/judgments/{response.json()['id']}/reason",
        json={"disagreement_reason": "item_mapping"},
    )
    assert completed.status_code == 200
    assert completed.json()["disagreement_reason"] == "item_mapping"
    assert completed.json()["requires_disagreement_reason"] is False


def test_agreement_metrics_report_small_samples_and_chance_adjustment():
    pairs = [
        ("likely_struggling", "likely_struggling"),
        ("not_struggling", "not_struggling"),
        ("likely_struggling", "not_struggling"),
        ("not_struggling", "likely_struggling"),
    ]
    summary = agreement_summary(pairs, minimum_sample=10)

    assert summary["raw_agreement"] == 0.5
    assert summary["chance_adjusted_agreement"] == cohens_kappa(pairs)
    assert summary["sufficient_sample"] is False
