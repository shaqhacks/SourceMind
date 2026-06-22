from pathlib import Path

from SourceMind.backend.services.md_store import (
    Competency,
    Lesson,
    LessonState,
    MarkdownSubjectStore,
    Misconception,
    Quote,
    RetrievalCheck,
    SRSData,
    SubjectDocument,
    SubjectFrontmatter,
    TransferTask,
    WorkedExample,
)


def test_subject_round_trip(tmp_path: Path) -> None:
    store = MarkdownSubjectStore(tmp_path)
    document = SubjectDocument(
        subject_id="fluid_intelligence",
        frontmatter=SubjectFrontmatter(
            current_level=1,
            total_mastery=42,
            audio_overview_url="https://example.com/audio",
            understanding_percentages={"foundation": 80, "transfer": 20},
        ),
        competencies=[
            Competency(
                id="C1",
                name="Working Memory",
                level=1,
                dependencies=[],
                mastery_percent=80,
            ),
            Competency(
                id="C2",
                name="Transfer Application",
                level=2,
                dependencies=["C1"],
                mastery_percent=20,
            ),
        ],
        quotes=[
            Quote(
                text="Fluid intelligence | supports novel problem solving.",
                source_ref="p. 12",
                competency_id="C1",
                level_id=1,
            )
        ],
        lesson_model=[
            Lesson(
                id="LESSON_C1",
                title="Working Memory",
                competency_id="C1",
                objective="Recall the source-grounded foundation.",
                reading=[
                    "This lesson teaches Working Memory from the source quote.",
                    "Explain it in your own words before transfer.",
                ],
                source_quote_ids=["C1:p. 12"],
                worked_example_ids=["WE_C1_1"],
                retrieval_check_ids=["RC_C1_1"],
                misconception_ids=["MIS_C1_1"],
                transfer_task_ids=[],
            )
        ],
        worked_examples=[
            WorkedExample(
                id="WE_C1_1",
                competency_id="C1",
                prompt="Worked example for Working Memory",
                steps=["Read the quote.", "Explain it simply."],
                source_quote_ids=["C1:p. 12"],
            )
        ],
        retrieval_checks=[
            RetrievalCheck(
                id="RC_C1_1",
                competency_id="C1",
                question="What is the source idea?",
                expected_answer="Fluid intelligence | supports novel problem solving.",
            )
        ],
        misconceptions=[
            Misconception(
                id="MIS_C1_1",
                competency_id="C1",
                trap="Treating a summary as the source.",
                correction="Return to the quote.",
                source_quote_ids=["C1:p. 12"],
            )
        ],
        transfer_tasks=[
            TransferTask(
                id="TT_C2_1",
                competency_id="C2",
                prompt="Apply the idea to a new scenario.",
                prerequisite_ids=["C1"],
                locked=True,
            )
        ],
        lesson_state={"LESSON_C1": LessonState(completed_check_ids=["RC_C1_1"])},
        srs_data={"C1": SRSData(ease=2.6, interval=3, last_score=90, confidence_history=[4, 5])},
        dependencies_notes="- C2 requires C1.",
        lessons="### Remember\nRecall the quote.",
    )

    path = store.save(document)
    loaded = store.load("fluid_intelligence")

    assert path.exists()
    assert loaded.frontmatter.total_mastery == 42
    assert loaded.competencies[1].dependencies == ["C1"]
    assert loaded.quotes[0].text == "Fluid intelligence | supports novel problem solving."
    assert loaded.quotes[0].source_ref == "p. 12"
    assert loaded.lesson_model[0].id == "LESSON_C1"
    assert loaded.lesson_model[0].reading == [
        "This lesson teaches Working Memory from the source quote.",
        "Explain it in your own words before transfer.",
    ]
    assert loaded.worked_examples[0].steps == ["Read the quote.", "Explain it simply."]
    assert loaded.retrieval_checks[0].difficulty == "easy"
    assert loaded.misconceptions[0].trap.startswith("Treating")
    assert loaded.transfer_tasks[0].locked is True
    assert loaded.lesson_state["LESSON_C1"].completed_check_ids == ["RC_C1_1"]
    assert loaded.srs_data["C1"].confidence_history == [4, 5]
    assert "requires C1" in loaded.dependencies_notes
    assert "Remember" in loaded.lessons


def test_load_prompt_style_markdown(tmp_path: Path) -> None:
    (tmp_path / "psychometrics.md").write_text(
        """---
current_level: 1
total_mastery: 75
audio_overview_url:
understanding_percentages:
  foundation: 90
  transfer: 60
---

## COMPETENCY_MAP:
| ID | Name | Level | Dependencies | Mastery % |
| --- | --- | ---: | --- | ---: |
| Q1 | Verbatim Recall | 1 | - | 85% |
| T1 | Scenario Transfer | 2 | Q1 | 65% |

## QUOTES:
| Verbatim Text | Source Page/Ref | Competency ID | Level ID |
| --- | --- | --- | ---: |
| Evidence should be grounded in source material. | ch. 1 | Q1 | 1 |

## srs_data:
Q1:
  ease: 2.5
  interval: 2
  last_score: 80
  confidence_history: [5, 3]
""",
        encoding="utf-8",
    )

    loaded = MarkdownSubjectStore(tmp_path).load("psychometrics")

    assert loaded.subject_id == "psychometrics"
    assert loaded.competencies[0].mastery_percent == 85
    assert loaded.quotes[0].competency_id == "Q1"
    assert loaded.srs_data["Q1"].interval == 2


def test_garbled_numeric_cells_do_not_make_subject_unloadable(tmp_path: Path) -> None:
    # A hand-edited/garbled Level or Mastery cell must not crash load() (which
    # would make the subject permanently unloadable). It degrades gracefully.
    (tmp_path / "broken.md").write_text(
        "---\ncurrent_level: 1\ntotal_mastery: 0\n---\n\n"
        "## COMPETENCY_MAP:\n"
        "| ID | Name | Level | Dependencies | Mastery % | UID |\n"
        "| --- | --- | ---: | --- | ---: | --- |\n"
        "| C1 | Integers | not-a-number | - | oops% | uid-1 |\n"
        "\n## SRS_DATA:\n```yaml\nC1:\n  interval: 2\n",  # truncated (missing closing fence)
        encoding="utf-8",
    )

    loaded = MarkdownSubjectStore(tmp_path).load("broken")

    assert loaded.competencies[0].id == "C1"
    assert loaded.competencies[0].level == 1  # defaulted
    assert loaded.competencies[0].mastery_percent == 0  # defaulted
    assert loaded.srs_data["C1"].interval == 2  # partial fence still parsed


def test_uid_with_pipe_round_trips(tmp_path: Path) -> None:
    store = MarkdownSubjectStore(tmp_path)
    store.save(
        SubjectDocument(
            subject_id="piped_uid",
            competencies=[Competency(id="C1", name="Integers", level=1, dependencies=[], mastery_percent=50, uid="a|b")],
        )
    )
    loaded = store.load("piped_uid")
    assert loaded.competencies[0].uid == "a|b"
    assert loaded.competencies[0].mastery_percent == 50
