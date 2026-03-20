from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.compiler import _validate_unsupported_parts, _warn_geometry_scale_anomalies
from agent.feedback import build_compile_signal_bundle
from agent.harness import ArticraftAgent
from agent.models import CompileReport
from sdk import ArticulatedObject, Box, Cylinder
from sdk import TestReport as SDKTestReport


def test_absurd_dimension_warning() -> None:
    model = ArticulatedObject(name="absurd")
    base = model.part("base")
    base.visual(Box((0.4, 0.4, 0.2)))

    boom = model.part("boom")
    boom.visual(Cylinder(radius=0.01, length=8.88e7))

    warnings: list[str] = []
    _warn_geometry_scale_anomalies(
        {"object_model": model},
        script_dir=Path.cwd(),
        warnings=warnings,
    )

    assert any("IMPORTANT:" in warning for warning in warnings)
    assert any(
        "non-finite or absurd geometry dimensions detected" in warning for warning in warnings
    )


def test_outlier_dimension_warning() -> None:
    model = ArticulatedObject(name="outlier")
    for i in range(6):
        part = model.part(f"small_{i}")
        part.visual(Box((0.1, 0.08, 0.06)))

    giant = model.part("giant")
    giant.visual(Cylinder(radius=0.03, length=20.0))

    warnings: list[str] = []
    _warn_geometry_scale_anomalies(
        {"object_model": model},
        script_dir=Path.cwd(),
        warnings=warnings,
    )

    assert any("IMPORTANT:" in warning for warning in warnings)
    assert any("geometry outlier dimensions detected" in warning for warning in warnings)


def test_compile_signal_bundle_includes_test_warnings_and_allowances() -> None:
    warnings = [
        "IMPORTANT: URDF compile warning (non-blocking): geometry outlier dimensions detected.\n"
        "- link='boom' source='visual' index=0 geometry='Cylinder' dims=(0.06, 0.06, 20)m"
    ]
    bundle = build_compile_signal_bundle(
        status="success",
        warnings=warnings,
        test_report=SDKTestReport(
            passed=True,
            checks_run=1,
            checks=("check_no_overlaps",),
            failures=(),
            warnings=("neighbor overlaps downgraded to warnings",),
            allowances=("allow_overlap('door', 'frame'): hinge nesting",),
        ),
    )

    assert any(signal.kind == "geometry_scale" for signal in bundle.signals)
    assert any(signal.kind == "test_warning" for signal in bundle.signals)
    assert any(signal.kind == "allowance" for signal in bundle.signals)


def test_harness_injects_structured_compile_signals() -> None:
    agent = ArticraftAgent.__new__(ArticraftAgent)
    agent._seen_compile_signal_sigs = set()
    agent.trace_writer = None

    report = CompileReport(
        urdf_xml="<robot/>",
        warnings=[
            "IMPORTANT: URDF compile warning (non-blocking): geometry outlier dimensions detected.\n"
            "- link='boom' source='visual' index=0 geometry='Cylinder' dims=(0.06, 0.06, 20)m"
        ],
        signal_bundle=build_compile_signal_bundle(
            status="success",
            warnings=[
                "IMPORTANT: URDF compile warning (non-blocking): geometry outlier dimensions detected.\n"
                "- link='boom' source='visual' index=0 geometry='Cylinder' dims=(0.06, 0.06, 20)m"
            ],
            test_report=SDKTestReport(
                passed=True,
                checks_run=2,
                checks=("check_no_overlaps", "check_visuals"),
                failures=(),
                warnings=("visual connectivity drift detected",),
                allowances=("allow_overlap('door', 'frame'): hinge nesting",),
            ),
        ),
    )

    conversation: list[dict] = []
    injected = agent._maybe_inject_compile_signals(
        conversation,
        bundle=report.signal_bundle,
    )

    assert injected is True
    assert conversation
    assert "<compile_signals>" in conversation[0]["content"]
    assert "<summary>" in conversation[0]["content"]
    assert "<warnings>" in conversation[0]["content"]
    assert "<notes>" in conversation[0]["content"]
    assert "<response_rules>" in conversation[0]["content"]
    assert "Geometry outlier dimensions detected." in conversation[0]["content"]
    assert "visual connectivity drift detected" in conversation[0]["content"]
    assert "hinge nesting" in conversation[0]["content"]


def test_validate_unsupported_parts_keeps_visual_findings_as_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings_by_source = {
        "visual": [
            SimpleNamespace(
                part="lid",
                nearest_part="base",
                min_distance=0.012,
                pose_index=0,
                pose={},
                backend="aabb",
            )
        ],
        "collision": [],
    }

    fake_sdk = SimpleNamespace(
        default_contact_tol_from_env=lambda: 1e-6,
        find_unsupported_parts=lambda _model, **kwargs: findings_by_source[
            kwargs["geometry_source"]
        ],
    )
    monkeypatch.setattr("agent.compiler._import_sdk_module", lambda _sdk_package: fake_sdk)

    warnings = _validate_unsupported_parts({"object_model": object()}, script_dir=Path.cwd())

    assert len(warnings) == 1
    assert "URDF compile warning (visual, non-blocking): isolated parts detected" in warnings[0]


def test_validate_unsupported_parts_promotes_collision_findings_to_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings_by_source = {
        "visual": [],
        "collision": [
            SimpleNamespace(
                part="fan",
                nearest_part="nacelle",
                min_distance=0.021,
                pose_index=0,
                pose={},
                backend="fcl",
            )
        ],
    }

    fake_sdk = SimpleNamespace(
        default_contact_tol_from_env=lambda: 1e-6,
        find_unsupported_parts=lambda _model, **kwargs: findings_by_source[
            kwargs["geometry_source"]
        ],
    )
    monkeypatch.setattr("agent.compiler._import_sdk_module", lambda _sdk_package: fake_sdk)

    with pytest.raises(
        RuntimeError,
        match="URDF compile failure \\(collision, blocking\\): isolated parts detected",
    ):
        _validate_unsupported_parts({"object_model": object()}, script_dir=Path.cwd())
