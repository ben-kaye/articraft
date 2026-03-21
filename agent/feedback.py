from __future__ import annotations

import hashlib
import linecache
import re
import traceback
from typing import Iterable

from agent.models import CompileSignal, CompileSignalBundle

CODE_PATTERN = re.compile(
    r"```(?:python)?\s*\n"
    r"|^(?:from\s+\w+\s+import\s|import\s+\w+|def\s+\w+\s*\(|class\s+\w+)",
    re.MULTILINE,
)
LOFT_PROFILE_AREA_ERROR = "Loft profile area must be non-zero"
LOFT_PROFILE_AREA_HINT = (
    "Hint: LoftGeometry checks profile area in the XY projection. "
    "Use closed loops like `(x_i, y_i, z_const)`. "
    "If you need an XZ/YZ section, author it in XY first and rotate the mesh afterward."
)


def contains_code_in_text(text: str) -> bool:
    """Check if a model text response pasted code instead of using tools."""
    if not text:
        return False
    return bool(CODE_PATTERN.search(text))


def _compile_hint_lines(detail_lines: list[str]) -> list[str]:
    if any(LOFT_PROFILE_AREA_ERROR in line for line in detail_lines):
        return [LOFT_PROFILE_AREA_HINT]
    return []


def _exception_detail_lines(exc: BaseException, *, max_detail_lines: int = 40) -> list[str]:
    raw_message = str(exc).strip()
    if raw_message:
        tb_marker = "Traceback (most recent call last):"
        marker_idx = raw_message.find(tb_marker)
        if marker_idx >= 0:
            raw_message = raw_message[:marker_idx].rstrip()

    detail_lines: list[str] = []
    seen: set[str] = set()
    for line in raw_message.splitlines():
        cleaned = line.rstrip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        detail_lines.append(cleaned)

    warnings = getattr(exc, "warnings", None)
    if isinstance(warnings, list):
        for warning in warnings:
            cleaned = str(warning).strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            detail_lines.append(cleaned)

    if len(detail_lines) > max_detail_lines:
        omitted = len(detail_lines) - max_detail_lines
        detail_lines = detail_lines[:max_detail_lines]
        detail_lines.append(f"... ({omitted} more lines)")

    for hint in _compile_hint_lines(detail_lines):
        if hint not in seen:
            detail_lines.append(hint)
            seen.add(hint)
    return detail_lines


def _exception_location_lines(exc: BaseException) -> list[str]:
    extracted = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    skip_wrapper_location = isinstance(exc, RuntimeError)
    if not extracted or skip_wrapper_location:
        return []

    last = extracted[-1]
    location = f"{last.filename}:{last.lineno}"
    lines = [f"Location: {location}"]
    raw_line = linecache.getline(last.filename, last.lineno).rstrip("\n")
    if raw_line.strip():
        lines.append(f"Code: {raw_line}")
    return lines


def _make_signal(
    *,
    severity: str,
    kind: str,
    code: str,
    summary: str,
    details: str = "",
    blocking: bool = False,
    source: str = "compiler",
    group: str = "qc",
    check_name: str | None = None,
) -> CompileSignal:
    sig_src = "\n".join(
        [
            severity,
            kind,
            code,
            summary,
            details,
            str(blocking),
            source,
            group,
            check_name or "",
        ]
    ).encode("utf-8")
    return CompileSignal(
        severity=severity,  # type: ignore[arg-type]
        kind=kind,
        code=code,
        summary=summary,
        details=details,
        blocking=blocking,
        source=source,  # type: ignore[arg-type]
        group=group,  # type: ignore[arg-type]
        check_name=check_name,
        dedupe_key=hashlib.sha1(sig_src).hexdigest(),
    )


