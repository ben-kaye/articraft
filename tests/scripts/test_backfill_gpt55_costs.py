from __future__ import annotations

import json

from scripts.backfill_gpt55_costs import backfill_gpt55_costs


def test_backfill_gpt55_costs_rewrites_pricing_and_costs(tmp_path) -> None:
    cost_path = tmp_path / "data" / "records" / "rec_001" / "cost.json"
    cost_path.parent.mkdir(parents=True)
    cost_path.write_text(
        json.dumps(
            {
                "model_id": "gpt-5.5-2026-04-23",
                "total": {
                    "tokens": {
                        "prompt_tokens": 300_000,
                        "cached_tokens": 100_000,
                        "uncached_prompt_tokens": 200_000,
                        "candidates_tokens": 10_000,
                        "total_tokens": 310_000,
                    },
                    "costs_usd": {
                        "input_uncached": 1.0,
                        "input_cached": 0.05,
                        "output": 0.225,
                        "total": 1.275,
                    },
                },
                "maintenance_total": {
                    "tokens": {
                        "prompt_tokens": 0,
                        "cached_tokens": 0,
                        "uncached_prompt_tokens": 0,
                        "candidates_tokens": 0,
                        "total_tokens": 0,
                    },
                    "costs_usd": {
                        "input_uncached": 0.0,
                        "input_cached": 0.0,
                        "output": 0.0,
                        "total": 0.0,
                    },
                },
                "all_in_total": {
                    "tokens": {
                        "prompt_tokens": 300_000,
                        "cached_tokens": 100_000,
                        "uncached_prompt_tokens": 200_000,
                        "candidates_tokens": 10_000,
                        "total_tokens": 310_000,
                    },
                    "costs_usd": {
                        "input_uncached": 1.0,
                        "input_cached": 0.05,
                        "output": 0.225,
                        "total": 1.275,
                    },
                },
                "pricing": {
                    "input_uncached": 2.5,
                    "input_cached": 0.25,
                    "output": 15.0,
                    "prompt_tier_threshold_tokens": 272_000,
                    "input_uncached_above_threshold": 5.0,
                    "input_cached_above_threshold": 0.5,
                    "output_above_threshold": 22.5,
                },
                "turns": [
                    {
                        "tokens": {
                            "prompt_tokens": 300_000,
                            "cached_tokens": 100_000,
                            "uncached_prompt_tokens": 200_000,
                            "candidates_tokens": 10_000,
                            "total_tokens": 310_000,
                        },
                        "costs_usd": {
                            "input_uncached": 1.0,
                            "input_cached": 0.05,
                            "output": 0.225,
                            "total": 1.275,
                        },
                    }
                ],
                "maintenance_events": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = backfill_gpt55_costs(tmp_path)

    assert summary.gpt55_cost_files == 1
    assert summary.rewritten_cost_files == 1
    assert summary.old_total_usd == 1.275
    assert summary.new_total_usd == 2.55

    rewritten = json.loads(cost_path.read_text(encoding="utf-8"))
    assert rewritten["pricing"]["input_uncached"] == 5.0
    assert rewritten["pricing"]["input_uncached_above_threshold"] == 10.0
    assert rewritten["turns"][0]["costs_usd"] == {
        "input_uncached": 2.0,
        "input_cached": 0.1,
        "output": 0.45,
        "total": 2.55,
    }
    assert rewritten["total"]["costs_usd"]["total"] == 2.55
    assert rewritten["all_in_total"]["costs_usd"]["total"] == 2.55


def test_backfill_gpt55_costs_dry_run_leaves_file_unchanged(tmp_path) -> None:
    cost_path = tmp_path / "data" / "records" / "rec_001" / "cost.json"
    cost_path.parent.mkdir(parents=True)
    original = {
        "model_id": "gpt-5.5-2026-04-23",
        "pricing": {"input_uncached": 2.5},
        "turns": [
            {
                "tokens": {
                    "prompt_tokens": 1_000,
                    "cached_tokens": 0,
                    "uncached_prompt_tokens": 1_000,
                    "candidates_tokens": 100,
                    "total_tokens": 1_100,
                },
                "costs_usd": {
                    "input_uncached": 0.0025,
                    "input_cached": 0.0,
                    "output": 0.0015,
                    "total": 0.004,
                },
            }
        ],
        "maintenance_events": [],
    }
    cost_path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    summary = backfill_gpt55_costs(tmp_path, dry_run=True)

    assert summary.rewritten_cost_files == 1
    assert json.loads(cost_path.read_text(encoding="utf-8")) == original
