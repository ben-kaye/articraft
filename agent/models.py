from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class TerminateReason(StrEnum):
    """Reasons the agent runtime can terminate."""

    GOAL_COMPLETE = "GOAL_COMPLETE"
    CODE_VALID = "CODE_VALID"
    MAX_TURNS = "MAX_TURNS"
    ERROR = "ERROR"


@dataclass(slots=True)
class AgentResult:
    """Result from a single agent run."""

    success: bool
    reason: TerminateReason
    message: str
    conversation: list[dict[str, Any]]
    final_code: str | None = None
    urdf_xml: str | None = None
    compile_warnings: list[str] = field(default_factory=list)
    turn_count: int = 0
    tool_call_count: int = 0
    compile_attempt_count: int = 0
    usage: dict[str, int] | None = None


@dataclass(slots=True, frozen=True)
class CompileReport:
    """Compile result plus non-blocking warnings."""

    urdf_xml: str
    warnings: list[str]
    test_report: object | None = None


@dataclass(slots=True, frozen=True)
class PromptPreviewRequest:
    """Request used to build a provider payload preview."""

    user_content: Any
    provider: str
    model_id: str
    thinking_level: str
    system_prompt_path: str
    sdk_package: str = "sdk"
    sdk_docs_mode: str = "full"
    openai_transport: str = "http"
    openai_reasoning_summary: str | None = "auto"


@dataclass(slots=True, frozen=True)
class SessionPaths:
    """Filesystem paths bound to a single run."""

    script_path: Path
    trace_dir: Path
    checkpoint_urdf_path: Path | None = None
