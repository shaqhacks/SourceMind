from SourceMind.backend.services.lesson_engine import LessonEngine
from SourceMind.backend.services.md_store import Competency, Quote, SubjectDocument


def lesson_document() -> SubjectDocument:
    return SubjectDocument(
        subject_id="lesson",
        competencies=[
            Competency(id="L1_A", name="Foundation A", level=1, dependencies=[], mastery_percent=60),
            Competency(id="L1_B", name="Foundation B", level=1, dependencies=[], mastery_percent=85),
            Competency(id="L2_A", name="Transfer A", level=2, dependencies=["L1_A", "L1_B"], mastery_percent=10),
        ],
        quotes=[
            Quote(text="Foundation A is the first source idea.", source_ref="p. 1", competency_id="L1_A", level_id=1),
            Quote(text="Foundation B supports a later transfer.", source_ref="p. 2", competency_id="L1_B", level_id=1),
            Quote(text="Transfer A combines the foundations.", source_ref="p. 3", competency_id="L2_A", level_id=2),
        ],
    )


def test_build_lesson_bundle_creates_durable_course_work() -> None:
    document = lesson_document()
    engine = LessonEngine()

    engine.ensure_lesson_model(document)

    assert len(document.lesson_model) == 3
    assert len(document.worked_examples) == 3
    assert len(document.retrieval_checks) == 9
    assert len(document.misconceptions) == 3
    assert len(document.transfer_tasks) == 1
    assert document.lesson_model[0].retrieval_check_ids == ["RC_L1_A_1", "RC_L1_A_2", "RC_L1_A_3"]
    assert document.lesson_model[0].reading
    assert document.lesson_model[0].reading[0].startswith("This lesson teaches Foundation A")
    assert "Foundation A is the first source idea." in document.lesson_model[0].reading[0]


def test_ensure_lesson_model_does_not_regenerate_existing_model() -> None:
    document = lesson_document()
    engine = LessonEngine()
    engine.ensure_lesson_model(document)
    first_ids = [lesson.id for lesson in document.lesson_model]

    engine.ensure_lesson_model(document)

    assert [lesson.id for lesson in document.lesson_model] == first_ids
    assert len(document.retrieval_checks) == 9


def test_ensure_lesson_model_backfills_reading_for_existing_lessons() -> None:
    document = lesson_document()
    engine = LessonEngine()
    engine.ensure_lesson_model(document)
    document.lesson_model[0].reading = []

    engine.ensure_lesson_model(document)

    assert document.lesson_model[0].reading
    assert "source claim" in document.lesson_model[0].reading[0]


def test_transfer_tasks_stay_locked_until_all_prerequisites_reach_gate() -> None:
    document = lesson_document()
    engine = LessonEngine()
    engine.ensure_lesson_model(document)

    task = document.transfer_tasks[0]
    assert task.locked is True

    document.competencies[0].mastery_percent = 80
    engine.refresh_transfer_locks(document)

    assert task.locked is False
    assert document.lesson_state["LESSON_L2_A"].unlocked_transfer_task_ids == [task.id]


def test_dependencyless_level_2_transfer_stays_locked_and_needs_review() -> None:
    document = SubjectDocument(
        subject_id="missing_dependencies",
        competencies=[
            Competency(id="L1_A", name="Foundation A", level=1, dependencies=[], mastery_percent=100),
            Competency(id="L2_A", name="Transfer A", level=2, dependencies=[], mastery_percent=0),
        ],
        quotes=[
            Quote(text="Foundation A is grounded.", source_ref="p. 1", competency_id="L1_A", level_id=1),
            Quote(text="Transfer A needs explicit prerequisites.", source_ref="p. 2", competency_id="L2_A", level_id=2),
        ],
    )

    LessonEngine().ensure_lesson_model(document)

    transfer_lesson = next(lesson for lesson in document.lesson_model if lesson.id == "LESSON_L2_A")
    task = document.transfer_tasks[0]
    assert transfer_lesson.status == "needs_review"
    assert task.prerequisite_ids == []
    assert task.locked is True


def test_missing_source_quote_marks_lesson_needs_review_without_generated_checks() -> None:
    document = SubjectDocument(
        subject_id="missing_source",
        competencies=[Competency(id="L1_A", name="Foundation A", level=1, dependencies=[], mastery_percent=0)],
        quotes=[],
    )

    LessonEngine().ensure_lesson_model(document)

    assert document.lesson_model[0].status == "needs_review"
    assert document.lesson_model[0].retrieval_check_ids == []
    assert document.worked_examples == []
    assert document.retrieval_checks == []


def test_low_value_source_text_marks_lesson_needs_review_without_checks() -> None:
    document = SubjectDocument(
        subject_id="bad_source",
        competencies=[Competency(id="L1_A", name="Rights Foundations", level=1, dependencies=[], mastery_percent=0)],
        quotes=[
            Quote(
                text="Beginning and Intermediate Algebra available for free download at http://wallace.ccfaculty.org/book/book.html",
                source_ref="p. 1",
                competency_id="L1_A",
                level_id=1,
            )
        ],
    )

    LessonEngine().ensure_lesson_model(document)

    assert document.lesson_model[0].status == "needs_review"
    assert "waiting for usable source evidence" in document.lesson_model[0].reading[0]
    assert document.lesson_model[0].retrieval_check_ids == []
    assert document.worked_examples == []
    assert document.retrieval_checks == []


def test_interleaving_unlocks_only_after_basic_related_mastery() -> None:
    document = lesson_document()
    engine = LessonEngine()
    engine.ensure_lesson_model(document)

    detail = engine.lesson_detail(document, "LESSON_L2_A")

    assert detail["interleaving_unlocked"] is False

    for competency in document.competencies:
        competency.mastery_percent = 65

    detail = engine.lesson_detail(document, "LESSON_L2_A")

    assert detail["interleaving_unlocked"] is True


def test_retrieval_check_update_tracks_lesson_state() -> None:
    document = lesson_document()
    engine = LessonEngine()
    engine.ensure_lesson_model(document)

    updated = engine.update_retrieval_check(
        document=document,
        lesson_id="LESSON_L1_A",
        check_id="RC_L1_A_1",
        correct=True,
        confidence=5,
        mastery_percent=74,
        interval=2,
    )

    assert updated.mastery_percent == 74
    assert updated.interval == 2
    assert updated.confidence_history == [5]
    assert document.lesson_state["LESSON_L1_A"].completed_check_ids == ["RC_L1_A_1"]
