from pathlib import Path

from fastapi.testclient import TestClient

from SourceMind.backend import main as api
from SourceMind.backend.routers import courses as courses_router
from SourceMind.backend.services import course_engine as course_engine_module
from SourceMind.backend.services.course_engine import CourseEngine, ExtractedPage
from SourceMind.backend.services.course_models import CourseDocument, CourseStatus, GenerationStatus, LessonBlock, SourceFile
from SourceMind.backend.services.course_store import CourseStore


class SimpleCourseEngine(CourseEngine):
    def create_draft_from_pdfs(self, course_id: str, title: str, pdf_paths: list[Path]) -> CourseDocument:
        source = SourceFile(id="SRC_1", filename=pdf_paths[0].name, order=0)
        return CourseDocument(
            course_id=course_id,
            title=title,
            source_files=[source],
            chapters=self.detect_outline(
                title,
                [source],
                [
                    ExtractedPage(
                        source_file_id="SRC_1",
                        source_name=pdf_paths[0].name,
                        page_number=1,
                        text="Chapter 1: Foundations\n1.1 Integers\nAn integer is a positive or negative whole number.",
                    )
                ],
            ),
        )


def test_course_upload_creates_draft_outline(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", SimpleCourseEngine())
    client = TestClient(api.app)

    response = client.post(
        "/courses/uploads",
        data={"title": "Algebra"},
        files=[("files", ("algebra.pdf", b"%PDF-1.4\nfake", "application/pdf"))],
    )

    assert response.status_code == 200
    assert response.json()["course_id"] == "algebra"
    assert response.json()["sections_count"] == 1
    stored = store.load("algebra")
    assert stored.status == CourseStatus.outline_draft
    assert stored.competencies[0].lesson_ids == [stored.chapters[0].sections[0].id]


def test_course_upload_rejects_disguised_non_pdf(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", SimpleCourseEngine())
    client = TestClient(api.app)

    response = client.post(
        "/courses/uploads",
        data={"title": "Algebra"},
        files=[("files", ("algebra.pdf", b"not a pdf", "application/pdf"))],
    )

    assert response.status_code == 422
    assert "not a valid PDF" in response.json()["detail"]


def test_course_upload_rejects_too_many_pdfs(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", SimpleCourseEngine())
    monkeypatch.setattr(courses_router, "MAX_UPLOAD_FILES", 1)
    client = TestClient(api.app)

    response = client.post(
        "/courses/uploads",
        data={"title": "Algebra"},
        files=[
            ("files", ("one.pdf", b"%PDF-1.4\nfake", "application/pdf")),
            ("files", ("two.pdf", b"%PDF-1.4\nfake", "application/pdf")),
        ],
    )

    assert response.status_code == 413
    assert "at most 1 PDFs" in response.json()["detail"]


def test_course_upload_rejects_total_pdf_size_limit(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", SimpleCourseEngine())
    monkeypatch.setattr(courses_router, "MAX_UPLOAD_FILES", 5)
    monkeypatch.setattr(courses_router, "MAX_TOTAL_UPLOAD_BYTES", 8)
    client = TestClient(api.app)

    response = client.post(
        "/courses/uploads",
        data={"title": "Algebra"},
        files=[
            ("files", ("one.pdf", b"%PDF-", "application/pdf")),
            ("files", ("two.pdf", b"%PDF-", "application/pdf")),
        ],
    )

    assert response.status_code == 413
    assert "too large together" in response.json()["detail"]


def test_course_generate_and_section_workflow(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
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
                )
            ],
        ),
    )
    store.save(course)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", engine)
    monkeypatch.setattr(courses_router, "_enqueue_generation", lambda course_id, delay_seconds=0: courses_router._run_generation_job(course_id))
    client = TestClient(api.app)

    generated = client.post("/courses/algebra/generate")
    assert generated.status_code == 200
    assert generated.json()["generation"]["status"] == "succeeded"
    assert generated.json()["competencies"]
    section_id = generated.json()["chapters"][0]["sections"][0]["id"]

    section = client.get(f"/courses/algebra/sections/{section_id}")
    assert section.status_code == 200
    assert section.json()["competencies"]
    check_id = section.json()["section"]["checks"][0]["id"]
    expected = section.json()["section"]["checks"][0]["expected_answer"]

    check = client.post(
        f"/courses/algebra/sections/{section_id}/checks/{check_id}/grade",
        json={"answer": expected, "confidence": 5},
    )
    assert check.status_code == 200
    assert check.json()["passed"] is True

    quiz_answers = {item["id"]: item["expected_answer"] for item in section.json()["section"]["mastery_quiz"]}
    quiz = client.post(
        f"/courses/algebra/sections/{section_id}/quiz/submit",
        json={"answers": quiz_answers, "confidence": 5},
    )
    assert quiz.status_code == 200
    assert quiz.json()["score"] >= 70


def test_due_reviews_endpoint_lists_scheduled_course_material(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
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
                )
            ],
        ),
    )
    engine.generate_lessons(course)
    store.save(course)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", engine)
    client = TestClient(api.app)
    section_id = course.chapters[0].sections[0].id
    check_id = course.chapters[0].sections[0].checks[0].id

    grade = client.post(
        f"/courses/algebra/sections/{section_id}/checks/{check_id}/grade",
        json={"answer": "not the right concept", "confidence": 6},
    )
    assert grade.status_code == 200

    due = client.get("/courses/reviews/due")

    assert due.status_code == 200
    payload = due.json()
    assert payload["due_count"] == 1
    assert payload["items"][0]["course_id"] == "algebra"
    assert payload["items"][0]["section_id"] == section_id


