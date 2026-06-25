"""Compile a generated model.py -> URDF, in an isolated subprocess.

Returns a CompileResult the harness can act on, plus a feedback string for the LLM.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .feedback import classify_failure, format_feedback, source_of


@dataclass
class CompileResult:
    ok: bool  # compiled to URDF without raising
    passed: bool  # ok AND run_tests() had no failures
    urdf_xml: str | None = None
    error: str | None = None
    traceback: str | None = None
    failures: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    allowances: list[str] = field(default_factory=list)  # explicit allow_*() calls, echoed as notes
    allowed_isolated_parts: list[str] = field(default_factory=list)

    @property
    def feedback(self) -> str:
        return format_feedback(self)


def compile_model(
    model_path: Path | str, *, repo_root: Path | str, timeout: float = 180.0
) -> CompileResult:
    model_path = Path(model_path)
    urdf_out = model_path.with_suffix(".urdf")
    urdf_out.unlink(missing_ok=True)  # don't let a stale URDF survive a failing compile
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "agent._compile_worker",
                str(model_path),
                str(urdf_out),
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CompileResult(ok=False, passed=False, error=f"compile timed out after {timeout}s")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # worker crashed (e.g. segfault) before emitting JSON
        err = (proc.stderr or "compile subprocess crashed").strip()[-2000:]
        return CompileResult(
            ok=False, passed=False, error="compile subprocess crashed", traceback=err
        )

    report = data.get("report") or {}
    failures = report.get("failures", [])
    for fa in failures:  # tag (kind, group, source) so the trace carries comparable categories
        fa["kind"], fa["group"] = classify_failure(fa.get("name", ""))
        fa["source"] = source_of(fa["kind"])
    return CompileResult(
        ok=data["ok"],
        passed=data["ok"] and report.get("passed", True) and not failures,
        # Surface the URDF whenever geometry compiled, even if run_tests() failed or raised,
        # so the viewer can render QC-failing models.
        urdf_xml=urdf_out.read_text(encoding="utf-8")
        if data.get("urdf_written") and urdf_out.exists()
        else None,
        error=data.get("error"),
        traceback=data.get("traceback"),
        failures=failures,
        warnings=report.get("warnings", []),
        allowances=report.get("allowances", []),
        allowed_isolated_parts=report.get("allowed_isolated_parts", []),
    )
