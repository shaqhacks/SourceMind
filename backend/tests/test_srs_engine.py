from SourceMind.backend.services.llm_local import GroundingScore
from SourceMind.backend.services.md_store import Competency, Quote, SRSData, SubjectDocument
from SourceMind.backend.services.srs_engine import SRSEngine


def subject_document() -> SubjectDocument:
    return SubjectDocument(
        subject_id="transfer",
        competencies=[
            Competency(id="Q1", name="Evidence Recall", level=1, dependencies=[], mastery_percent=79),
            Competency(id="T1", name="Scenario Transfer", level=2, dependencies=["Q1"], mastery_percent=40),
        ],
        quotes=[
            Quote(
                text="Claims should be grounded in source evidence before transfer.",
                source_ref="p. 1",
                competency_id="Q1",
                level_id=1,
            )
        ],
        srs_data={
            "Q1": SRSData(ease=2.5, interval=1, last_score=55, confidence_history=[5], repetitions=1),
            "T1": SRSData(ease=2.5, interval=3, last_score=70, confidence_history=[3], repetitions=1),
        },
    )


def test_mastery_gate_blocks_level_2_until_dependencies_reach_80() -> None:
    document = subject_document()
    session = SRSEngine().build_session(document)

    assert "T1" in session.mastery_gate
    assert session.mastery_gate["T1"] == ["Q1"]
    assert all(item.competency_id != "T1" for item in session.items)

    document.competencies[0].mastery_percent = 80
    open_session = SRSEngine().build_session(document)

    assert "T1" not in open_session.mastery_gate
    assert any(item.competency_id == "T1" for item in open_session.items)


def test_incorrect_but_confident_gets_top_priority_and_immediate_repeat() -> None:
    document = subject_document()
    session = SRSEngine().build_session(document)

    assert session.items[0].competency_id == "Q1"
    assert session.items[0].due_reason.startswith("incorrect_but_confident")

    result = SRSEngine().evaluate(document, "Q1", correct=False, confidence=6)

    assert result.prioritized_for_immediate_repeat is True
    assert result.interval == 0


def test_prediction_risk_halves_failure_penalty() -> None:
    document = subject_document()
    grounding = GroundingScore(grounded_pct=20, inference_pct=30, prediction_pct=50)

    result = SRSEngine().evaluate(document, "Q1", correct=False, confidence=4, grounding=grounding)

    assert result.penalty_halved_for_prediction_risk is True
    assert result.mastery_percent == 72


def test_diagnostic_downshift_after_three_level_2_failures() -> None:
    document = subject_document()
    document.competencies[0].mastery_percent = 85
    engine = SRSEngine()

    first = engine.evaluate(document, "T1", correct=False, confidence=3, level=2)
    second = engine.evaluate(document, "T1", correct=False, confidence=3, level=2)
    third = engine.evaluate(document, "T1", correct=False, confidence=3, level=2)

    assert first.diagnostic_downshift is None
    assert second.diagnostic_downshift is None
    assert third.diagnostic_downshift is not None
    assert third.diagnostic_downshift["prerequisite_id"] == "Q1"


def test_study_session_does_not_prompt_from_pdf_boilerplate() -> None:
    document = SubjectDocument(
        subject_id="bad_quote",
        competencies=[Competency(id="Q1", name="Evidence Recall", level=1, dependencies=[], mastery_percent=0)],
        quotes=[
            Quote(
                text="Beginning and Intermediate Algebra available for free download at http://wallace.ccfaculty.org/book/book.html",
                source_ref="p. 1",
                competency_id="Q1",
                level_id=1,
            )
        ],
    )

    session = SRSEngine().build_session(document)

    assert session.items[0].quote is None
    assert session.items[0].prompt == "Recall the foundational idea for Evidence Recall."
