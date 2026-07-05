"""Pydantic request/response schemas, kept separate from routers so router
imports stay limited to fastapi/pydantic/app.services/app.schemas/app.config.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobCreate(BaseModel):
    type: str
    payload: dict[str, Any] | None = None


class JobOut(BaseModel):
    id: str
    type: str
    status: str
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    progress: dict[str, Any] | None
    error: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CourseCreate(BaseModel):
    title: str


class CourseOut(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
