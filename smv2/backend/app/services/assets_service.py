"""Asset upload: content-sniffed PDF validation, on-disk storage, Asset row.

Framework-free-ish — `file` only needs to expose an async `read(n) -> bytes`
method (FastAPI's UploadFile satisfies this duck type). Validation is by
magic bytes, never by filename extension or the client-supplied
content-type header (both are trivially spoofable). Reads happen in bounded
chunks streamed straight to disk, so an oversized upload is rejected
mid-stream and never fully buffered into memory.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Protocol

from app.config import data_dir, max_upload_bytes
from app.db.engine import get_session
from app.db.models import Asset

_PDF_MAGIC = b"%PDF-"
_PDF_SOURCE_FORMAT = "pdf"
_PDF_MEDIA_TYPE = "application/pdf"
# fitz itself tolerates the %PDF- marker appearing anywhere in roughly the
# first 1KB (some PDFs are preceded by junk bytes/comments) rather than
# strictly at offset 0 — match that same tolerance here.
_MAGIC_SNIFF_WINDOW = 1024
_CHUNK_SIZE = 1024 * 1024  # 1MB


class UnsupportedFileTypeError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


class _AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


async def save_upload(course_id: str, filename: str, content_type: str, file: _AsyncReadable) -> Asset:
    max_bytes = max_upload_bytes()

    asset_id = str(uuid.uuid4())
    assets_dir = data_dir() / "assets" / course_id
    assets_dir.mkdir(parents=True, exist_ok=True)
    stored_path = assets_dir / f"{asset_id}.pdf"

    sha256_hash = hashlib.sha256()
    total_bytes = 0
    sniff_buffer = b""
    magic_confirmed = False

    with stored_path.open("wb") as out:
        while True:
            chunk = await file.read(_CHUNK_SIZE)
            if not chunk:
                break

            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                stored_path.unlink(missing_ok=True)
                raise FileTooLargeError(f"file exceeds max upload size of {max_bytes} bytes")

            if not magic_confirmed:
                sniff_buffer += chunk
                if len(sniff_buffer) >= _MAGIC_SNIFF_WINDOW:
                    if _PDF_MAGIC not in sniff_buffer[:_MAGIC_SNIFF_WINDOW]:
                        stored_path.unlink(missing_ok=True)
                        raise UnsupportedFileTypeError(
                            "file is not a PDF (no %PDF- marker in first 1KB)"
                        )
                    magic_confirmed = True

            sha256_hash.update(chunk)
            out.write(chunk)

    if not magic_confirmed and _PDF_MAGIC not in sniff_buffer:
        # File was smaller than the sniff window in total.
        stored_path.unlink(missing_ok=True)
        raise UnsupportedFileTypeError("file is not a PDF (no %PDF- marker in first 1KB)")

    session = get_session()
    try:
        asset = Asset(
            id=asset_id,
            course_id=course_id,
            filename=filename,
            content_type=content_type,
            source_format=_PDF_SOURCE_FORMAT,
            media_type=_PDF_MEDIA_TYPE,
            size_bytes=total_bytes,
            sha256=sha256_hash.hexdigest(),
            stored_path=str(stored_path),
            status="stored",
        )
        session.add(asset)
        session.commit()
        return asset
    finally:
        session.close()


def list_assets(course_id: str) -> list[Asset]:
    session = get_session()
    try:
        return (
            session.query(Asset)
            .filter(Asset.course_id == course_id)
            .order_by(Asset.created_at.asc())
            .all()
        )
    finally:
        session.close()


class AssetNotFoundError(ValueError):
    pass


class AssetFileMissingError(ValueError):
    pass


def resolve_asset_file_path(asset_id: str) -> tuple[Path, str, str]:
    """Returns (absolute path, original filename) for serving asset_id's
    stored PDF as-is (original-PDF page view). Asset.stored_path is a
    server-minted value written once at upload time (assets_service.
    save_upload), never user input at request time — but we still assert it
    resolves under data_dir()/assets before returning it, belt and braces,
    the same reasoning as images_service.resolve_image_path's containment
    check for a path that's normally trustworthy by construction.
    """
    session = get_session()
    try:
        asset = session.get(Asset, asset_id)
    finally:
        session.close()

    if asset is None:
        raise AssetNotFoundError(f"asset not found: {asset_id!r}")

    assets_root = (data_dir() / "assets").resolve()
    candidate = Path(asset.stored_path).resolve()
    if candidate != assets_root and assets_root not in candidate.parents:
        raise AssetNotFoundError(f"asset {asset_id!r} stored_path escapes the assets directory")

    if not candidate.is_file():
        raise AssetFileMissingError(f"asset file missing on disk: {asset_id!r}")

    return candidate, asset.filename, asset.media_type
