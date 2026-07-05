from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import IngestStartOut, OutlineEditRequest, SectionOut
from app.services import courses_service, jobs_service, outline_service

router = APIRouter(prefix="/api/courses", tags=["ingest"])


@router.post(
    "/{course_id}/ingest", operation_id="start_ingest", status_code=202, response_model=IngestStartOut
)
def start_ingest(course_id: str) -> IngestStartOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")

    job = jobs_service.create_job("ingest", {"course_id": course_id})
    courses_service.set_course_status(course_id, "ingesting")
    return IngestStartOut(job_id=job.id)


@router.patch("/{course_id}/outline", operation_id="edit_outline", response_model=list[SectionOut])
def edit_outline(course_id: str, body: OutlineEditRequest) -> list[SectionOut]:
    course = courses_service.get_course(course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    if course.status == "ingesting":
        raise HTTPException(status_code=409, detail="course is mid-ingest")

    try:
        sections = outline_service.edit_outline(course_id, body.operations)
    except outline_service.OutlineOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return [SectionOut.model_validate(s) for s in sections]
