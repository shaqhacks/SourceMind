from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import CardOut, GenerateCardsOut
from app.services import cards_service

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
