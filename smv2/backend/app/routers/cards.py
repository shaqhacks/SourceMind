from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import CardOut, GenerateCardsOut, UpdateCardIn
from app.services import cards_service, llm_readiness_service

router = APIRouter(tags=["cards"])


@router.post(
    "/api/sections/{section_id}/cards",
    operation_id="generate_cards",
    status_code=202,
    response_model=GenerateCardsOut,
)
def generate_cards(section_id: str) -> GenerateCardsOut:
    try:
        job_id = cards_service.start_card_generation(section_id)
    except llm_readiness_service.LlmReadinessUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    except cards_service.SectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except cards_service.CardGenerationAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GenerateCardsOut(job_id=job_id)


@router.get("/api/sections/{section_id}/cards", operation_id="list_cards", response_model=list[CardOut])
def list_cards(section_id: str) -> list[CardOut]:
    cards = cards_service.list_cards(section_id)
    if cards is None:
        raise HTTPException(status_code=404, detail="section not found")
    return [CardOut.model_validate(c) for c in cards]


@router.patch("/api/cards/{card_id}", operation_id="update_card", response_model=CardOut)
def update_card(card_id: str, body: UpdateCardIn) -> CardOut:
    try:
        card = cards_service.update_card(card_id, body.front_md, body.back_md)
    except cards_service.CardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except cards_service.DuplicateCardError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CardOut.model_validate(card)


@router.delete("/api/cards/{card_id}", operation_id="delete_card", status_code=204)
def delete_card(card_id: str) -> None:
    deleted = cards_service.delete_card(card_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="card not found")
