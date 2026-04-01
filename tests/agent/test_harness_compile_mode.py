from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import agent.harness as harness
from agent.feedback import build_compile_signal_bundle
from agent.harness import ArticraftAgent
from agent.models import CompileReport, TerminateReason


def test_compile_async_uses_timeout_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = ArticraftAgent.__new__(ArticraftAgent)
    agent.file_path = str(tmp_path / "model.py")
    agent.sdk_package = "sdk_hybrid"
    agent.runtime_limits = None

    report = CompileReport(
        urdf_xml="<robot />",
        warnings=[],
        signal_bundle=build_compile_signal_bundle(status="success"),
    )
    captured: dict[str, object] = {}

    def fake_compile(
        script_path: Path,
        *,
        sdk_package: str,
        rewrite_visual_glb: bool,
    ) -> CompileReport:
        captured["script_path"] = script_path
        captured["sdk_package"] = sdk_package
        captured["rewrite_visual_glb"] = rewrite_visual_glb
        return report

    monkeypatch.setattr(harness, "compile_urdf_report_maybe_timeout", fake_compile)

    result = asyncio.run(agent._compile_urdf_report_async())

    assert result is report
    assert captured == {
        "script_path": tmp_path / "model.py",
        "sdk_package": "sdk_hybrid",
        "rewrite_visual_glb": False,
    }


def test_execute_compile_model_reuses_cached_success_for_current_revision() -> None:
    agent = ArticraftAgent.__new__(ArticraftAgent)
    agent._current_edit_revision = 2
    agent._last_successful_compile_revision = None
    agent._last_successful_compile_report = None
    agent._compile_attempt_count = 0
    agent._last_compile_failure_sig = None
    agent._consecutive_compile_failure_count = 0
    agent._last_checkpoint_urdf_sig = None
    agent.checkpoint_urdf_path = None

    report = CompileReport(
        urdf_xml="<robot />",
        warnings=[],
        signal_bundle=build_compile_signal_bundle(status="success"),
    )
    compile_calls = 0

    async def fake_compile() -> CompileReport:
        nonlocal compile_calls
        compile_calls += 1
        return report

    async def fake_persist(_: str) -> None:
        return None

    agent._compile_urdf_report_async = fake_compile
    agent._persist_compile_success_checkpoint_async = fake_persist

    first = asyncio.run(agent._execute_compile_model(tool_call_id="call_1"))
    second = asyncio.run(agent._execute_compile_model(tool_call_id="call_2"))

    assert compile_calls == 1
    assert agent._compile_attempt_count == 1
    assert agent._last_successful_compile_revision == 2
    assert first.output == second.output
    assert first.compilation == {"status": "success", "error": None}
    assert second.compilation == {"status": "success", "error": None}


def test_execute_compile_model_failure_leaves_latest_revision_stale() -> None:
    agent = ArticraftAgent.__new__(ArticraftAgent)
    agent._current_edit_revision = 1
    agent._last_successful_compile_revision = 0
    agent._last_successful_compile_report = CompileReport(
        urdf_xml="<robot old='1' />",
        warnings=[],
        signal_bundle=build_compile_signal_bundle(status="success"),
    )
    agent._compile_attempt_count = 0
    agent._last_compile_failure_sig = None
    agent._consecutive_compile_failure_count = 0
    agent._last_checkpoint_urdf_sig = None
    agent.checkpoint_urdf_path = None

    async def fake_compile() -> CompileReport:
        raise RuntimeError("ValueError: bad loft")

    async def fake_persist_failure(_: BaseException) -> bool:
        return False

    agent._compile_urdf_report_async = fake_compile
    agent._persist_compile_failure_checkpoint_async = fake_persist_failure

    result = asyncio.run(agent._execute_compile_model(tool_call_id="call_1"))

    assert agent._compile_attempt_count == 1
    assert agent._last_successful_compile_revision == 0
    assert agent._latest_code_is_fresh() is False
    assert result.compilation == {
        "status": "error",
        "error": "status=failure failures=1 warnings=0 notes=0\nPrimary issue: compile execution failed.",
    }
    assert "<compile_signals>" in str(result.output)
    assert "bad loft" in str(result.output)


def test_mark_code_mutated_invalidates_fresh_compile_and_resets_audit() -> None:
    agent = ArticraftAgent.__new__(ArticraftAgent)
    agent._current_edit_revision = 3
    agent._last_successful_compile_revision = 3
    agent._last_successful_compile_report = CompileReport(
        urdf_xml="<robot />",
        warnings=[],
        signal_bundle=build_compile_signal_bundle(status="success"),
    )
    agent._post_success_design_audit_sent = True

    agent._mark_code_mutated("edit_code")

    assert agent._current_edit_revision == 4
    assert agent._latest_code_is_fresh() is False
    assert agent._post_success_design_audit_sent is False


def test_run_requires_compile_model_before_concluding_and_delays_design_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _SequenceLLM:
        model_id = "gemini-2.5-pro"

        def __init__(self, *args: object, **kwargs: object) -> None:
            self._responses = [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_edit",
                            "type": "function",
                            "function": {
                                "name": "edit_code",
                                "arguments": json.dumps(
                                    {
                                        "old_string": '"draft_model"',
                                        "new_string": '"draft_model_v2"',
                                        "replace_all": False,
                                    }
                                ),
                            },
                        }
                    ],
                },
                {"content": "Done.", "tool_calls": []},
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_compile",
                            "type": "function",
                            "function": {"name": "compile_model", "arguments": "{}"},
                        }
                    ],
                },
                {"content": "Done.", "tool_calls": []},
                {"content": "Done.", "tool_calls": []},
            ]

        async def generate_with_tools(
            self, *, system_prompt: str, messages: list[dict], tools: list[dict]
        ) -> dict:
            assert tools
            return self._responses.pop(0)

        async def close(self) -> None:
            return None

    report = CompileReport(
        urdf_xml="<robot />",
        warnings=[],
        signal_bundle=build_compile_signal_bundle(status="success"),
    )

    monkeypatch.setattr(harness, "GeminiLLM", _SequenceLLM)
    agent = ArticraftAgent(
        file_path=str(tmp_path / "model.py"),
        provider="gemini",
        max_turns=6,
        display_enabled=False,
    )

    async def fake_compile() -> CompileReport:
        return report

    async def fake_persist(_: str) -> None:
        return None

    agent._compile_urdf_report_async = fake_compile
    agent._persist_compile_success_checkpoint_async = fake_persist

    result = asyncio.run(agent.run("make a hinge"))

    assert result.success is True
    assert result.reason == TerminateReason.CODE_VALID
    assert result.compile_attempt_count == 1
    assert result.tool_call_count == 2

    user_messages = [
        str(message.get("content", ""))
        for message in result.conversation
        if message.get("role") == "user"
    ]
    assert any("<compile_required>" in content for content in user_messages)
    assert any("<design_audit>" in content for content in user_messages)

    compile_tool_messages = [
        message
        for message in result.conversation
        if message.get("role") == "tool" and message.get("name") == "compile_model"
    ]
    assert len(compile_tool_messages) == 1
    compile_payload = json.loads(compile_tool_messages[0]["content"])
    assert "Compile passed cleanly." in compile_payload["result"]

    compile_index = result.conversation.index(compile_tool_messages[0])
    audit_index = next(
        index
        for index, message in enumerate(result.conversation)
        if message.get("role") == "user" and "<design_audit>" in str(message.get("content", ""))
    )
    assert audit_index > compile_index + 1
