from SourceMind.backend.services.llm_local import LocalLLMService
from SourceMind.backend.services.notebooklm_service import NotebookAnalysis, NotebookCompetency, NotebookQuote


def test_notebook_analysis_builds_subject_with_durable_lesson_model() -> None:
    analysis = NotebookAnalysis(
        competencies=[
            NotebookCompetency(id="L1_A", name="Foundation A", level=1),
            NotebookCompetency(id="L2_A", name="Transfer A", level=2, dependencies=["L1_A"]),
        ],
        quotes=[
            NotebookQuote(text="Foundation A comes first.", source_ref="p. 1", competency_id="L1_A", level_id=1),
            NotebookQuote(text="Transfer A applies the foundation.", source_ref="p. 2", competency_id="L2_A", level_id=2),
        ],
        raw={"fallback": True},
    )

    document = LocalLLMService().build_subject_from_notebook_analysis("generated", analysis)

    assert len(document.lesson_model) == 2
    assert len(document.retrieval_checks) == 6
    assert len(document.worked_examples) == 2
    assert document.transfer_tasks[0].prerequisite_ids == ["L1_A"]


def test_notebook_analysis_filters_boilerplate_before_lesson_build() -> None:
    analysis = NotebookAnalysis(
        competencies=[NotebookCompetency(id="L1_A", name="Algebra Equation Concepts", level=1)],
        quotes=[
            NotebookQuote(
                text="Beginning and Intermediate Algebra available for free download at http://wallace.ccfaculty.org/book/book.html",
                source_ref="p. 1",
                competency_id="L1_A",
                level_id=1,
            ),
            NotebookQuote(
                text="An equation is a mathematical statement that two expressions are equal.",
                source_ref="p. 8",
                competency_id="L1_A",
                level_id=1,
            ),
        ],
    )

    document = LocalLLMService().build_subject_from_notebook_analysis("generated", analysis)

    assert [quote.text for quote in document.quotes] == [
        "An equation is a mathematical statement that two expressions are equal."
    ]
    assert document.lesson_model[0].reading
    assert "An equation is a mathematical statement" in document.lesson_model[0].reading[0]