def _warning_signal_from_text(warning: str) -> CompileSignal:
    text = str(warning).strip()
    if not text:
        return _make_signal(
            severity="warning",
            kind="compiler_warning",
            code="WARN_COMPILER",
            summary="Compiler emitted a warning.",
        )

    lines = text.splitlines()
    headline = lines[0]
    details = "\n".join(lines[1:]).strip()

    if "non-finite or absurd geometry dimensions detected" in text:
        return _make_signal(
            severity="warning",
            kind="geometry_scale",
            code="WARN_GEOMETRY_ABSURD",
            summary="Non-finite or absurd geometry dimensions detected.",
            details=details,
            group="design",
        )
    if "geometry outlier dimensions detected" in text:
        return _make_signal(
            severity="warning",
            kind="geometry_scale",
            code="WARN_GEOMETRY_OUTLIER",
            summary="Geometry outlier dimensions detected.",
            details=details,
            group="design",
        )
    if "visual connectivity check failed" in text:
        return _make_signal(
            severity="warning",
            kind="visual_connectivity",
            code="WARN_VISUAL_CONNECTIVITY",
            summary="Visual connectivity check failed.",
            details=details,
            group="design",
        )
    if "visual/collision geometry appear misaligned" in text:
        return _make_signal(
            severity="warning",
            kind="visual_collision_misalignment",
            code="WARN_VISUAL_COLLISION_MISALIGNMENT",
            summary="Visual and collision geometry appear misaligned on some links.",
            details=details,
            group="design",
        )
    if "isolated parts detected" in text:
        summary = "Isolated parts detected."
        if "(visual" in headline or "(visual," in headline:
            summary = "Isolated visual parts detected."
        elif "(collision" in headline or "(collision," in headline:
            summary = "Isolated collision parts detected."
        return _make_signal(
            severity="warning",
            kind="isolated_part",
            code="WARN_ISOLATED_PART",
            summary=summary,
            details=details,
            group="design",
        )
    if "geometry overlap check reported overlaps" in text:
        return _make_signal(
            severity="warning",
            kind="geometry_overlap",
            code="WARN_GEOMETRY_OVERLAP",
            summary="Geometry overlap check reported overlaps.",
            details=details,
            group="qc",
        )
    if "cwd-relative asset paths detected" in text:
        return _make_signal(
            severity="warning",
            kind="path_hygiene",
            code="WARN_CWD_RELATIVE_ASSET_PATH",
            summary="cwd-relative asset paths detected.",
            details=details,
            group="hygiene",
        )
    return _make_signal(
        severity="warning",
        kind="compiler_warning",
        code="WARN_COMPILER",
        summary=headline.replace("IMPORTANT: ", "").strip(),
        details=details,
    )


def _iter_test_failures(test_report: object | None) -> Iterable[CompileSignal]:
    failures = getattr(test_report, "failures", None)
    if not isinstance(failures, tuple):
        return ()

    signals: list[CompileSignal] = []
    for failure in failures:
        name = str(getattr(failure, "name", "unknown"))
        details = str(getattr(failure, "details", "")).strip()
        signals.append(
            _make_signal(
                severity="failure",
                kind="test_failure",
                code="TEST_FAILURE",
                summary=name,
                details=details,
                blocking=True,
                source="tests",
                group="qc",
                check_name=name,
            )
        )
    return signals


def _iter_test_warnings(test_report: object | None) -> Iterable[CompileSignal]:
    warnings = getattr(test_report, "warnings", None)
    if not isinstance(warnings, tuple):
        return ()
    signals: list[CompileSignal] = []
    for warning in warnings:
        text = str(warning).strip()
        if not text:
            continue
        if "coplanar" in text.lower():
            max_risk = "medium"
            risk_match = re.search(r"max_risk=(low|medium|high)", text, re.IGNORECASE)
            if risk_match is not None:
                max_risk = risk_match.group(1).lower()
            if max_risk == "low":
                signals.append(
                    _make_signal(
                        severity="note",
                        kind="coplanar_surface_hint",
                        code="NOTE_COPLANAR_SURFACE",
                        summary="Low-confidence coplanar-surface hint.",
                        details=text,
                        source="tests",
                        group="qc",
                    )
                )
                continue
            signals.append(
                _make_signal(
                    severity="warning",
                    kind="coplanar_surface",
                    code="WARN_COPLANAR_SURFACE",
                    summary=f"Coplanar-surface heuristic reported {max_risk}-risk pair(s).",
                    details=text,
                    source="tests",
                    group="qc",
                )
            )
            continue
        signals.append(
            _make_signal(
                severity="warning",
                kind="test_warning",
                code="TEST_WARNING",
                summary=text.splitlines()[0],
                details="\n".join(text.splitlines()[1:]).strip(),
                source="tests",
                group="qc",
            )
        )
    return signals


def _iter_allowance_notes(test_report: object | None) -> Iterable[CompileSignal]:
    allowances = getattr(test_report, "allowances", None)
    if not isinstance(allowances, tuple):
        return ()
    signals: list[CompileSignal] = []
    for allowance in allowances:
        text = str(allowance).strip()
        if not text:
            continue
        signals.append(
            _make_signal(
                severity="note",
                kind="allowance",
                code="ALLOWANCE",
                summary=text,
                source="tests",
                group="qc",
            )
        )
    return signals


