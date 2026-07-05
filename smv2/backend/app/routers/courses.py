from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import CourseCreate, CourseOut
from app.services import courses_service

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.post("", operation_id="create_course", status_code=201, response_model=CourseOut)
def create_course(body: CourseCreate) -> CourseOut:
    course = courses_service.create_course(body.title)
    return CourseOut.model_validate(course)


@router.get("", operation_id="list_courses", response_model=list[CourseOut])
def list_courses() -> list[CourseOut]:
    return [CourseOut.model_validate(course) for course in courses_service.list_courses()]


@router.get("/{course_id}", operation_id="get_course", response_model=CourseOut)
def get_course(course_id: str) -> CourseOut:
    course = courses_service.get_course(course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    return CourseOut.model_validate(course)


@router.delete("/{course_id}", operation_id="delete_course", status_code=204)
def delete_course(course_id: str) -> None:
    deleted = courses_service.delete_course(course_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="course not found")
