from __future__ import annotations

from pathlib import Path

from agent.harness import _minimal_scaffold_text


def test_base_strict_scaffold_matches_harness_fallback() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scaffold_path = repo_root / "scaffold.py"
    scaffold_text = scaffold_path.read_text(encoding="utf-8")

    assert scaffold_text == _minimal_scaffold_text(sdk_package="sdk", scaffold_mode="strict")
    assert "from sdk import ArticulatedObject, TestContext, TestReport" in scaffold_text
    assert "def build_object_model() -> ArticulatedObject:" in scaffold_text
    assert "def run_tests() -> TestReport:" in scaffold_text
    assert "ctx.check_model_valid()" in scaffold_text
    assert "ctx.check_mesh_assets_ready()" in scaffold_text
    assert "ctx.fail_if_isolated_parts()" in scaffold_text
    assert "ctx.warn_if_part_contains_disconnected_geometry_islands()" in scaffold_text
    assert "ctx.fail_if_parts_overlap_in_current_pose()" in scaffold_text
    assert "ctx.warn_if_articulation_origin_far_from_geometry" not in scaffold_text
    assert "ctx.warn_if_articulation_overlaps(max_pose_samples=128)" not in scaffold_text
    assert (
        "ctx.warn_if_overlaps(max_pose_samples=128, ignore_adjacent=True, ignore_fixed=True)"
        not in scaffold_text
    )
    assert (
        "likely-failure grounded-component floating check for disconnected part groups"
        in scaffold_text
    )
    assert (
        "noisier warning-tier sensor for same-part disconnected geometry islands" in scaffold_text
    )
    assert (
        "likely-failure rest-pose part-to-part overlap backstop for real 3D interpenetration"
        in scaffold_text
    )
    assert 'This is not an "inside / nested / footprint overlap" check.' in scaffold_text
    assert "Investigate all three. Warning-tier signals are not free passes." in scaffold_text
    assert "Use `ctx.allow_overlap(...)` only for true intended penetration." in scaffold_text
    assert "If parts are nested but should remain clear, prove that with exact" in scaffold_text
    assert "Keep pose-specific checks lean." in scaffold_text
    assert "Do not add blanket lower/upper pose sweeps" in scaffold_text
    assert "fail_if_parts_overlap_in_sampled_poses(...)" in scaffold_text
    assert "ctx.warn_if_articulation_overlaps(...)" in scaffold_text
    assert "expect_aabb_" not in scaffold_text


def test_hybrid_strict_scaffold_matches_harness_fallback() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scaffold_path = repo_root / "scaffold_hybrid.py"
    scaffold_text = scaffold_path.read_text(encoding="utf-8")

    assert scaffold_text == _minimal_scaffold_text(
        sdk_package="sdk_hybrid",
        scaffold_mode="strict",
    )
    assert "from sdk_hybrid import ArticulatedObject, TestContext, TestReport" in scaffold_text
    assert "def build_object_model() -> ArticulatedObject:" in scaffold_text
    assert "def run_tests() -> TestReport:" in scaffold_text
    assert "ctx.check_model_valid()" in scaffold_text
    assert "ctx.check_mesh_assets_ready()" in scaffold_text
    assert "ctx.fail_if_isolated_parts()" in scaffold_text
    assert "ctx.warn_if_part_contains_disconnected_geometry_islands()" in scaffold_text
    assert "ctx.fail_if_parts_overlap_in_current_pose()" in scaffold_text
    assert "ctx.warn_if_articulation_origin_far_from_geometry" not in scaffold_text
    assert "ctx.warn_if_articulation_overlaps(max_pose_samples=128)" not in scaffold_text
    assert (
        "ctx.warn_if_overlaps(max_pose_samples=128, ignore_adjacent=True, ignore_fixed=True)"
        not in scaffold_text
    )
    assert "Preferred default QC stack" in scaffold_text
    assert (
        "likely-failure grounded-component floating check for disconnected part groups"
        in scaffold_text
    )
    assert (
        "noisier warning-tier sensor for same-part disconnected geometry islands" in scaffold_text
    )
    assert (
        "likely-failure rest-pose part-to-part overlap backstop for real 3D interpenetration"
        in scaffold_text
    )
    assert 'This is not an "inside / nested / footprint overlap" check.' in scaffold_text
    assert "Investigate all three. Warning-tier signals are not free passes." in scaffold_text
    assert "Use `ctx.allow_overlap(...)` only for true intended penetration." in scaffold_text
    assert "If parts are nested but should remain clear, prove that with exact" in scaffold_text
    assert "Keep pose-specific checks lean." in scaffold_text
    assert "Do not add blanket lower/upper pose sweeps" in scaffold_text
    assert "fail_if_parts_overlap_in_sampled_poses(...)" in scaffold_text
    assert "ctx.warn_if_articulation_overlaps(...)" in scaffold_text
    assert "expect_aabb_" not in scaffold_text


def test_base_lite_scaffold_matches_harness_fallback() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scaffold_path = repo_root / "scaffold_lite.py"
    scaffold_text = scaffold_path.read_text(encoding="utf-8")

    assert scaffold_text == _minimal_scaffold_text(sdk_package="sdk", scaffold_mode="lite")
    assert "ctx.fail_if_isolated_parts()" in scaffold_text
    assert "ctx.warn_if_part_contains_disconnected_geometry_islands()" in scaffold_text
    assert "ctx.fail_if_parts_overlap_in_current_pose()" in scaffold_text
    assert "For bounded REVOLUTE/PRISMATIC joints" not in scaffold_text
    assert "limits = hinge.motion_limits" not in scaffold_text
    assert 'ctx.fail_if_isolated_parts(name="lid_hinge_upper_no_floating")' not in scaffold_text


def test_hybrid_lite_scaffold_matches_harness_fallback() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scaffold_path = repo_root / "scaffold_hybrid_lite.py"
    scaffold_text = scaffold_path.read_text(encoding="utf-8")

    assert scaffold_text == _minimal_scaffold_text(sdk_package="sdk_hybrid", scaffold_mode="lite")
    assert "ctx.fail_if_isolated_parts()" in scaffold_text
    assert "ctx.warn_if_part_contains_disconnected_geometry_islands()" in scaffold_text
    assert "ctx.fail_if_parts_overlap_in_current_pose()" in scaffold_text
    assert "For bounded REVOLUTE/PRISMATIC joints" not in scaffold_text
    assert "limits = hinge.motion_limits" not in scaffold_text
    assert 'ctx.fail_if_isolated_parts(name="lid_hinge_upper_no_floating")' not in scaffold_text
