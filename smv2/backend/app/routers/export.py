from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services import export_service

router = APIRouter(prefix="/api/courses", tags=["export"])

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_STREAM_CHUNK_SIZE = 1024 * 1024


def _sanitize_filename(title: str) -> str:
    cleaned = _SAFE_FILENAME_RE.sub("-", title).strip("-")
    return f"{cleaned}.zip" if cleaned else "course-export.zip"


@router.get("/{course_id}/export", operation_id="export_course")
def export_course(course_id: str) -> StreamingResponse:
    result = export_service.build_export_zip(course_id)
    if result is None:
        raise HTTPException(status_code=404, detail="course not found")
    spool, course_title = result

    def _stream_and_close():
        try:
            while True:
                chunk = spool.read(_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            spool.close()

    filename = _sanitize_filename(course_title)
    return StreamingResponse(
        _stream_and_close(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
