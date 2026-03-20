from __future__ import annotations

from pathlib import Path

from agent.prompts import (
    DESIGNER_PROMPT_NAME,
    GEMINI_DESIGNER_PROMPT_NAME,
    HYBRID_GEMINI_DESIGNER_PROMPT_NAME,
    HYBRID_OPENAI_DESIGNER_PROMPT_NAME,
    OPENAI_DESIGNER_PROMPT_NAME,
    load_system_prompt_text,
    resolve_system_prompt_path,
)
from agent.runner import build_provider_payload_preview


def test_openai_prompt_resolution_and_payload_preview() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    resolved = resolve_system_prompt_path(
        DESIGNER_PROMPT_NAME,
        provider="openai",
        repo_root=repo_root,
    )
    assert resolved.name == OPENAI_DESIGNER_PROMPT_NAME

    loaded_path, loaded_text = load_system_prompt_text(
        DESIGNER_PROMPT_NAME,
        provider="openai",
        repo_root=repo_root,
    )
    assert loaded_path == resolved
    assert loaded_text == resolved.read_text(encoding="utf-8")

    hybrid_resolved = resolve_system_prompt_path(
        DESIGNER_PROMPT_NAME,
        provider="openai",
        sdk_package="sdk_hybrid",
        repo_root=repo_root,
    )
    assert hybrid_resolved.name == HYBRID_OPENAI_DESIGNER_PROMPT_NAME

    payload = build_provider_payload_preview(
        "a pair of scissors",
        provider="openai",
        model_id="gpt-5.4",
        thinking_level="high",
        system_prompt_path=DESIGNER_PROMPT_NAME,
    )
    instructions = payload["instructions"]
    docs_message = payload["input"][0]["content"][0]["text"]

    assert "<tool_contract>" in instructions
    assert "<feedback_strategy>" in instructions
    assert "<failure_diagnosis>" in instructions
    assert "<modeling_priority>" in instructions
    assert "Use ONLY `read_file` and `apply_patch`" in instructions
    assert "FREEFORM tool" in instructions
    assert "write_code" not in instructions
    assert "Do NOT provide `file_path`" in instructions
    assert "<compile_signals>" in instructions
    assert "wrong geometric representation" in instructions
    assert "prompt-named visible features" in instructions
    assert "silhouette-critical visible forms" in instructions
    assert "If the real object should be hollow, thin-walled, or cavity-bearing" in instructions
    assert "Do not omit important internal structures" in instructions
    assert "## sdk/_docs/common/00_quickstart.md" in docs_message
    assert "## sdk/_docs/common/80_testing.md" in docs_message


def test_openai_hybrid_payload_preview_includes_hybrid_docs() -> None:
    hybrid_docs_message = build_provider_payload_preview(
        "a pair of scissors",
        provider="openai",
        model_id="gpt-5.4",
        thinking_level="high",
        system_prompt_path=DESIGNER_PROMPT_NAME,
        sdk_package="sdk_hybrid",
        sdk_docs_mode="core",
    )["input"][0]["content"][0]["text"]
    assert "## sdk/_docs/common/00_quickstart.md" in hybrid_docs_message
    assert "## sdk/_docs/cadquery/35_cadquery.md" in hybrid_docs_message
    assert "## sdk/_docs/common/80_testing.md" in hybrid_docs_message


def test_gemini_prompt_resolution_and_payload_preview() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    gemini_resolved = resolve_system_prompt_path(
        DESIGNER_PROMPT_NAME,
        provider="gemini",
        repo_root=repo_root,
    )
    assert gemini_resolved.name == GEMINI_DESIGNER_PROMPT_NAME

    gemini_hybrid_resolved = resolve_system_prompt_path(
        DESIGNER_PROMPT_NAME,
        provider="gemini",
        sdk_package="sdk_hybrid",
        repo_root=repo_root,
    )
    assert gemini_hybrid_resolved.name == HYBRID_GEMINI_DESIGNER_PROMPT_NAME

    gemini_payload = build_provider_payload_preview(
        "a pair of scissors",
        provider="gemini",
        model_id="gemini-2.5-pro",
        thinking_level="high",
        system_prompt_path=DESIGNER_PROMPT_NAME,
    )
    gemini_instructions = gemini_payload["config"]["system_instruction"]
    assert "<tool_contract>" in gemini_instructions
    assert "<feedback_strategy>" in gemini_instructions
    assert "<compile_signals>" in gemini_instructions
    assert "Use ONLY `read_code` and `edit_code`" in gemini_instructions
    assert 'old_string=""' in gemini_instructions
    assert "write_code" not in gemini_instructions
    assert "wrong geometric representation" in gemini_instructions
    assert "prompt-named visible features" in gemini_instructions
    assert "silhouette-critical visible forms" in gemini_instructions
    assert (
        "If the real object should be hollow, thin-walled, or cavity-bearing" in gemini_instructions
    )
    assert "Do not omit important internal structures" in gemini_instructions
