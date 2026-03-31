"""
Cost tracking and calculation for LLM API usage.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

MAX_COST_ENV_VAR = "ARTICRAFT_MAX_COST_USD"


GEMINI_FLASH_PRICING: dict[str, float] = {
    "input_uncached": 0.50,
    "input_cached": 0.05,
    "output": 3.00,
}

GEMINI_3_PRO_PRICING: dict[str, float] = {
    "input_uncached": 2.00,
    "input_cached": 2.00,
    "output": 12.00,
    "prompt_tier_threshold_tokens": 200_000,
    "input_uncached_above_threshold": 4.00,
    "input_cached_above_threshold": 4.00,
    "output_above_threshold": 18.00,
}

OPENAI_GPT_5_3_CODEX_PRICING: dict[str, float] = {
    "input_uncached": 1.75,
    "input_cached": 0.175,
    "output": 14.00,
}
OPENAI_GPT_5_2_PRICING = OPENAI_GPT_5_3_CODEX_PRICING

OPENAI_GPT_5_4_PRICING: dict[str, float] = {
    "input_uncached": 2.50,
    "input_cached": 0.25,
    "output": 15.00,
    "prompt_tier_threshold_tokens": 272_000,
    "input_uncached_above_threshold": 5.00,
    "input_cached_above_threshold": 0.50,
    "output_above_threshold": 22.50,
}


@dataclass(slots=True)
class CostBreakdown:
    """Detailed cost breakdown for a single turn or cumulative total."""

    prompt_tokens: int = 0
    cached_tokens: int = 0
    uncached_prompt_tokens: int = 0
    candidates_tokens: int = 0
    total_tokens: int = 0
    input_uncached_cost: float = 0.0
    input_cached_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0

    def __post_init__(self) -> None:
        if self.uncached_prompt_tokens == 0 and self.prompt_tokens > 0:
            self.uncached_prompt_tokens = self.prompt_tokens - self.cached_tokens


def calculate_cost(usage: dict[str, int], pricing: dict[str, float]) -> CostBreakdown:
    prompt_tokens = usage.get("prompt_tokens", 0)
    cached_tokens = usage.get("cached_tokens", 0)
    candidates_tokens = usage.get("candidates_tokens", 0)
    uncached_prompt_tokens = max(0, prompt_tokens - cached_tokens)

    threshold = pricing.get("prompt_tier_threshold_tokens")
    if threshold is not None and prompt_tokens > int(threshold):
        input_uncached_rate = pricing.get(
            "input_uncached_above_threshold",
            pricing["input_uncached"],
        )
        input_cached_rate = pricing.get(
            "input_cached_above_threshold",
            pricing["input_cached"],
        )
        output_rate = pricing.get("output_above_threshold", pricing["output"])
    else:
        input_uncached_rate = pricing["input_uncached"]
        input_cached_rate = pricing["input_cached"]
        output_rate = pricing["output"]

    input_uncached_cost = (uncached_prompt_tokens * input_uncached_rate) / 1_000_000
    input_cached_cost = (cached_tokens * input_cached_rate) / 1_000_000
    output_cost = (candidates_tokens * output_rate) / 1_000_000
    total_cost = input_uncached_cost + input_cached_cost + output_cost

    return CostBreakdown(
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        uncached_prompt_tokens=uncached_prompt_tokens,
        candidates_tokens=candidates_tokens,
        total_tokens=usage.get("total_tokens", prompt_tokens + candidates_tokens),
        input_uncached_cost=input_uncached_cost,
        input_cached_cost=input_cached_cost,
        output_cost=output_cost,
        total_cost=total_cost,
    )


def calculate_flash_cost(usage: dict[str, int]) -> CostBreakdown:
    return calculate_cost(usage, GEMINI_FLASH_PRICING)


@dataclass(slots=True)
class CostTracker:
    """Tracks cumulative costs across multiple turns."""

    model_id: str
    pricing: dict[str, float]
    total_breakdown: CostBreakdown = field(default_factory=CostBreakdown)
    turn_breakdowns: list[CostBreakdown] = field(default_factory=list)

    def add_turn(self, usage: dict[str, int]) -> CostBreakdown:
        turn_cost = calculate_cost(usage, self.pricing)
        self.turn_breakdowns.append(turn_cost)
        self.total_breakdown.prompt_tokens += turn_cost.prompt_tokens
        self.total_breakdown.cached_tokens += turn_cost.cached_tokens
        self.total_breakdown.uncached_prompt_tokens += turn_cost.uncached_prompt_tokens
        self.total_breakdown.candidates_tokens += turn_cost.candidates_tokens
        self.total_breakdown.total_tokens += turn_cost.total_tokens
        self.total_breakdown.input_uncached_cost += turn_cost.input_uncached_cost
        self.total_breakdown.input_cached_cost += turn_cost.input_cached_cost
        self.total_breakdown.output_cost += turn_cost.output_cost
        self.total_breakdown.total_cost += turn_cost.total_cost
        return turn_cost

    def format_cost_summary(self, turn_cost: CostBreakdown | None = None) -> str:
        if turn_cost is None:
            return f"Total cost: ${self.total_breakdown.total_cost:.6f}"
        return (
            f"Turn: ${turn_cost.total_cost:.6f} "
            f"(input: ${turn_cost.input_uncached_cost + turn_cost.input_cached_cost:.6f}, "
            f"output: ${turn_cost.output_cost:.6f}) | "
            f"Cumulative: ${self.total_breakdown.total_cost:.6f}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "total": {
                "tokens": {
                    "prompt_tokens": self.total_breakdown.prompt_tokens,
                    "cached_tokens": self.total_breakdown.cached_tokens,
                    "uncached_prompt_tokens": self.total_breakdown.uncached_prompt_tokens,
                    "candidates_tokens": self.total_breakdown.candidates_tokens,
                    "total_tokens": self.total_breakdown.total_tokens,
                },
                "costs_usd": {
                    "input_uncached": round(self.total_breakdown.input_uncached_cost, 8),
                    "input_cached": round(self.total_breakdown.input_cached_cost, 8),
                    "output": round(self.total_breakdown.output_cost, 8),
                    "total": round(self.total_breakdown.total_cost, 8),
                },
            },
            "pricing": self.pricing,
            "turns": [
                {
                    "tokens": {
                        "prompt_tokens": breakdown.prompt_tokens,
                        "cached_tokens": breakdown.cached_tokens,
                        "uncached_prompt_tokens": breakdown.uncached_prompt_tokens,
                        "candidates_tokens": breakdown.candidates_tokens,
                        "total_tokens": breakdown.total_tokens,
                    },
                    "costs_usd": {
                        "input_uncached": round(breakdown.input_uncached_cost, 8),
                        "input_cached": round(breakdown.input_cached_cost, 8),
                        "output": round(breakdown.output_cost, 8),
                        "total": round(breakdown.total_cost, 8),
                    },
                }
                for breakdown in self.turn_breakdowns
            ],
        }

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def is_flash_model(model_id: str) -> bool:
    return "flash" in model_id.lower()


def is_gemini_3_pro_model(model_id: str) -> bool:
    normalized = (model_id or "").strip().lower()
    return normalized.startswith("gemini-3") and "pro" in normalized


def is_gpt_5_2_model(model_id: str) -> bool:
    return model_id.strip().lower().startswith("gpt-5.2")


def is_gpt_5_3_codex_model(model_id: str) -> bool:
    return model_id.strip().lower().startswith("gpt-5.3-codex")


def is_gpt_5_4_model(model_id: str) -> bool:
    return model_id.strip().lower().startswith("gpt-5.4")


def pricing_for_provider_model(provider: str, model_id: str) -> dict[str, float] | None:
    provider_norm = (provider or "").strip().lower()
    if provider_norm == "gemini" and is_flash_model(model_id):
        return GEMINI_FLASH_PRICING
    if provider_norm == "gemini" and is_gemini_3_pro_model(model_id):
        return GEMINI_3_PRO_PRICING
    if provider_norm == "openai" and is_gpt_5_4_model(model_id):
        return OPENAI_GPT_5_4_PRICING
    if provider_norm == "openai" and (
        is_gpt_5_3_codex_model(model_id) or is_gpt_5_2_model(model_id)
    ):
        return OPENAI_GPT_5_3_CODEX_PRICING
    return None


def parse_max_cost_usd(value: object, *, label: str = "max_cost_usd") -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        amount = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {label}: {value!r}") from exc
    if amount <= 0:
        raise ValueError(f"{label} must be > 0")
    return amount


def max_cost_usd_from_env(env: dict[str, str] | None = None) -> float | None:
    values = os.environ if env is None else env
    return parse_max_cost_usd(values.get(MAX_COST_ENV_VAR), label=MAX_COST_ENV_VAR)
