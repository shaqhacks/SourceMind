import threading

import pytest

from SourceMind.backend.services import course_engine as course_engine_module
from SourceMind.backend.services.course_engine import CompetencyTree, CourseEngine, ExtractedPage
from SourceMind.backend.services.course_models import (
    AdaptiveSuggestion,
    Chapter,
    CourseDocument,
    CourseStatus,
    LessonBlock,
    Misconception,
    SectionLesson,
    SourceFile,
    SourceSpan,
    SupportStatus,
    TransferTask,
)
from SourceMind.backend.services.course_store import CourseStore


def test_course_store_round_trip_markdown_json(tmp_path):
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[SourceFile(id="SRC_1", filename="algebra.pdf", order=0)],
        chapters=[],
    )
    store = CourseStore(tmp_path)

    store.save(course)
    loaded = store.load("algebra")

    assert loaded.course_id == "algebra"
    assert loaded.title == "Algebra"
    assert "COURSE_JSON" in store.course_path("algebra").read_text(encoding="utf-8")


def test_course_document_defaults_new_learning_path_metadata_for_legacy_payload():
    loaded = CourseDocument.model_validate(
        {
            "schema_version": 1,
            "course_id": "legacy_algebra",
            "title": "Legacy Algebra",
            "source_files": [],
            "competencies": [],
            "chapters": [],
            "generation": {},
        }
    )

    assert loaded.schema_version == 1
    assert loaded.source_bundle_type == "structured_course"
    assert loaded.organization_policy == "preserve_source_spine"


def test_course_store_round_trip_preserves_learning_path_metadata(tmp_path):
    course = CourseDocument(
        course_id="learning_path",
        title="Learning Path",
        source_bundle_type="mixed",
        organization_policy="reorganize_learning_path",
        chapters=[
            Chapter(
                id="CH_1",
                number="1",
                title="Foundations",
                order=0,
                sections=[
                    SectionLesson(
                        id="SEC_1",
                        chapter_id="CH_1",
                        number="1.1",
                        title="Integers",
                        order=0,
                        lesson_blocks=[
                            LessonBlock(
                                id="LB_1",
                                kind="background",
                                title="Context",
                                body="Helpful prerequisite context",
                                support_status=SupportStatus.course_inference,
                            )
                        ],
                        misconceptions=[
                            Misconception(
                                id="MIS_1",
                                title="Sign confusion",
                                trap="Treating negative signs as subtraction in every context.",
                                correction="Separate unary sign from subtraction operation.",
                                concept_ids=["CON_1"],
                                source_refs=["p. 1"],
                            )
                        ],
                        transfer_tasks=[
                            TransferTask(
                                id="TT_1",
                                title="Apply the rule",
                                prompt="Classify signs in a new expression.",
                                concept_ids=["CON_1"],
                                prerequisite_ids=["CON_0"],
                                source_refs=["p. 2"],
                            )
                        ],
                        adaptive_suggestions=[
                            AdaptiveSuggestion(
                                id="AS_1",
                                kind="worked_example",
                                title="Revisit worked example",
                                body="Review the integer-sign example before retrying.",
                                concept_ids=["CON_1"],
                                source_refs=["p. 1"],
                                priority=0.8,
                            )
                        ],
                    )
                ],
            )
        ],
    )
    store = CourseStore(tmp_path)

    store.save(course)
    loaded = store.load("learning_path")

    assert loaded.schema_version == 2
    assert loaded.source_bundle_type == "mixed"
    assert loaded.organization_policy == "reorganize_learning_path"
    section = loaded.chapters[0].sections[0]
    assert section.lesson_blocks[0].support_status == "course_inference"
    assert section.misconceptions[0].title == "Sign confusion"
    assert section.transfer_tasks[0].prerequisite_ids == ["CON_0"]
    assert section.adaptive_suggestions[0].kind == "worked_example"


