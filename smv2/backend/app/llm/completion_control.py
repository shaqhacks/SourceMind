"""Provider-neutral completion controls for streamed generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

CompletionPhase = Literal["loading", "thinking", "generating", "finalizing"]


@dataclass(frozen=True)
class CompletionProgress:
    phase: CompletionPhase
    elapsed_seconds: float
    seconds_since_activity: float


@dataclass(frozen=True)
class CompletionOptions:
    progress: Callable[[CompletionProgress], None] | None = None
    is_cancelled: Callable[[], bool] | None = None
    response_schema: dict[str, Any] | None = None


class ProviderStreamError(Exception):
    def __init__(self, message: str, *, category: str, had_activity: bool):
        super().__init__(message)
        self.category = category
        self.had_activity = had_activity


class ProviderCancelledError(Exception):
    pass
