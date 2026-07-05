from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.llm.provider import ProviderTimeoutError
from app.schemas import ChatIn, ChatOut, ChatTurnOut
from app.services import chat_service, courses_service

router = APIRouter(tags=["chat"])


@router.post("/api/courses/{course_id}/chat", operation_id="send_chat", response_model=ChatOut)
def send_chat(course_id: str, body: ChatIn) -> ChatOut:
    try:
        result = chat_service.send_chat(course_id, body.message)
    except chat_service.CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    return ChatOut.model_validate(result)


@router.get("/api/courses/{course_id}/chat", operation_id="chat_history", response_model=list[ChatTurnOut])
def chat_history(course_id: str) -> list[ChatTurnOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [ChatTurnOut.model_validate(t) for t in chat_service.get_chat_history(course_id)]