def test_course_store_save_keeps_existing_file_readable_until_atomic_replace(tmp_path):
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[SourceFile(id="SRC_1", filename="algebra.pdf", order=0)],
        chapters=[],
    )
    store = CourseStore(tmp_path)
    store.save(course)

    started = threading.Event()
    finish_replace = threading.Event()
    original_write = store._write_text_atomic

    def delayed_atomic_write(path, content):
        tmp_path = path.with_name(f".{path.name}.pending")
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(content)
        started.set()
        assert finish_replace.wait(timeout=2), "timed out waiting to complete atomic replace"
        tmp_path.replace(path)

    store._write_text_atomic = delayed_atomic_write

    updated_course = store.load("algebra")
    updated_course.title = "Algebra II"

    save_thread = threading.Thread(target=store.save, args=(updated_course,))
    save_thread.start()
    assert started.wait(timeout=2), "timed out waiting for delayed save to stage new content"

    loaded_during_save = store.load("algebra")
    assert loaded_during_save.title == "Algebra"

    finish_replace.set()
    save_thread.join(timeout=2)
    assert not save_thread.is_alive(), "timed out waiting for save thread to finish"

    store._write_text_atomic = original_write
    assert store.load("algebra").title == "Algebra II"


def test_detect_outline_preserves_chapter_and_section_order():
    engine = CourseEngine()
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    pages = [
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=8,
            text="Chapter 0: Pre-Algebra\n0.1 Integers\nIntegers are positive and negative whole numbers.",
        ),
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=12,
            text="0.2 Fractions\nA fraction represents part of a whole.",
        ),
    ]

    chapters = engine.detect_outline("Algebra", [source], pages)

    assert chapters[0].number == "0"
    assert chapters[0].title == "Pre-Algebra"
    assert [section.number for section in chapters[0].sections] == ["0.1", "0.2"]
    assert chapters[0].sections[0].title == "Integers"


def test_detect_outline_skips_table_of_contents_page():
    engine = CourseEngine()
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    pages = [
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=4,
            text=(
                "Table of Contents\n"
                "0.1 Integers........................................ .7\n"
                "0.2 Fractions.....................................12\n"
                "0.3 Order of Operations....................18\n"
                "1.1 One-Step Equations....................28"
            ),
        ),
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=7,
            text=(
                "Chapter 0: Pre-Algebra\n"
                "0.1 Integers\n"
                "Integers are whole numbers and their opposites. "
                "Positive integers are greater than zero, and negative integers are less than zero."
            ),
        ),
    ]

    chapters = engine.detect_outline("Algebra", [source], pages)
    section = chapters[0].sections[0]

    assert section.number == "0.1"
    assert section.source_spans[0].page_start == 7
    assert "Table of Contents" not in section.source_spans[0].text


def test_detect_outline_rejects_practice_pages_and_solution_math_as_sections():
    engine = CourseEngine()
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    pages = [
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=177,
            text=(
                "Chapter 5: Polynomials\n"
                "5.1 Exponent Properties\n"
                "When multiplying powers with the same base, add the exponents."
            ),
        ),
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=182,
            text=(
                "5.1 Practice - Exponent Properties\n"
                "Simplify.\n"
                "1) 4 · 44 · 44\n"
                "3) 4 · 2 2"
            ),
        ),
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=188,
            text=(
                "5.3 Scientific Notation\n"
                "Scientific notation writes a number as a factor times a power of ten.\n"
                "0.0074 Our Solution\n"
                "1.83 = 5.832 Evaluate 1.8 3"
            ),
        ),
    ]

    chapters = engine.detect_outline("Algebra", [source], pages)
    sections = chapters[0].sections

    assert [section.number for section in sections] == ["5.1", "5.3"]
    assert [section.title for section in sections] == ["Exponent Properties", "Scientific Notation"]


