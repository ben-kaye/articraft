from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.compiler import compile_urdf_report, persist_compile_success_artifacts, update_manifest
from agent.runner import compile_urdf


def test_compile_artifacts_update_manifest(tmp_path: Path) -> None:
    outputs_root = tmp_path / "outputs"
    run_dir = outputs_root / "sample_run"
    viewer_dir = outputs_root / "viewer"
    run_dir.mkdir(parents=True)
    viewer_dir.mkdir(parents=True)

    urdf_path = run_dir / "sample_run.urdf"
    sig = persist_compile_success_artifacts(
        urdf_xml="<robot name='sample'/>",
        urdf_out=urdf_path,
        outputs_root=outputs_root,
    )

    assert sig is not None
    assert urdf_path.read_text(encoding="utf-8") == "<robot name='sample'/>"

    manifest = json.loads((outputs_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "generated": [
            {
                "name": "sample_run",
                "path": "sample_run/sample_run.urdf",
            }
        ]
    }

    duplicate_sig = persist_compile_success_artifacts(
        urdf_xml="<robot name='sample'/>",
        urdf_out=urdf_path,
        outputs_root=outputs_root,
        previous_sig=sig,
    )
    assert duplicate_sig == sig

    extra_urdf = outputs_root / "second" / "second.urdf"
    extra_urdf.parent.mkdir(parents=True)
    extra_urdf.write_text("<robot name='second'/>", encoding="utf-8")
    (viewer_dir / "ignored.urdf").write_text("<robot name='viewer'/>", encoding="utf-8")
    update_manifest(outputs_root)

    manifest = json.loads((outputs_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "generated": [
            {
                "name": "sample_run",
                "path": "sample_run/sample_run.urdf",
            },
            {
                "name": "second",
                "path": "second/second.urdf",
            },
        ]
    }

    assert callable(compile_urdf)


def test_compile_urdf_report_can_skip_required_checks(tmp_path: Path) -> None:
    script_path = tmp_path / "model.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from sdk import ArticulatedObject, Box, Origin",
                "",
                "object_model = ArticulatedObject(name='unsafe')",
                "base = object_model.part('base')",
                "base.visual(Box((0.1, 0.1, 0.1)), origin=Origin(xyz=(0.0, 0.0, 0.05)))",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Missing required `run_tests\\(\\)`"):
        compile_urdf_report(script_path)

    report = compile_urdf_report(script_path, run_checks=False)
    assert "<robot" in report.urdf_xml
    assert report.warnings == []
    assert report.signal_bundle.status == "success"


def test_compile_urdf_report_can_ignore_geometry_qc_after_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_path = tmp_path / "model.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from sdk import ArticulatedObject, Box, Origin",
                "",
                "object_model = ArticulatedObject(name='qc_ok')",
                "base = object_model.part('base')",
                "base.visual(Box((0.1, 0.1, 0.1)), origin=Origin(xyz=(0.0, 0.0, 0.05)))",
            ]
        ),
        encoding="utf-8",
    )

    def fake_run_required_tests(*_args, **_kwargs):
        raise RuntimeError(
            "URDF compile failure (collision, blocking): isolated parts detected "
            "(not contacting any other part in the checked pose)."
        )

    monkeypatch.setattr("agent.compiler._run_required_tests", fake_run_required_tests)

    with pytest.raises(RuntimeError, match="URDF compile failure \\(collision, blocking\\)"):
        compile_urdf_report(script_path)

    report = compile_urdf_report(script_path, ignore_geom_qc=True)
    assert "<robot" in report.urdf_xml
    assert any(
        "URDF compile warning (collision, non-blocking): isolated parts detected" in warning
        for warning in report.warnings
    )
    assert report.signal_bundle.status == "success"


def test_compile_urdf_report_does_not_ignore_non_geometry_failures(tmp_path: Path) -> None:
    script_path = tmp_path / "model.py"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from sdk import ArticulatedObject, Box, Origin",
                "",
                "object_model = ArticulatedObject(name='unsafe')",
                "base = object_model.part('base')",
                "base.visual(Box((0.1, 0.1, 0.1)), origin=Origin(xyz=(0.0, 0.0, 0.05)))",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Missing required `run_tests\\(\\)`"):
        compile_urdf_report(script_path, ignore_geom_qc=True)