def _runtime_failure_signal(exc: BaseException) -> CompileSignal:
    detail_lines = _exception_detail_lines(exc)
    detail_lines.extend(_exception_location_lines(exc))
    summary = f"{type(exc).__name__}: compile execution failed."
    if detail_lines:
        first = detail_lines[0]
        if first:
            summary = f"{type(exc).__name__}: {first}"
    return _make_signal(
        severity="failure",
        kind="compile_runtime",
        code="COMPILE_RUNTIME_FAILURE",
        summary=summary,
        details="\n".join(detail_lines),
        blocking=True,
        source="compiler",
        group="build",
    )


def build_compile_signal_bundle(
    *,
    status: str,
    warnings: Iterable[str] = (),
    test_report: object | None = None,
    exc: BaseException | None = None,
) -> CompileSignalBundle:
    deduped: dict[str, CompileSignal] = {}

    for warning in warnings:
        signal = _warning_signal_from_text(str(warning))
        deduped[signal.dedupe_key or signal.summary] = signal

    for signal in _iter_test_warnings(test_report):
        deduped[signal.dedupe_key or signal.summary] = signal

    for signal in _iter_allowance_notes(test_report):
        deduped[signal.dedupe_key or signal.summary] = signal

    failure_signals = list(_iter_test_failures(test_report))
    if failure_signals:
        for signal in failure_signals:
            deduped[signal.dedupe_key or signal.summary] = signal
    elif exc is not None:
        runtime_signal = _runtime_failure_signal(exc)
        deduped[runtime_signal.dedupe_key or runtime_signal.summary] = runtime_signal

    signals = tuple(deduped.values())
    failure_count = sum(1 for signal in signals if signal.severity == "failure")
    warning_count = sum(1 for signal in signals if signal.severity == "warning")
    note_count = sum(1 for signal in signals if signal.severity == "note")

    if failure_count:
        if any(signal.kind == "test_failure" for signal in signals):
            summary = (
                f"status={status} failures={failure_count} warnings={warning_count} notes={note_count}\n"
                "Primary issue: required QC tests failed."
            )
        else:
            summary = (
                f"status={status} failures={failure_count} warnings={warning_count} notes={note_count}\n"
                "Primary issue: compile execution failed."
            )
    elif warning_count:
        summary = (
            f"status={status} failures=0 warnings={warning_count} notes={note_count}\n"
            "Primary issue: compile passed with warnings."
        )
    else:
        summary = (
            f"status={status} failures=0 warnings=0 notes={note_count}\nCompile passed cleanly."
        )

    return CompileSignalBundle(status=status, summary=summary, signals=signals)  # type: ignore[arg-type]


def compile_signal_bundle_from_exception(exc: BaseException) -> CompileSignalBundle:
    existing = getattr(exc, "compile_signal_bundle", None)
    if isinstance(existing, CompileSignalBundle):
        return existing
    warnings = getattr(exc, "warnings", None)
    test_report = getattr(exc, "test_report", None)
    warning_items = warnings if isinstance(warnings, list) else []
    return build_compile_signal_bundle(
        status="failure",
        warnings=warning_items,
        test_report=test_report,
        exc=exc,
    )


def _render_signal_lines(signals: Iterable[CompileSignal]) -> str:
    rendered: list[str] = []
    for signal in signals:
        line = f"- [{signal.kind}] {signal.summary}"
        if signal.details:
            line += f"\n{signal.details}"
        rendered.append(line)
    return "\n".join(rendered)


def render_compile_signals(bundle: CompileSignalBundle, *, repeated: bool = False) -> str:
    failures = [signal for signal in bundle.signals if signal.severity == "failure"]
    warnings = [signal for signal in bundle.signals if signal.severity == "warning"]
    notes = [signal for signal in bundle.signals if signal.severity == "note"]

    summary = bundle.summary
    if repeated and failures:
        summary += "\nThis failure matches the previous compile attempt."

    parts = ["<compile_signals>", "<summary>", summary, "</summary>"]
    if failures:
        parts.extend(["", "<failures>", _render_signal_lines(failures), "</failures>"])
    if warnings:
        parts.extend(["", "<warnings>", _render_signal_lines(warnings), "</warnings>"])
    if notes and (failures or warnings):
        parts.extend(["", "<notes>", _render_signal_lines(notes), "</notes>"])

    response_rules = [
        "- Resolve failures either by correcting the current code when the representation is sound, or by rethinking the model when the representation itself is wrong.",
        "- Treat warnings as design and QC sensors, not noise.",
        "- If a signal reveals a wrong representation or composition, replace that representation instead of tuning around it.",
    ]
    if repeated and failures:
        response_rules.append(
            "- This failure class repeated. Stop patching symptoms and rewrite the affected region from the root cause."
        )
    parts.extend(
        [
            "",
            "<response_rules>",
            "\n".join(response_rules),
            "</response_rules>",
            "</compile_signals>",
        ]
    )
    return "\n".join(parts)
