from pathlib import Path

from fastapi.testclient import TestClient

from SourceMind.backend import main as api
from SourceMind.backend.routers import upload as upload_router
from SourceMind.backend.services.md_store import Competency, MarkdownSubjectStore, Quote, SubjectDocument
from SourceMind.backend.services.notebooklm_service import NotebookAnalysis


class FakeNotebookLMService:
    seen_paths: list[str] = []

    async def ingest_pdfs(self, pdf_paths: list[Path], title: str) -> NotebookAnalysis:
        self.__class__.seen_paths = [path.name for path in pdf_paths]
        return NotebookAnalysis(raw={"test": True, "title": title})

    async def ingest_pdf(self, pdf_path: Path, title: str) -> NotebookAnalysis:
        return await self.ingest_pdfs([pdf_path], title)


class FailingNotebookLMService:
    async def ingest_pdfs(self, pdf_paths: list[Path], title: str) -> NotebookAnalysis:
        raise RuntimeError("/internal/provider/path failed")

    async def ingest_pdf(self, pdf_path: Path, title: str) -> NotebookAnalysis:
        return await self.ingest_pdfs([pdf_path], title)


class FakeLLMService:
    def __init__(self, quotes: list[Quote] | None = None) -> None:
        self.quotes = quotes if quotes is not None else [
            Quote(
                text="Source-backed lessons need extracted quotes.",
                source_ref="p. 1",
                competency_id="L1_1",
                level_id=1,
            )
        ]

    def build_subject_from_notebook_analysis(self, subject_id: str, analysis: NotebookAnalysis) -> SubjectDocument:
        return SubjectDocument(
            subject_id=subject_id,
            competencies=[Competency(id="L1_1", name="Source Foundations", level=1, mastery_percent=0)],
            quotes=self.quotes,
        )


def test_upload_uses_unique_subject_id_instead_of_overwriting(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    store.save(
        SubjectDocument(
            subject_id="my_subject",
            competencies=[Competency(id="OLD", name="Old", level=1, mastery_percent=0)],
            quotes=[Quote(text="Old quote.", source_ref="p. 1", competency_id="OLD", level_id=1)],
        )
    )
    monkeypatch.setattr(upload_router, "MarkdownSubjectStore", lambda: store)
    monkeypatch.setattr(upload_router, "NotebookLMService", FakeNotebookLMService)
    monkeypatch.setattr(upload_router, "LocalLLMService", FakeLLMService)
    client = TestClient(api.app)

    response = client.post(
        "/upload/pdf",
        data={"title": "My Subject"},
        files={"file": ("source.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["subject_id"] == "my_subject_2"
    assert store.exists("my_subject")
    assert store.exists("my_subject_2")
    assert store.load("my_subject").competencies[0].id == "OLD"


def test_upload_rejects_pdf_when_ingestion_produces_no_quotes(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    monkeypatch.setattr(upload_router, "MarkdownSubjectStore", lambda: store)
    monkeypatch.setattr(upload_router, "NotebookLMService", FakeNotebookLMService)
    monkeypatch.setattr(upload_router, "LocalLLMService", lambda: FakeLLMService(quotes=[]))
    client = TestClient(api.app)

    response = client.post(
        "/upload/pdf",
        data={"title": "Scanned Notes"},
        files={"file": ("scanned.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 422
    assert "No selectable source text" in response.json()["detail"]
    assert not store.exists("scanned_notes")


def test_upload_accepts_multiple_pdfs_in_one_subject(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    FakeNotebookLMService.seen_paths = []
    monkeypatch.setattr(upload_router, "MarkdownSubjectStore", lambda: store)
    monkeypatch.setattr(upload_router, "NotebookLMService", FakeNotebookLMService)
    monkeypatch.setattr(upload_router, "LocalLLMService", FakeLLMService)
    client = TestClient(api.app)

    response = client.post(
        "/upload/pdf",
        data={"title": "Combined Algebra"},
        files=[
            ("files", ("chapter1.pdf", b"%PDF-1.4\nchapter one", "application/pdf")),
            ("files", ("chapter2.pdf", b"%PDF-1.4\nchapter two", "application/pdf")),
        ],
    )

    assert response.status_code == 200
    assert response.json()["subject_id"] == "combined_algebra"
    assert FakeNotebookLMService.seen_paths == ["chapter1.pdf", "chapter2.pdf"]
    assert store.exists("combined_algebra")


def test_safe_pdf_filename_strips_client_path_segments() -> None:
    assert upload_router._safe_pdf_filename("../../outside.pdf") == "outside.pdf"
    assert upload_router._safe_pdf_filename("/tmp/outside.pdf") == "outside.pdf"
    assert upload_router._safe_pdf_filename("notes.txt") == ""
    assert upload_router._safe_pdf_filename(None) == ""


def test_save_document_unique_retries_with_exclusive_create(tmp_path: Path) -> None:
    store = MarkdownSubjectStore(tmp_path)
    first = FakeLLMService().build_subject_from_notebook_analysis("same_title", NotebookAnalysis())
    second = FakeLLMService().build_subject_from_notebook_analysis("same_title", NotebookAnalysis())

    first_id = upload_router._save_document_unique(store, first, "same_title")
    second_id = upload_router._save_document_unique(store, second, "same_title")

    assert first_id == "same_title"
    assert second_id == "same_title_2"
    assert store.exists("same_title")
    assert store.exists("same_title_2")


def test_upload_rejects_oversized_pdf_before_ingestion(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    monkeypatch.setattr(upload_router, "MarkdownSubjectStore", lambda: store)
    monkeypatch.setattr(upload_router, "NotebookLMService", FakeNotebookLMService)
    monkeypatch.setattr(upload_router, "LocalLLMService", FakeLLMService)
    monkeypatch.setattr(upload_router, "MAX_UPLOAD_BYTES", 4)
    client = TestClient(api.app)

    response = client.post(
        "/upload/pdf",
        data={"title": "Huge"},
        files={"file": ("huge.pdf", b"12345", "application/pdf")},
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"]
    assert not store.exists("huge")


def test_upload_returns_bounded_error_for_ingestion_exception(tmp_path: Path, monkeypatch) -> None:
    store = MarkdownSubjectStore(tmp_path)
    monkeypatch.setattr(upload_router, "MarkdownSubjectStore", lambda: store)
    monkeypatch.setattr(upload_router, "NotebookLMService", FailingNotebookLMService)
    monkeypatch.setattr(upload_router, "LocalLLMService", FakeLLMService)
    client = TestClient(api.app)

    response = client.post(
        "/upload/pdf",
        data={"title": "Broken"},
        files={"file": ("broken.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "PDF ingestion failed. Check the backend logs for details."
    assert "/internal/provider/path" not in response.json()["detail"]