def test_detect_outline_uses_table_of_contents_as_course_spine_with_source_pages():
    engine = CourseEngine()
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    pages = [
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=4,
            text=(
                "Table of Contents\n"
                "Chapter 5: Polynomials\n"
                "5.1 Exponent Properties.................177\n"
                "5.2 Negative Exponents..................183\n"
                "5.3 Scientific Notation.....................188\n"
                "5.4 Introduction to Polynomials.....192"
            ),
        ),
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=177,
            text="5.1 Exponent Properties\nThe product rule says to add exponents when multiplying powers with the same base.",
        ),
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=183,
            text="5.2 Negative Exponents\nA negative exponent can be rewritten using a reciprocal.",
        ),
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=188,
            text="5.3 Scientific Notation\nScientific notation writes a number as a decimal factor times a power of ten.",
        ),
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=192,
            text="5.4 Introduction to Polynomials\nA polynomial is a sum of terms with whole-number exponents.",
        ),
    ]

    chapters = engine.detect_outline("Algebra", [source], pages)
    sections = chapters[0].sections

    assert [section.number for section in sections] == ["5.1", "5.2", "5.3", "5.4"]
    assert sections[0].source_spans[0].page_start == 177
    assert "product rule" in sections[0].source_spans[0].text


def test_detect_outline_does_not_truncate_ten_chapter_textbook_toc():
    engine = CourseEngine()
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    toc_lines = ["Table of Contents"]
    page_number = 10
    for chapter in range(1, 11):
        toc_lines.append(f"Chapter {chapter}: Chapter {chapter} Title")
        for section in range(1, 6):
            toc_lines.append(f"{chapter}.{section} Topic {chapter}-{section}.................{page_number}")
            page_number += 5

    chapters = engine.detect_outline(
        "Algebra",
        [source],
        [
            ExtractedPage(
                source_file_id="SRC_1",
                source_name="algebra.pdf",
                page_number=4,
                text="\n".join(toc_lines),
            )
        ],
    )

    assert len(chapters) == 10
    assert [chapter.number for chapter in chapters] == [str(index) for index in range(1, 11)]
    assert sum(len(chapter.sections) for chapter in chapters) == 50
    assert chapters[-1].sections[-1].number == "10.5"


def test_build_competency_map_attaches_lessons_and_prerequisites():
    engine = CourseEngine()
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    chapters = engine.detect_outline(
        "Algebra",
        [source],
        [
            ExtractedPage(
                source_file_id="SRC_1",
                source_name="algebra.pdf",
                page_number=1,
                text="Chapter 1: Foundations\n1.1 Integers\nIntegers are positive and negative whole numbers.",
            ),
            ExtractedPage(
                source_file_id="SRC_1",
                source_name="algebra.pdf",
                page_number=2,
                text="1.2 Fractions\nFractions represent part of a whole.",
            ),
        ],
    )

    competencies = engine.build_competency_map(chapters)

    assert [competency.lesson_ids for competency in competencies] == [["SEC_1"], ["SEC_2"]]
    assert competencies[1].prerequisite_ids == ["COMP_1"]
    assert chapters[0].sections[1].competency_ids == ["COMP_2"]


def test_generate_lessons_creates_workbook_items_from_source_spans(monkeypatch):
    engine = CourseEngine(allow_deterministic_fallback=True)
    monkeypatch.setattr(engine, "_generate_with_ollama", lambda *args, **kwargs: None)
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=engine.detect_outline(
            "Algebra",
            [source],
            [
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=8,
                    text="Chapter 0: Pre-Algebra\n0.1 Integers\nAn integer is a positive or negative whole number. Integers can be added by comparing their signs.",
                )
            ],
        ),
    )

    engine.generate_lessons(course)
    section = course.chapters[0].sections[0]

    assert course.status == CourseStatus.ready
    assert section.status == CourseStatus.ready
    assert section.learning_objectives
    assert section.lesson_blocks
    assert section.worked_examples
    assert len(section.checks) == 3
    assert len(section.mastery_quiz) == 3
    assert section.is_assessment_section is True
    assert section.assessment_reason == "End-of-chapter knowledge check."
    assert {check.kind for check in section.checks} == {"multiple_choice"}
    assert {item.kind for item in section.mastery_quiz} == {"multiple_choice"}
    assert all(check.choices and check.expected_answer in check.choices for check in section.checks)
    assert all(item.choices and item.expected_answer in item.choices for item in section.mastery_quiz)
    assert course.competencies
    assert section.competency_ids == [course.competencies[0].id]
    assert course.competencies[0].lesson_ids == [section.id]


