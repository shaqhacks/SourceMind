from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.config import max_upload_bytes
from app.schemas import AssetOut
from app.services import assets_service, courses_service
from app.services.assets_service import FileTooLargeError, UnsupportedFileTypeError

router = APIRouter(prefix="/api/courses", tags=["assets"])


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
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    return AssetOut.model_validate(asset)


@router.get("/{course_id}/assets", operation_id="list_assets", response_model=list[AssetOut])
def list_assets(course_id: str) -> list[AssetOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [AssetOut.model_validate(a) for a in assets_service.list_assets(course_id)]