def test_due_reviews_endpoint_does_not_mask_broken_course_files(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
    store.course_path("broken").write_text(
        "---\ncourse_id: broken\n---\n\n## COURSE_JSON:\n```json\n{\"course_id\":\n```\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(courses_router, "course_store", store)
    client = TestClient(api.app, raise_server_exceptions=False)

    response = client.get("/courses/reviews/due")

    assert response.status_code >= 500


def test_get_course_reconciles_generation_without_persisting_lesson_repair(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
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
                )
            ],
        ),
    )
    engine.generate_lessons(course)
    section = course.chapters[0].sections[0]
    section.lesson_blocks = [
        LessonBlock(
            id="thin",
            kind="teaching",
            title="Thin",
            body="Thin.",
        )
    ]
    course.generation.status = GenerationStatus.running
    store.save(course)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", engine)
    monkeypatch.setattr(courses_router, "_enqueue_generation", lambda course_id, delay_seconds=0: None)
    client = TestClient(api.app)

    response = client.get("/courses/algebra")

    assert response.status_code == 200
    saved_course = store.load("algebra")
    assert saved_course.chapters[0].sections[0].lesson_blocks[0].body == "Thin."
    assert saved_course.generation.status == GenerationStatus.queued


def test_course_chat_labels_support_status(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
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
                )
            ],
        ),
    )
    engine.generate_lessons(course)
    store.save(course)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", engine)
    client = TestClient(api.app)
    section_id = course.chapters[0].sections[0].id

    response = client.post(
        f"/courses/algebra/sections/{section_id}/chat",
        json={"question": "What is an integer?"},
    )

    assert response.status_code == 200
    assert response.json()["support_status"] in {"pdf_backed", "course_inference", "outside_knowledge"}
    assert store.load("algebra").chapters[0].sections[0].chat_history


def test_course_generate_retries_missing_ollama_without_fake_lessons(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(course_engine_module, "ollama", None)
    monkeypatch.setattr(courses_router, "GENERATION_RETRY_BASE_SECONDS", 0.01)
    store = CourseStore(tmp_path)
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
    store.save(course)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", engine)
    monkeypatch.setattr(courses_router, "_enqueue_generation", lambda course_id, delay_seconds=0: None)
    client = TestClient(api.app)

    response = client.post("/courses/algebra/generate")
    assert response.status_code == 200
    courses_router._run_generation_job("algebra")
    response = client.get("/courses/algebra")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == CourseStatus.generating.value
    assert payload["generation"]["status"] == GenerationStatus.retry_scheduled.value
    assert "Ollama" in payload["generation"]["last_error"]
    assert payload["generation"]["next_retry_at"] is not None


def test_course_generate_returns_immediately_with_queued_progress(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
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
                )
            ],
        ),
    )
    store.save(course)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", engine)
    monkeypatch.setattr(courses_router, "_enqueue_generation", lambda course_id, delay_seconds=0: None)
    client = TestClient(api.app)

    response = client.post("/courses/algebra/generate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == CourseStatus.generating.value
    assert payload["generation"]["status"] == GenerationStatus.queued.value
    assert payload["generation"]["total_sections"] == 1
    assert payload["generation"]["completed_sections"] == 0


def test_course_section_regenerate_queues_failed_section_only(tmp_path: Path, monkeypatch) -> None:
    store = CourseStore(tmp_path)
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
                    page_number=1,
                    text=(
                        "Chapter 1: Foundations\n"
                        "1.1 Integers\n"
                        "An integer is a positive or negative whole number. Integers can be added by comparing signs."
                    ),
                )
            ],
        ),
    )
    section = course.chapters[0].sections[0]
    section.status = CourseStatus.needs_review
    section.lesson_blocks = [
        LessonBlock(
            id="old_block",
            kind="teaching",
            title="Old failed block",
            body="This should be cleared before regeneration.",
        )
    ]
    store.save(course)
    monkeypatch.setattr(courses_router, "course_store", store)
    monkeypatch.setattr(courses_router, "course_engine", engine)
    monkeypatch.setattr(courses_router, "_enqueue_generation", lambda course_id, delay_seconds=0: None)
    client = TestClient(api.app)

    response = client.post(f"/courses/algebra/sections/{section.id}/regenerate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == CourseStatus.generating.value
    assert payload["generation"]["status"] == GenerationStatus.queued.value
    assert payload["generation"]["total_sections"] == 1
    assert payload["generation"]["completed_sections"] == 0
    regenerated_section = payload["chapters"][0]["sections"][0]
    assert regenerated_section["status"] == CourseStatus.outline_draft.value
    assert regenerated_section["lesson_blocks"] == []