def test_generate_lessons_only_adds_assessments_at_chapter_end(monkeypatch):
    engine = CourseEngine(allow_deterministic_fallback=True)
    monkeypatch.setattr(engine, "_generate_with_ollama", lambda *args, **kwargs: None)
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=engine.detect_outline(
            "Algebra",
            [source],
            [
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=1,
                    text="Chapter 1: Foundations\n1.1 Integers\nAn integer is a positive or negative whole number. Integers can be added by comparing signs.",
                ),
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=2,
                    text="1.2 Fractions\nA fraction represents part of a whole and can be compared using equivalent forms.",
                ),
            ],
        ),
    )

    engine.generate_lessons(course)
    first, second = course.chapters[0].sections

    assert first.checks == []
    assert first.mastery_quiz == []
    assert first.is_assessment_section is False
    assert len(second.checks) == 3
    assert len(second.mastery_quiz) == 3
    assert second.is_assessment_section is True
    assert second.assessment_reason == "End-of-chapter knowledge check."
    assert {check.kind for check in second.checks} == {"multiple_choice"}


def test_generate_lessons_adds_long_chapter_checkpoint_assessments(monkeypatch):
    engine = CourseEngine(allow_deterministic_fallback=True)
    monkeypatch.setattr(engine, "_generate_with_ollama", lambda *args, **kwargs: None)
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    sections = [
        SectionLesson(
            id=f"SEC_{index}",
            chapter_id="CH_1",
            number=f"1.{index}",
            title=f"Topic {index}",
            order=index - 1,
            source_spans=[
                SourceSpan(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_start=index,
                    page_end=index,
                    text=(
                        f"1.{index} Topic {index}\n"
                        f"Topic {index} explains a useful algebra rule with examples and conditions for applying it correctly."
                    ),
                )
            ],
        )
        for index in range(1, 7)
    ]
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=[Chapter(id="CH_1", number="1", title="Long Chapter", order=0, sections=sections)],
    )
    course.competencies = engine.build_competency_map(course.chapters)

    engine.generate_lessons(course)

    assert course.chapters[0].sections[0].checks == []
    assert course.chapters[0].sections[2].checks == []
    assert len(course.chapters[0].sections[3].checks) == 3
    assert len(course.chapters[0].sections[5].checks) == 3
    assert course.chapters[0].sections[3].assessment_reason == "Long-chapter checkpoint."
    assert course.chapters[0].sections[5].assessment_reason == "End-of-chapter knowledge check."
    assert {item.kind for item in course.chapters[0].sections[3].mastery_quiz} == {"multiple_choice"}


