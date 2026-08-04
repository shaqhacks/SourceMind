from __future__ import annotations

import uuid
from datetime import datetime, timezone

from conftest import _course_profile_id

from app.db.engine import get_session
from app.db.models import (
    Asset,
    Card,
    ChatTurn,
    Chunk,
    Concept,
    ConceptEdge,
    ConceptMastery,
    ConceptMasteryEvent,
    ConceptRelation,
    ConceptRevision,
    ConceptSectionLink,
    ConceptSourceLink,
    Course,
    CurriculumVersion,
    EvidenceItem,
    EvidenceItemConceptLink,
    Highlight,
    LlmCall,
    LearningClaim,
    LearningClaimRevision,
    LearnerConceptState,
    LearnerEvidenceEvent,
    Note,
    PracticeAnswer,
    PracticeExtractionRun,
    PracticeQuestion,
    ProgressState,
    ReviewLog,
    ReviewState,
    Section,
    ShadowLearnerPrediction,
    Test,
    TestAttempt,
)
from app.services.courses_service import delete_course


def test_delete_course_cascades_to_every_fk_bearing_table(client):
    session = get_session()
    try:
        course = Course(id=str(uuid.uuid4()), title="Cascade Course", status="created")
        session.add(course)
        session.flush()
        course_profile_id = _course_profile_id(session, course.id)

        section = Section(
            id="section-cascade-1",
            course_id=course.id,
            order_index=0,
            title="Intro",
            body_md="Body text.",
            content_hash="hash1",
        )
        session.add(section)
        session.flush()

        asset = Asset(
            id=str(uuid.uuid4()),
            course_id=course.id,
            filename="a.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256="x",
            stored_path="/tmp/a.pdf",
            status="stored",
        )
        chunk = Chunk(
            id=str(uuid.uuid4()),
            course_id=course.id,
            section_id=section.id,
            chunk_index=0,
            text="chunk text",
            source_ref=f"{section.id}:p.1",
        )
        card = Card(
            id="card-cascade-1",
            course_id=course.id,
            section_id=section.id,
            front_md="Q",
            back_md="A",
            position=0,
        )
        session.add_all([asset, chunk, card])
        session.flush()

        review_state = ReviewState(
            course_learning_profile_id=course_profile_id,
            card_id=card.id,
            course_id=course.id,
            due_at=datetime.now(timezone.utc),
            interval_days=1.0,
            ease=2.5,
            reps=0,
            lapses=0,
        )
        review_log = ReviewLog(
            id=str(uuid.uuid4()),
            course_learning_profile_id=course_profile_id,
            card_id=card.id,
            course_id=course.id,
            graded_at=datetime.now(timezone.utc),
            grade=3,
        )
        progress = ProgressState(course_id=course.id, section_id=section.id, scroll_pos=0.5)
        chat_turn = ChatTurn(id=str(uuid.uuid4()), course_id=course.id, role="user", content="hi")
        test = Test(
            id=str(uuid.uuid4()), course_id=course.id, section_id=section.id, questions=[{"q": 1}]
        )
        test_attempt = TestAttempt(
            id=str(uuid.uuid4()),
            test_id=test.id,
            course_id=course.id,
            course_learning_profile_id=course_profile_id,
        )
        note = Note(
            course_id=course.id,
            section_id=section.id,
            surface="pdf",
            page=0,
            anchor_y=0.5,
            note_md="cascade note",
        )
        concept = Concept(
            course_id=course.id,
            slug="cascade.concept",
            label="Cascade Concept",
            section_id=section.id,
        )
        concept_2 = Concept(
            course_id=course.id,
            slug="cascade.concept-2",
            label="Cascade Concept 2",
            section_id=section.id,
        )
        session.add_all([concept, concept_2])
        session.flush()
        curriculum_version = CurriculumVersion(
            course_id=course.id,
            status="published",
            is_current=True,
        )
        session.add(curriculum_version)
        session.flush()
        concept_revision = ConceptRevision(
            curriculum_version_id=curriculum_version.id,
            concept_id=concept.id,
            label=concept.label,
            description_md="Cascade description",
            aliases=[],
        )
        learning_claim = LearningClaim(
            course_id=course.id,
            concept_id=concept.id,
            stable_key="cascade-claim",
        )
        session.add_all([concept_revision, learning_claim])
        session.flush()
        learning_claim_revision = LearningClaimRevision(
            curriculum_version_id=curriculum_version.id,
            learning_claim_id=learning_claim.id,
            concept_id=concept.id,
            statement="Demonstrate the cascade claim.",
            success_criteria_md="Succeeds.",
            aliases=[],
        )
        evidence_item = EvidenceItem(
            course_id=course.id,
            item_type="practice_question",
            source_record_id="cascade-evidence-source",
            source_index=0,
            content_json={"stem_md": "2 + 2?"},
            content_fingerprint="cascade-evidence-fingerprint",
            mapping_status="mapped",
        )
        session.add(evidence_item)
        session.flush()
        evidence_mapping = EvidenceItemConceptLink(
            course_id=course.id,
            evidence_item_id=evidence_item.id,
            curriculum_version_id=curriculum_version.id,
            learning_claim_id=learning_claim.id,
            role="primary",
            task_type="multiple_choice",
            review_state="verified",
        )
        session.add(evidence_mapping)
        session.flush()
        learner_evidence_event = LearnerEvidenceEvent(
            course_id=course.id,
            course_learning_profile_id=course_profile_id,
            evidence_item_id=evidence_item.id,
            evidence_mapping_id=evidence_mapping.id,
            learning_claim_id=learning_claim.id,
            curriculum_version_id=curriculum_version.id,
            channel="practice",
            normalized_outcome=1.0,
            raw_result={"correct": True},
            source_event_key="cascade-evidence-event",
        )
        learner_concept_state = LearnerConceptState(
            course_id=course.id,
            course_learning_profile_id=course_profile_id,
            curriculum_version_id=curriculum_version.id,
            concept_id=concept.id,
            learning_claim_id=learning_claim.id,
            state_scope="claim",
            state_key=f"claim:{learning_claim.id}",
            readiness_estimate=0.5,
            lower_bound=0.2,
            upper_bound=0.8,
            uncertainty=0.6,
            effective_evidence_count=1.0,
            distinct_item_count=1,
            distinct_session_count=1,
            trend="unknown",
            status="insufficient_evidence",
            forgetting_risk=0.0,
            calculated_through=datetime.now(timezone.utc),
            model_version="transparent-beta-v1",
        )
        shadow_prediction = ShadowLearnerPrediction(
            course_id=course.id,
            course_learning_profile_id=course_profile_id,
            curriculum_version_id=curriculum_version.id,
            learning_claim_id=learning_claim.id,
            model_name="bkt",
            model_version="bkt-v1",
            status="insufficient_data",
            evidence_snapshot_hash="cascade-shadow-snapshot",
            training_cutoff=datetime.now(timezone.utc),
            feature_schema_version="learner-evidence-v1",
            prediction_horizon="next_representative_item",
            target_definition="correctness",
            config_json={},
        )
        concept_relation = ConceptRelation(
            course_id=course.id,
            curriculum_version_id=curriculum_version.id,
            from_concept_id=concept.id,
            to_concept_id=concept_2.id,
            kind="requires",
        )
        concept_source_link = ConceptSourceLink(
            course_id=course.id,
            curriculum_version_id=curriculum_version.id,
            concept_id=concept.id,
            learning_claim_id=learning_claim.id,
            section_id=section.id,
            source_ref="Intro",
            source_content_hash=section.content_hash,
        )
        concept_edge = ConceptEdge(
            course_id=course.id,
            from_concept_id=concept.id,
            to_concept_id=concept_2.id,
        )
        concept_section_link = ConceptSectionLink(
            course_id=course.id,
            concept_id=concept.id,
            section_id=section.id,
        )
        highlight = Highlight(
            course_id=course.id,
            section_id=section.id,
            exact="cascade highlight",
        )
        session.add_all(
            [
                learning_claim_revision,
                concept_relation,
                concept_source_link,
                concept_edge,
                concept_section_link,
                highlight,
                learner_evidence_event,
                learner_concept_state,
                shadow_prediction,
            ]
        )
        session.flush()
        practice_question = PracticeQuestion(
            course_id=course.id,
            section_id=section.id,
            concept_id=concept.id,
            problem_number="1",
            source_ref="Practice #1",
            stem_md="2 + 2?",
            choices=["3", "4"],
            correct_index=1,
            explanation_md="2 + 2 = 4.",
            source_fingerprint="cascade-practice-question",
            extraction_version="test",
            confidence=1.0,
        )
        extraction_run = PracticeExtractionRun(
            course_id=course.id,
            section_id=section.id,
            input_fingerprint="cascade-practice-run",
            question_count=1,
        )
        session.add_all([practice_question, extraction_run])
        session.flush()
        practice_answer = PracticeAnswer(
            course_id=course.id,
            question_id=practice_question.id,
            learner_key="learner",
            selected_index=1,
            correct=True,
            points_delta=1,
        )
        mastery = ConceptMastery(
            course_id=course.id,
            concept_id=concept.id,
            learner_key="learner",
            points=1,
            correct_count=1,
            wrong_count=0,
        )
        session.add_all([practice_answer, mastery])
        session.flush()
        mastery_event = ConceptMasteryEvent(
            course_id=course.id,
            concept_id=concept.id,
            question_id=practice_question.id,
            practice_answer_id=practice_answer.id,
            learner_key="learner",
            delta=1,
        )
        llm_call = LlmCall(
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            purpose="lesson",
            model="test-model",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            status="ok",
            course_id=course.id,
        )
        session.add_all(
            [
                review_state,
                review_log,
                progress,
                chat_turn,
                test,
                test_attempt,
                note,
                mastery_event,
                llm_call,
            ]
        )
        session.commit()

        course_id = course.id
        llm_call_id = llm_call.id
    finally:
        session.close()

    deleted = delete_course(course_id)
    assert deleted is True

    session = get_session()
    try:
        assert session.get(Course, course_id) is None
        assert session.query(Section).filter_by(course_id=course_id).count() == 0
        assert session.query(Asset).filter_by(course_id=course_id).count() == 0
        assert session.query(Chunk).filter_by(course_id=course_id).count() == 0
        assert session.query(Card).filter_by(course_id=course_id).count() == 0
        assert session.query(ReviewState).filter_by(course_id=course_id).count() == 0
        assert session.query(ReviewLog).filter_by(course_id=course_id).count() == 0
        assert session.query(ProgressState).filter_by(course_id=course_id).count() == 0
        assert session.query(ChatTurn).filter_by(course_id=course_id).count() == 0
        assert session.query(Test).filter_by(course_id=course_id).count() == 0
        assert session.query(TestAttempt).filter_by(course_id=course_id).count() == 0
        assert session.query(Note).filter_by(course_id=course_id).count() == 0
        assert session.query(Highlight).filter_by(course_id=course_id).count() == 0
        assert session.query(Concept).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptEdge).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptSectionLink).filter_by(course_id=course_id).count() == 0
        assert session.query(CurriculumVersion).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptRevision).filter_by(concept_id=concept.id).count() == 0
        assert session.query(LearningClaim).filter_by(course_id=course_id).count() == 0
        assert (
            session.query(LearningClaimRevision)
            .filter_by(learning_claim_id=learning_claim.id)
            .count()
            == 0
        )
        assert session.query(ConceptRelation).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptSourceLink).filter_by(course_id=course_id).count() == 0
        assert session.query(EvidenceItem).filter_by(course_id=course_id).count() == 0
        assert session.query(EvidenceItemConceptLink).filter_by(course_id=course_id).count() == 0
        assert session.query(LearnerEvidenceEvent).filter_by(course_id=course_id).count() == 0
        assert session.query(LearnerConceptState).filter_by(course_id=course_id).count() == 0
        assert session.query(ShadowLearnerPrediction).filter_by(course_id=course_id).count() == 0
        assert session.query(PracticeQuestion).filter_by(course_id=course_id).count() == 0
        assert session.query(PracticeExtractionRun).filter_by(course_id=course_id).count() == 0
        assert session.query(PracticeAnswer).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptMastery).filter_by(course_id=course_id).count() == 0
        assert session.query(ConceptMasteryEvent).filter_by(course_id=course_id).count() == 0

        surviving_llm_call = session.get(LlmCall, llm_call_id)
        assert surviving_llm_call is not None
        assert surviving_llm_call.course_id is None
    finally:
        session.close()


def test_delete_course_returns_false_for_missing_course(client):
    assert delete_course("does-not-exist") is False


def test_delete_course_removes_asset_files_from_disk(client, ingest_course):
    """DB delete alone doesn't touch the filesystem — the uploaded PDFs
    under data_dir()/assets/{course_id} used to be left behind forever.
    """
    from app.config import data_dir

    course_id, *_ = ingest_course("with_bookmarks.pdf")

    assets_dir = data_dir() / "assets" / course_id
    assert assets_dir.exists()
    assert any(assets_dir.iterdir())

    resp = client.delete(f"/api/courses/{course_id}")
    assert resp.status_code == 204
    assert not assets_dir.exists()


def test_delete_course_tolerates_missing_asset_dir(client):
    """A course with no uploaded assets has no assets dir at all — deleting
    it must not raise over a directory that was never created.
    """
    resp = client.post("/api/courses", json={"title": "No Assets"})
    course_id = resp.json()["id"]

    resp = client.delete(f"/api/courses/{course_id}")
    assert resp.status_code == 204
