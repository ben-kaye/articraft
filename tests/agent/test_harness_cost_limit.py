from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agent.cost import CostTracker
from agent.harness import ArticraftAgent
from agent.models import TerminateReason


class _DummyDisplay:
    def start(self) -> None:
        return None

    def start_turn(self, turn_number: int) -> None:
        return None

    def start_llm_wait(self) -> None:
        return None

    def stop_llm_wait(self) -> None:
        return None

    def add_llm_call(self, tokens: dict, cost: float, duration: float) -> None:
        return None

    def add_thinking_summary(self, summary: str) -> None:
        return None

    def end_turn(self, success: bool, error: str | None = None) -> None:
        return None


class _DummyRegistry:
    def get_tool_schemas(self) -> list[dict]:
        return []


class _SingleResponseLLM:
    model_id = "gpt-5.4"

    async def generate_with_tools(
        self, system_prompt: str, messages: list[dict], tools: list[dict]
    ) -> dict:
        return {
            "usage": {
                "prompt_tokens": 10000,
                "cached_tokens": 0,
                "candidates_tokens": 5000,
                "total_tokens": 15000,
            }
        }

    async def close(self) -> None:
        return None


def test_harness_cost_limit_trips_and_persists_cost_json(tmp_path: Path) -> None:
    agent = ArticraftAgent.__new__(ArticraftAgent)
    agent.file_path = str(tmp_path / "model.py")
    agent.max_turns = 3
    agent.sdk_package = "sdk"
    agent.scaffold_mode = "lite"
    agent.sdk_docs_mode = "full"
    agent.runtime_limits = None
    agent._seen_compile_signal_sigs = set()
    agent._seen_tool_error_sigs = set()
    agent._seen_find_example_paths = set()
    agent._last_compile_failure_sig = None
    agent._consecutive_compile_failure_count = 0
    agent._post_success_design_audit_sent = False
    agent._post_success_design_audit_enabled = True
    agent.checkpoint_urdf_path = None
    agent.trace_writer = None
    agent.provider = "openai"
    agent.llm = _SingleResponseLLM()
    agent.tool_registry = _DummyRegistry()
    agent.on_turn_start = None
    agent.display = _DummyDisplay()
    agent.loaded_system_prompt_path = "designer_system_prompt_openai.txt"
    agent.system_prompt = "system"
    agent.sdk_docs_context = ""
    agent.cost_tracker = CostTracker(
        model_id="gpt-5.4",
        pricing={"input_uncached": 2.5, "input_cached": 0.25, "output": 15.0},
    )
    agent.max_cost_usd = 0.01
    agent._ensure_code_file = lambda: Path(agent.file_path).write_text(
        "# draft\n", encoding="utf-8"
    )

    result = asyncio.run(agent.run("make a hinge"))

    assert result.success is False
    assert result.reason == TerminateReason.COST_LIMIT
    assert "Cost limit exceeded after turn 1" in result.message

    cost_path = tmp_path / "cost.json"
    assert cost_path.exists()
    payload = json.loads(cost_path.read_text(encoding="utf-8"))
    assert payload["total"]["costs_usd"]["total"] > 0.01