def test_generate_lessons_replaces_thin_ollama_lesson_blocks(monkeypatch):
    engine = CourseEngine(allow_deterministic_fallback=True)
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=engine.detect_outline(
            "Algebra",
            [source],
            [
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=28,
                    text=(
                        "Chapter 1: Solving Linear Equations\n"
                        "1.1 One-Step Equations\n"
                        "A one-step equation can be solved by using inverse operations to isolate the variable. "
                        "Addition is undone by subtraction, and multiplication is undone by division."
                    ),
                )
            ],
        ),
    )
    course.competencies = engine.build_competency_map(course.chapters)
    thin_payload = {
        "learning_objectives": ["Solve one-step equations."],
        "concepts": [{"title": "One-Step Equations", "explanation": "Use inverse operations."}],
        "lesson_blocks": [
            {"kind": "teaching", "title": "Introduction", "body": "One-step equations use inverse operations."},
            {"kind": "definition", "title": "Definition", "body": "They take one step."},
            {"kind": "common_mistake", "title": "Mistake", "body": "Do not do the wrong inverse."},
        ],
        "worked_example": {"title": "Example", "prompt": "Solve x + 3 = 7.", "steps": ["Subtract 3.", "x = 4."]},
        "checks": [
            {"kind": "short_answer", "prompt": "What is the inverse of addition?", "expected_answer": "Subtraction", "choices": []},
            {"kind": "multiple_choice", "prompt": "What isolates x?", "expected_answer": "Use inverse operations", "choices": ["Use inverse operations", "Guess"]},
            {"kind": "self_explanation", "prompt": "Explain the step.", "expected_answer": "Undo the operation.", "choices": []},
        ],
        "mastery_quiz": [
            {"kind": "recall", "prompt": "What is a one-step equation?", "expected_answer": "An equation solved with one inverse operation."},
            {"kind": "application", "prompt": "How do you solve x + 3 = 7?", "expected_answer": "Subtract 3."},
            {"kind": "explanation", "prompt": "Why subtract?", "expected_answer": "It undoes addition."},
        ],
    }
    monkeypatch.setattr(engine, "_generate_with_ollama", lambda *args, **kwargs: engine._normalize_payload(thin_payload, args[0], args[1], args[2]))

    engine.generate_lessons(course)
    section = course.chapters[0].sections[0]

    total_words = sum(len(block.body.split()) for block in section.lesson_blocks)
    assert total_words >= 180
    assert {block.kind for block in section.lesson_blocks} >= {"teaching", "definition", "worked_example", "common_mistake", "self_explanation"}


def test_generate_lessons_rejects_table_of_contents_as_lesson_source(monkeypatch):
    engine = CourseEngine(allow_deterministic_fallback=True)
    monkeypatch.setattr(engine, "_generate_with_ollama", lambda *args, **kwargs: None)
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=[
            Chapter(
                id="CH_1",
                number="0",
                title="Pre-Algebra",
                order=0,
                sections=[
                    SectionLesson(
                        id="SEC_1",
                        chapter_id="CH_1",
                        number="0.1",
                        title="Integers",
                        order=0,
                        source_spans=[
                            SourceSpan(
                                source_file_id="SRC_1",
                                source_name="algebra.pdf",
                                page_start=4,
                                page_end=4,
                                text=(
                        "0.1 Integers\n"
                        "0.2 Fractions.....................................12\n"
                        "0.3 Order of Operations....................18\n"
                        "0.4 Properties of Algebra..................22\n"
                        "1.1 One-Step Equations....................28\n"
                        "1.2 Two-Step Equations....................33"
                                ),
                            )
                        ],
                    )
                ],
            )
        ],
    )

    engine.generate_lessons(course)
    section = course.chapters[0].sections[0]

    assert course.status == CourseStatus.needs_review
    assert section.status == CourseStatus.needs_review
    assert section.lesson_blocks == []


def test_quiz_submission_updates_concept_mastery_and_completion(monkeypatch):
    engine = CourseEngine(allow_deterministic_fallback=True)
    monkeypatch.setattr(engine, "_generate_with_ollama", lambda *args, **kwargs: None)
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=engine.detect_outline(
            "Algebra",
            [source],
            [
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=8,
                    text="Chapter 0: Pre-Algebra\n0.1 Integers\nAn integer is a positive or negative whole number. Integers can be added by comparing their signs.",
                )
            ],
        ),
    )
    engine.generate_lessons(course)
    section = course.chapters[0].sections[0]
    for check in section.checks[:2]:
        check.completed = True

    result = engine.submit_quiz(
        section,
        {item.id: item.expected_answer for item in section.mastery_quiz},
        confidence=5,
    )

    assert result["passed"] is True
    assert section.completed is True
    assert section.concepts[0].mastery.mastery_percent >= 70
    assert section.concepts[0].mastery.next_review_at is not None


