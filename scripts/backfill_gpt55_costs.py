from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.cost import OPENAI_GPT_5_5_PRICING, CostBreakdown, calculate_cost


@dataclass(slots=True)
class BackfillSummary:
    scanned_cost_files: int = 0
    gpt55_cost_files: int = 0
    rewritten_cost_files: int = 0
    skipped: Counter[str] | None = None
    old_total_usd: float = 0.0
    new_total_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.skipped is None:
            self.skipped = Counter()


def _is_gpt55_model(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith("gpt-5.5")


def _coerce_usage(tokens: Any) -> dict[str, int] | None:
    if not isinstance(tokens, dict):
        return None

    usage: dict[str, int] = {}
    for key in ("prompt_tokens", "cached_tokens", "candidates_tokens", "total_tokens"):
        value = tokens.get(key)
        if not isinstance(value, int):
            return None
        usage[key] = value
    return usage


def _tokens_dict(breakdown: CostBreakdown) -> dict[str, int]:
    return {
        "prompt_tokens": breakdown.prompt_tokens,
        "cached_tokens": breakdown.cached_tokens,
        "uncached_prompt_tokens": breakdown.uncached_prompt_tokens,
        "candidates_tokens": breakdown.candidates_tokens,
        "total_tokens": breakdown.total_tokens,
    }


def _costs_dict(breakdown: CostBreakdown) -> dict[str, float]:
    return {
        "input_uncached": round(breakdown.input_uncached_cost, 8),
        "input_cached": round(breakdown.input_cached_cost, 8),
        "output": round(breakdown.output_cost, 8),
        "total": round(breakdown.total_cost, 8),
    }


def _empty_breakdown() -> CostBreakdown:
    return CostBreakdown()


def _add_breakdown(total: CostBreakdown, item: CostBreakdown) -> None:
    total.prompt_tokens += item.prompt_tokens
    total.cached_tokens += item.cached_tokens
    total.uncached_prompt_tokens += item.uncached_prompt_tokens
    total.candidates_tokens += item.candidates_tokens
    total.total_tokens += item.total_tokens
    total.input_uncached_cost += item.input_uncached_cost
    total.input_cached_cost += item.input_cached_cost
    total.output_cost += item.output_cost
    total.total_cost += item.total_cost


def _breakdown_payload(breakdown: CostBreakdown) -> dict[str, object]:
    return {
        "tokens": _tokens_dict(breakdown),
        "costs_usd": _costs_dict(breakdown),
    }


def _rewrite_billable_node(node: Any) -> tuple[dict[str, object] | None, CostBreakdown | None]:
    if not isinstance(node, dict):
        return None, None

    usage = _coerce_usage(node.get("tokens"))
    if usage is None:
        return None, None

    breakdown = calculate_cost(usage, OPENAI_GPT_5_5_PRICING)
    rewritten = dict(node)
    rewritten["tokens"] = _tokens_dict(breakdown)
    rewritten["costs_usd"] = _costs_dict(breakdown)
    return rewritten, breakdown


def _rewrite_cost_payload(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "payload is not an object"
    if not _is_gpt55_model(payload.get("model_id")):
        return None, "model is not gpt-5.5"

    turns = payload.get("turns")
    if not isinstance(turns, list) or not turns:
        return None, "missing turns"

    rewritten_turns: list[dict[str, object]] = []
    turn_total = _empty_breakdown()
    for turn in turns:
        rewritten_turn, breakdown = _rewrite_billable_node(turn)
        if rewritten_turn is None or breakdown is None:
            return None, "turn is missing complete token data"
        rewritten_turns.append(rewritten_turn)
        _add_breakdown(turn_total, breakdown)

    rewritten_events: list[Any] = []
    maintenance_total = _empty_breakdown()
    maintenance_events = payload.get("maintenance_events")
    if isinstance(maintenance_events, list):
        for event in maintenance_events:
            if not isinstance(event, dict):
                rewritten_events.append(event)
                continue
            if event.get("tokens") is None and event.get("costs_usd") is None:
                rewritten_events.append(dict(event))
                continue
            rewritten_event, breakdown = _rewrite_billable_node(event)
            if rewritten_event is None or breakdown is None:
                return None, "maintenance event is missing complete token data"
            rewritten_events.append(rewritten_event)
            _add_breakdown(maintenance_total, breakdown)

    all_in_total = _empty_breakdown()
    _add_breakdown(all_in_total, turn_total)
    _add_breakdown(all_in_total, maintenance_total)

    rewritten = dict(payload)
    rewritten["total"] = _breakdown_payload(turn_total)
    rewritten["maintenance_total"] = _breakdown_payload(maintenance_total)
    rewritten["all_in_total"] = _breakdown_payload(all_in_total)
    rewritten["pricing"] = dict(OPENAI_GPT_5_5_PRICING)
    rewritten["turns"] = rewritten_turns
    rewritten["maintenance_events"] = rewritten_events
    return rewritten, None


def _total_cost_usd(payload: Any) -> float:
    if not isinstance(payload, dict):
        return 0.0
    total = payload.get("total")
    if not isinstance(total, dict):
        return 0.0
    costs = total.get("costs_usd")
    if not isinstance(costs, dict):
        return 0.0
    value = costs.get("total")
    return float(value) if isinstance(value, (int, float)) else 0.0


def backfill_gpt55_costs(repo_root: Path, *, dry_run: bool = False) -> BackfillSummary:
    summary = BackfillSummary()
    data_root = repo_root / "data"
    if not data_root.exists():
        return summary

    for cost_path in sorted(data_root.rglob("cost.json")):
        summary.scanned_cost_files += 1
        payload = json.loads(cost_path.read_text(encoding="utf-8"))
        if _is_gpt55_model(payload.get("model_id") if isinstance(payload, dict) else None):
            summary.gpt55_cost_files += 1

        rewritten, skip_reason = _rewrite_cost_payload(payload)
        if rewritten is None:
            if skip_reason != "model is not gpt-5.5":
                summary.skipped[skip_reason or "unknown"] += 1
            continue

        summary.old_total_usd += _total_cost_usd(payload)
        summary.new_total_usd += _total_cost_usd(rewritten)
        if rewritten == payload:
            continue

        summary.rewritten_cost_files += 1
        if not dry_run:
            cost_path.write_text(json.dumps(rewritten, indent=2) + "\n", encoding="utf-8")

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backfill_gpt55_costs.py")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    summary = backfill_gpt55_costs(args.repo_root.resolve(), dry_run=args.dry_run)
    print(
        json.dumps(
            {
                "scanned_cost_files": summary.scanned_cost_files,
                "gpt55_cost_files": summary.gpt55_cost_files,
                "rewritten_cost_files": summary.rewritten_cost_files,
                "skipped": dict(summary.skipped or {}),
                "old_total_usd": round(summary.old_total_usd, 8),
                "new_total_usd": round(summary.new_total_usd, 8),
                "delta_total_usd": round(summary.new_total_usd - summary.old_total_usd, 8),
                "dry_run": args.dry_run,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
