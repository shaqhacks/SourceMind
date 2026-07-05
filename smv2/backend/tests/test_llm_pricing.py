from __future__ import annotations

from app.llm.pricing import estimate_cost


def test_estimate_cost_known_model():
    cost = estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 3.0 + 15.0


def test_estimate_cost_scales_with_tokens():
    cost = estimate_cost("claude-sonnet-5", input_tokens=500_000, output_tokens=0)
    assert cost == 1.5


def test_estimate_cost_unknown_model_returns_none():
    assert estimate_cost("some-model-that-does-not-exist", input_tokens=1000, output_tokens=1000) is None


def test_estimate_cost_zero_tokens_is_zero():
    assert estimate_cost("claude-sonnet-5", input_tokens=0, output_tokens=0) == 0.0