def test_due_review_items_prioritize_high_confidence_misses(monkeypatch):
    engine = CourseEngine(allow_deterministic_fallback=True)
    monkeypatch.setattr(engine, "_generate_with_ollama", lambda *args, **kwargs: None)
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=engine.detect_outline(
            "Algebra",
            [source],
            [
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=8,
                    text="Chapter 0: Pre-Algebra\n0.1 Integers\nAn integer is a positive or negative whole number. Integers can be added by comparing their signs.",
                )
            ],
        ),
    )
    engine.generate_lessons(course)
    section = course.chapters[0].sections[0]
    competency = course.competencies[0]

    concept = section.concepts[0]
    concept.mastery.mastery_percent = 20
    engine.record_mastery_review(concept.mastery, score=0, confidence=6)
    engine._sync_competency_mastery(course)
    engine.record_mastery_review(competency.mastery, score=0, confidence=6)

    due_items = engine.due_review_items(course)

    assert due_items
    assert due_items[0]["due"] is True
    assert due_items[0]["competency_id"] == competency.id
    assert due_items[0]["section_id"] == section.id
    assert "missed" in due_items[0]["reason"]


def test_freshly_generated_course_has_no_due_reviews_before_attempt(monkeypatch):
    engine = CourseEngine(allow_deterministic_fallback=True)
    monkeypatch.setattr(engine, "_generate_with_ollama", lambda *args, **kwargs: None)
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=engine.detect_outline(
            "Algebra",
            [source],
            [
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=8,
                    text="Chapter 0: Pre-Algebra\n0.1 Integers\nAn integer is a positive or negative whole number. Integers can be added by comparing their signs.",
                )
            ],
        ),
    )

    engine.generate_lessons(course)

    assert course.competencies[0].mastery.last_score is None
    assert engine.due_review_items(course) == []
    assert engine.due_review_items(course, include_upcoming=True) == []


def test_generate_lessons_keeps_prerequisites_across_chapters(monkeypatch):
    engine = CourseEngine(allow_deterministic_fallback=True)
    monkeypatch.setattr(engine, "_generate_with_ollama", lambda *args, **kwargs: None)
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=engine.detect_outline(
            "Algebra",
            [source],
            [
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=1,
                    text="Chapter 1: Foundations\n1.1 Integers\nAn integer is a positive or negative whole number. Integers can be added by comparing signs.",
                ),
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=2,
                    text="Chapter 2: Equations\n2.1 Linear Equations\nA linear equation is solved by using inverse operations while preserving equality.",
                ),
            ],
        ),
    )

    engine.generate_lessons(course)
    first_section = course.chapters[0].sections[0]
    second_section = course.chapters[1].sections[0]

    assert first_section.concepts
    assert second_section.prerequisites == [first_section.concepts[0].id]


def test_generation_requires_ollama_unless_dev_fallback_enabled(monkeypatch):
    monkeypatch.setattr(course_engine_module, "ollama", None)
    engine = CourseEngine()
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    course = CourseDocument(
        course_id="algebra",
        title="Algebra",
        source_files=[source],
        chapters=engine.detect_outline(
            "Algebra",
            [source],
            [
                ExtractedPage(
                    source_file_id="SRC_1",
                    source_name="algebra.pdf",
                    page_number=1,
                    text="Chapter 1: Foundations\n1.1 Integers\nAn integer is a positive or negative whole number. Integers can be added by comparing signs.",
                )
            ],
        ),
    )

    with pytest.raises(course_engine_module.LLMUnavailableError):
        engine.generate_lessons(course)


