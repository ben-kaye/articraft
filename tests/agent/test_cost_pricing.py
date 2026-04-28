from __future__ import annotations

import pytest

from agent.cost import calculate_cost, pricing_for_provider_model


def test_gpt55_pricing_uses_explicit_model_rates() -> None:
    pricing = pricing_for_provider_model("openai", "gpt-5.5-2026-04-23")

    assert pricing == {
        "input_uncached": 5.00,
        "input_cached": 0.50,
        "output": 30.00,
        "prompt_tier_threshold_tokens": 272_000,
        "input_uncached_above_threshold": 10.00,
        "input_cached_above_threshold": 1.00,
        "output_above_threshold": 45.00,
    }


def test_gpt55_pricing_uses_high_context_tier_above_threshold() -> None:
    pricing = pricing_for_provider_model("openai", "gpt-5.5-2026-04-23")
    assert pricing is not None

    cost = calculate_cost(
        {
            "prompt_tokens": 300_000,
            "cached_tokens": 100_000,
            "candidates_tokens": 10_000,
            "total_tokens": 310_000,
        },
        pricing,
    )

    assert cost.input_uncached_cost == 2.0
    assert cost.input_cached_cost == 0.1
    assert cost.output_cost == 0.45
    assert cost.total_cost == pytest.approx(2.55)


def test_gpt54_pricing_remains_unchanged() -> None:
    pricing = pricing_for_provider_model("openai", "gpt-5.4")

    assert pricing is not None
    assert pricing["input_uncached"] == 2.50
    assert pricing["input_cached"] == 0.25
    assert pricing["output"] == 15.00
