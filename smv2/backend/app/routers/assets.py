from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.config import max_upload_bytes
from app.pipeline.import_adapters import UNSUPPORTED_SOURCE_FORMAT_CODE
from app.schemas import AssetOut
from app.services import assets_service, courses_service, html_pages_service
from app.services.assets_service import (
    AssetFileMissingError,
    AssetNotFoundError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)

# Applied to both the manifest and page-HTML responses: the served page
# HTML is untrusted-ish (derived from a user-uploaded PDF) and rendered in
# a sandboxed iframe on the frontend — default-src 'none' blocks scripts
# entirely (the pages this endpoint serves never contain any: pdf2htmlEX's
# --split-pages output is a bare content fragment, and app.pipeline.
# html_conversion only ever inlines CSS into it, never JS), style-src
# 'unsafe-inline' allows the inlined layout CSS, font-src/img-src data:
# allow the base64-embedded fonts/background images pdf2htmlEX produces.
_HTML_PAGE_CSP = "default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:"
_HTML_PAGE_HEADERS = {"Content-Security-Policy": _HTML_PAGE_CSP, "X-Frame-Options": "SAMEORIGIN"}

router = APIRouter(prefix="/api/courses", tags=["assets"])
asset_router = APIRouter(prefix="/api/assets", tags=["assets"])

_UNSAFE_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _extension_for_source(source_format: str | None, media_type: str | None) -> str:
    normalized_format = (source_format or "").lower()
    normalized_media = (media_type or "").lower()
    if normalized_format == "markdown" or normalized_media in {"text/markdown", "text/x-markdown"}:
        return ".md"
    if normalized_format == "html" or normalized_media == "text/html":
        return ".html"
    if normalized_format in {"text", "plain_text"} or normalized_media == "text/plain":
        return ".txt"
    if normalized_format == "pdf" or normalized_media == "application/pdf":
        return ".pdf"
    return ".bin"


def _sanitize_download_filename(
    filename: str,
    *,
    source_format: str | None = None,
    media_type: str | None = None,
) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS_RE.sub("-", filename).strip("-") or "asset"
    if "." in cleaned:
        stem, current_ext = cleaned.rsplit(".", 1)
        stem = stem or "asset"
        current_ext = f".{current_ext.lower()}"
    else:
        stem, current_ext = cleaned, ""
    expected_ext = _extension_for_source(source_format, media_type)
    if current_ext == expected_ext:
        return f"{stem}{current_ext}"
    return f"{stem}{expected_ext}"


@router.post(
    "/{course_id}/assets", operation_id="upload_asset", status_code=201, response_model=AssetOut
)
async def upload_asset(course_id: str, request: Request, file: UploadFile) -> AssetOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")

    # Reject obviously-oversized uploads by their declared Content-Length
    # before reading a single byte of the body — the service-level check
    # during streaming is the real enforcement, this is just a fast exit.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > max_upload_bytes():
            raise HTTPException(status_code=413, detail="file exceeds max upload size")

    try:
        asset = await assets_service.save_upload(
            course_id,
            file.filename or "upload.pdf",
            file.content_type or "application/octet-stream",
            file,
        )
    except UnsupportedFileTypeError as exc:
        detail: str | dict[str, str]
        if str(exc) == UNSUPPORTED_SOURCE_FORMAT_CODE:
            detail = {"code": UNSUPPORTED_SOURCE_FORMAT_CODE}
        else:
            detail = str(exc)
        raise HTTPException(status_code=415, detail=detail) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    return AssetOut.model_validate(asset)


@router.get("/{course_id}/assets", operation_id="list_assets", response_model=list[AssetOut])
def list_assets(course_id: str) -> list[AssetOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [AssetOut.model_validate(a) for a in assets_service.list_assets(course_id)]


@asset_router.get("/{asset_id}/file", operation_id="get_asset_file")
def get_asset_file(asset_id: str) -> FileResponse:
    """Serves the original uploaded source as-is, for the reader's
    original-source page view. Inline disposition keeps browser-viewable
    sources embedded where supported instead of forcing a download.
    """
    try:
        path, filename, media_type, source_format = assets_service.resolve_asset_file_path(asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except AssetFileMissingError as exc:
        raise HTTPException(status_code=404, detail="asset file not found") from exc

    return FileResponse(
        path,
        media_type=media_type,
        filename=_sanitize_download_filename(
            filename,
            source_format=source_format,
            media_type=media_type,
        ),
        content_disposition_type="inline",
    )


@asset_router.get("/{asset_id}/html/manifest", operation_id="get_asset_html_manifest")
def get_asset_html_manifest(asset_id: str) -> JSONResponse:
    try:
        manifest = html_pages_service.get_manifest(asset_id)
    except html_pages_service.AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except html_pages_service.HtmlNotReadyError as exc:
        raise HTTPException(status_code=404, detail="html conversion not ready") from exc
    return JSONResponse(content=manifest, headers=_HTML_PAGE_HEADERS)


@asset_router.get("/{asset_id}/html/{page}", operation_id="get_asset_html_page")
def get_asset_html_page(asset_id: str, page: int) -> HTMLResponse:
    try:
        path = html_pages_service.resolve_page_path(asset_id, page)
    except html_pages_service.AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except html_pages_service.HtmlNotReadyError as exc:
        raise HTTPException(status_code=404, detail="html conversion not ready") from exc
    except html_pages_service.HtmlPageNotFoundError as exc:
        raise HTTPException(status_code=404, detail="page not found") from exc

    return HTMLResponse(content=path.read_text(encoding="utf-8"), headers=_HTML_PAGE_HEADERS)
