from __future__ import annotations

from fastapi import APIRouter

from app.config import api_version

router = APIRouter()


@router.get("/health", operation_id="health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": api_version()}
