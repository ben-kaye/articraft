from __future__ import annotations

from agent.feedback import build_compile_signal_bundle
from agent.harness import ArticraftAgent


def test_compile_failure_signal_message_has_structured_sections() -> None:
    agent = ArticraftAgent.__new__(ArticraftAgent)
    agent._last_compile_failure_sig = None
    agent._consecutive_compile_failure_count = 0
    agent.trace_writer = None

    conversation: list[dict] = []
    content = agent._append_compile_failure_signals(
        conversation,
        bundle=build_compile_signal_bundle(
            status="failure",
            exc=RuntimeError("ValueError: bad loft"),
        ),
    )

    assert "<compile_signals>" in content
    assert "<summary>" in content
    assert "<failures>" in content
    assert "<response_rules>" in content
    assert "compile execution failed" in content
    assert "Failures are blocking and should be investigated." in content
    assert "assembly requires a gap" in content
    assert "Warnings are possible issues and should not be ignored" in content
    assert "use probe_model or exact checks" in content
    assert conversation


def test_repeated_compile_failure_signal_message_escalates_to_rewrite() -> None:
    agent = ArticraftAgent.__new__(ArticraftAgent)
    agent._last_compile_failure_sig = None
    agent._consecutive_compile_failure_count = 0
    agent.trace_writer = None

    bundle = build_compile_signal_bundle(
        status="failure",
        exc=RuntimeError("ValueError: bad loft"),
    )
    conversation: list[dict] = []
    agent._append_compile_failure_signals(conversation, bundle=bundle)
    content = agent._append_compile_failure_signals(conversation, bundle=bundle)

    assert "This failure matches the previous compile attempt." in content
    assert "This failure class repeated." in content
    assert "rewrite the affected region from the root cause" in content


def test_compile_failure_streak_escalates_even_when_signature_changes() -> None:
    agent = ArticraftAgent.__new__(ArticraftAgent)
    agent._last_compile_failure_sig = None
    agent._consecutive_compile_failure_count = 0
    agent.trace_writer = None

    conversation: list[dict] = []
    for message in ("ValueError: bad loft", "ValueError: bad overlap", "ValueError: bad spinner"):
        content = agent._append_compile_failure_signals(
            conversation,
            bundle=build_compile_signal_bundle(
                status="failure",
                exc=RuntimeError(message),
            ),
        )

    assert "This is compile failure 3 in a row." in content
    assert "You are in a repair loop." in content
