from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from SourceMind.backend.services.llm_local import LocalLLMService
from SourceMind.backend.services.md_store import MarkdownSubjectStore
from SourceMind.backend.services.notebooklm_service import NotebookLMService


router = APIRouter(prefix="/upload", tags=["upload"])
logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = int(os.getenv("SOURCEMIND_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
UPLOAD_CHUNK_SIZE = 1024 * 1024


class UploadResponse(BaseModel):
    subject_id: str
    notebook_id: str | None = None
    source_id: str | None = None
    audio_overview_url: str | None = None
    competencies_count: int
    quotes_count: int
    status: str


@router.post("/pdf", response_model=UploadResponse)
async def upload_pdf(
    files: list[UploadFile] | None = File(default=None),
    file: UploadFile | None = File(default=None),
    title: str | None = Form(default=None),
) -> UploadResponse:
    uploads = _uploaded_files(files, file)
    if not uploads:
        raise HTTPException(status_code=422, detail="Choose at least one PDF to upload.")

    safe_filenames = [_validated_pdf_filename(upload) for upload in uploads]
    display_title = title or _default_title(safe_filenames)
    base_subject_id = _subject_id(display_title)
    store = MarkdownSubjectStore()
    notebooklm = NotebookLMService()
    llm = LocalLLMService()

    with tempfile.TemporaryDirectory(prefix="sourcemind-upload-") as tmpdir:
        pdf_paths = []
        for upload, safe_filename in zip(uploads, safe_filenames, strict=True):
            pdf_path = _unique_temp_path(Path(tmpdir), safe_filename)
            await _write_upload_file(upload, pdf_path)
            if pdf_path.stat().st_size == 0:
                raise HTTPException(status_code=422, detail=f"Uploaded PDF is empty: {safe_filename}")
            _validate_pdf_signature(pdf_path, safe_filename)
            pdf_paths.append(pdf_path)

        try:
            analysis = await notebooklm.ingest_pdfs(pdf_paths, display_title)
            document = llm.build_subject_from_notebook_analysis(base_subject_id, analysis)
            if not document.quotes:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "No selectable source text could be extracted from this PDF. "
                        "Run OCR on scanned pages or upload a text-selectable PDF so SourceMind can create quote-backed lessons."
                    ),
                )
            subject_id = _save_document_unique(store, document, base_subject_id)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("PDF ingestion failed for upload %s", ", ".join(safe_filenames))
            raise HTTPException(
                status_code=500,
                detail="PDF ingestion failed. Check the backend logs for details.",
            ) from exc

    return UploadResponse(
        subject_id=subject_id,
        notebook_id=analysis.notebook_id,
        source_id=analysis.source_id,
        audio_overview_url=analysis.audio_overview_url,
        competencies_count=len(document.competencies),
        quotes_count=len(document.quotes),
        status="created",
    )


def _subject_id(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", title.strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug or "uploaded_subject"


def _safe_pdf_filename(filename: str | None) -> str:
    if not filename:
        return ""
    basename = Path(filename).name
    if not basename.lower().endswith(".pdf"):
        return ""
    return basename


def _uploaded_files(files: list[UploadFile] | None, file: UploadFile | None) -> list[UploadFile]:
    uploads = list(files or [])
    if file is not None:
        uploads.append(file)
    return uploads


def _validated_pdf_filename(file: UploadFile) -> str:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Only PDF uploads are supported.")
    safe_filename = _safe_pdf_filename(file.filename)
    if not safe_filename:
        raise HTTPException(status_code=422, detail="Upload must have a .pdf filename.")
    return safe_filename


def _default_title(filenames: list[str]) -> str:
    if len(filenames) == 1:
        return Path(filenames[0]).stem
    return "combined_sources"


def _unique_temp_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        next_candidate = directory / f"{stem}_{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


async def _write_upload_file(file: UploadFile, destination: Path) -> int:
    total = 0
    with destination.open("wb") as handle:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploaded PDF is too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )
            handle.write(chunk)
    return total


def _validate_pdf_signature(path: Path, filename: str) -> None:
    with path.open("rb") as handle:
        signature = handle.read(5)
    if signature != b"%PDF-":
        raise HTTPException(status_code=422, detail=f"Uploaded file is not a valid PDF: {filename}")


def _save_document_unique(store: MarkdownSubjectStore, document, base_id: str) -> str:
    suffix = 1
    while True:
        candidate = base_id if suffix == 1 else f"{base_id}_{suffix}"
        document.subject_id = candidate
        try:
            store.save_new(document)
            return candidate
        except FileExistsError:
            suffix += 1
