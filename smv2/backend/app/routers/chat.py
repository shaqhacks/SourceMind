from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.llm.ledger import SpendCapExceededError
from app.llm.provider import ProviderNotConfiguredError, ProviderTimeoutError
from app.schemas import ChatIn, ChatOut, ChatTurnOut
from app.services import chat_service, courses_service, learner_context, llm_readiness_service

router = APIRouter(tags=["chat"])


@router.post("/api/courses/{course_id}/chat", operation_id="send_chat", response_model=ChatOut)
def send_chat(
    course_id: str, body: ChatIn, request: Request, response: Response
) -> ChatOut:
    learner_id = learner_context.ensure_learner_key(request, response)
    try:
        result = chat_service.send_chat(
            course_id,
            body.message,
            selection=body.selection.model_dump() if body.selection else None,
            learner_id=learner_id,
        )
    except chat_service.SelectionSectionMismatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except chat_service.CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail=llm_readiness_service.readiness_failure_detail(),
        ) from exc
    except llm_readiness_service.LlmReadinessUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    except SpendCapExceededError as exc:
        # Distinct 429 detail from LLMBusyError's ("LLM concurrency limit
        # reached") global handler — the client needs to tell "busy, retry"
        # apart from "this course is out of budget."
        raise HTTPException(status_code=429, detail="course spend cap exceeded") from exc
    return ChatOut.model_validate(result)


@router.get("/api/courses/{course_id}/chat", operation_id="chat_history", response_model=list[ChatTurnOut])
def chat_history(course_id: str) -> list[ChatTurnOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [ChatTurnOut.model_validate(t) for t in chat_service.get_chat_history(course_id)]
