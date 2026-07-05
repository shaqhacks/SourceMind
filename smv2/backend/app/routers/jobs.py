from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas import JobCreate, JobOut
from app.services import jobs_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", operation_id="create_job", status_code=202, response_model=JobOut)
def create_job(body: JobCreate) -> JobOut:
    try:
        job = jobs_service.create_job(body.type, body.payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JobOut.model_validate(job)


@router.get("/{job_id}", operation_id="get_job", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    job = jobs_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut.model_validate(job)


@router.get("/{job_id}/events", operation_id="job_events")
async def job_events(job_id: str) -> StreamingResponse:
    job = jobs_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return StreamingResponse(
        jobs_service.stream_job_events(job_id), media_type="text/event-stream"
    )


@router.get("", operation_id="list_jobs", response_model=list[JobOut])
def list_jobs() -> list[JobOut]:
    jobs = jobs_service.list_jobs(limit=50)
    return [JobOut.model_validate(job) for job in jobs]