def test_normalize_payload_replaces_invalid_llm_shapes():
    engine = CourseEngine(allow_deterministic_fallback=True)
    section = engine.detect_outline(
        "Algebra",
        [SourceFile(id="SRC_1", filename="algebra.pdf", order=0)],
        [
            ExtractedPage(
                source_file_id="SRC_1",
                source_name="algebra.pdf",
                page_number=1,
                text="Chapter 1: Foundations\n1.1 Integers\nAn integer is a positive or negative whole number. Integers can be added by comparing signs.",
            )
        ],
    )[0].sections[0]

    normalized = engine._normalize_payload(
        {
            "learning_objectives": ["Explain integers"],
            "concepts": [{"title": "Integers", "explanation": "Whole numbers with sign"}],
            "lesson_blocks": [{"kind": "bad_kind", "title": "Bad", "body": "Still text"}],
            "worked_example": {"title": 14, "prompt": "Use integers", "steps": [1, "Compare signs"]},
            "checks": [{"kind": "essay", "prompt": "What is an integer?", "expected_answer": "Whole number with sign"}],
            "mastery_quiz": [{"kind": "unknown", "prompt": "Recall it", "expected_answer": "Whole number with sign"}],
        },
        section,
        engine._section_evidence(section),
    )

    assert normalized["lesson_blocks"][0]["kind"] == "teaching"
    assert len(normalized["checks"]) == 3
    assert len(normalized["mastery_quiz"]) == 3
    assert {item["kind"] for item in normalized["checks"]} == {"multiple_choice"}
    assert {item["kind"] for item in normalized["mastery_quiz"]} == {"multiple_choice"}


def test_decompose_builds_competency_tree_from_raw_text():
    engine = CourseEngine()
    raw_text = (
        "Chapter 0: Pre-Algebra\n"
        "0.1 Integers\n"
        "Integers are positive and negative whole numbers."
        "\f"
        "0.2 Fractions\n"
        "A fraction represents part of a whole."
    )

    tree = engine.decompose(raw_text, title="Algebra")

    assert isinstance(tree, CompetencyTree)
    assert tree.chapters[0].number == "0"
    assert [section.number for section in tree.chapters[0].sections] == ["0.1", "0.2"]
    assert len(tree.competencies) == 2
    # Linear prerequisite chain: the second competency depends on the first.
    assert tree.competencies[0].id in tree.competencies[1].prerequisite_ids
    assert tree.competencies[0].prerequisite_ids == []


def test_decompose_matches_pdf_pipeline_competency_tree():
    """decompose(raw_text) must yield the same tree the PDF pipeline builds."""
    engine = CourseEngine()
    source = SourceFile(id="SRC_1", filename="algebra.pdf", order=0)
    pages = [
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=1,
            text="Chapter 0: Pre-Algebra\n0.1 Integers\nIntegers are positive and negative whole numbers.",
        ),
        ExtractedPage(
            source_file_id="SRC_1",
            source_name="algebra.pdf",
            page_number=2,
            text="0.2 Fractions\nA fraction represents part of a whole.",
        ),
    ]
    expected_chapters = engine.detect_outline("Algebra", [source], pages)
    expected_competencies = engine.build_competency_map(expected_chapters)

    raw_text = (
        "Chapter 0: Pre-Algebra\n0.1 Integers\nIntegers are positive and negative whole numbers."
        "\f"
        "0.2 Fractions\nA fraction represents part of a whole."
    )
    tree = engine.decompose(raw_text, title="Algebra")

    assert [c.number for c in tree.chapters] == [c.number for c in expected_chapters]
    assert [s.number for c in tree.chapters for s in c.sections] == [
        s.number for c in expected_chapters for s in c.sections
    ]
    assert [comp.id for comp in tree.competencies] == [comp.id for comp in expected_competencies]
    assert [comp.prerequisite_ids for comp in tree.competencies] == [
        comp.prerequisite_ids for comp in expected_competencies
    ]
