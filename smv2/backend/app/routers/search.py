from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.schemas import SearchResultsOut
from app.services import courses_service, search_service

router = APIRouter(prefix="/api/courses", tags=["search"])


@router.get("/{course_id}/search", operation_id="search_course", response_model=SearchResultsOut)
def search_course(
    course_id: str,
    query: Annotated[str, Query(min_length=1)],
    document_type: Annotated[list[str] | None, Query()] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResultsOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        return search_service.search_course(
            course_id,
            query,
            document_types=document_type,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
