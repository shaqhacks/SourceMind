"""Per-model $/Mtok pricing table for cost estimation.

Unknown models return None (never guess a cost for a model we don't have a
real rate for) — approximate published rates, update as pricing changes.
"""

from __future__ import annotations

# model -> (input $ per million tokens, output $ per million tokens)
_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
    "claude-haiku-4-5-20251001": (0.8, 4.0),
    # DeepSeek published rates (approximate; update as pricing changes).
    "deepseek-chat": (0.28, 0.42),
    "deepseek-reasoner": (0.55, 2.19),
    # Gemini published rates (approximate; update as pricing changes).
    "gemini-3.6-flash": (0.10, 0.40),
    "gemini-3.5-flash": (0.10, 0.40),
    "gemini-embedding-001": (0.0125, 0.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    rates = _PRICING_PER_MTOK.get(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    return (input_tokens / 1_000_000) * input_rate + (output_tokens / 1_000_000) * output_rate
