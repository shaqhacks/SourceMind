from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services import courses_service, images_service

router = APIRouter(tags=["images"])


@router.get("/api/courses/{course_id}/images/{filename}", operation_id="get_course_image")
def get_course_image(course_id: str, filename: str) -> FileResponse:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        path = images_service.resolve_image_path(course_id, filename)
    except images_service.InvalidImageFilenameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except images_service.ImageNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # media_type intentionally omitted: FileResponse/mimetypes guesses it
    # correctly from the extension (pymupdf4llm's default is .png).
    return FileResponse(path)
