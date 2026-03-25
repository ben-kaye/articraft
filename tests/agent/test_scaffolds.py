from __future__ import annotations

from pathlib import Path

from agent.harness import _minimal_scaffold_text


def test_base_scaffold_matches_harness_fallback() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scaffold_path = repo_root / "scaffold.py"
    scaffold_text = scaffold_path.read_text(encoding="utf-8")

    assert scaffold_text == _minimal_scaffold_text(sdk_package="sdk")
    assert (
        "from sdk import ArticulatedObject, AssetContext, TestContext, TestReport" in scaffold_text
    )
    assert "def build_object_model() -> ArticulatedObject:" in scaffold_text
    assert "def run_tests() -> TestReport:" in scaffold_text
    assert "ctx.check_model_valid()" in scaffold_text
    assert "ctx.check_mesh_files_exist()" in scaffold_text
    assert "ctx.check_no_isolated_parts()" in scaffold_text
    assert "ctx.warn_if_part_geometry_disconnected()" in scaffold_text
    assert "ctx.check_no_part_overlaps()" in scaffold_text
    assert "ctx.warn_if_articulation_origin_near_geometry" not in scaffold_text
    assert "ctx.warn_if_articulation_overlaps(max_pose_samples=128)" not in scaffold_text
    assert (
        "ctx.warn_if_overlaps(max_pose_samples=128, ignore_adjacent=True, ignore_fixed=True)"
        not in scaffold_text
    )
    assert "likely-failure broad-part floating check for isolated parts" in scaffold_text
    assert (
        "noisier warning-tier sensor for same-part disconnected geometry islands" in scaffold_text
    )
    assert "likely-failure rest-pose part-to-part overlap backstop" in scaffold_text
    assert "Investigate all three. Warning-tier signals are not free passes." in scaffold_text
    assert "expect_aabb_" not in scaffold_text


def test_hybrid_scaffold_matches_harness_fallback() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scaffold_path = repo_root / "scaffold_hybrid.py"
    scaffold_text = scaffold_path.read_text(encoding="utf-8")

    assert scaffold_text == _minimal_scaffold_text(sdk_package="sdk_hybrid")
    assert (
        "from sdk_hybrid import ArticulatedObject, AssetContext, TestContext, TestReport"
        in scaffold_text
    )
    assert "def build_object_model() -> ArticulatedObject:" in scaffold_text
    assert "def run_tests() -> TestReport:" in scaffold_text
    assert "ctx.check_model_valid()" in scaffold_text
    assert "ctx.check_mesh_files_exist()" in scaffold_text
    assert "ctx.check_no_isolated_parts()" in scaffold_text
    assert "ctx.warn_if_part_geometry_disconnected()" in scaffold_text
    assert "ctx.check_no_part_overlaps()" in scaffold_text
    assert "ctx.warn_if_articulation_origin_near_geometry" not in scaffold_text
    assert "ctx.warn_if_articulation_overlaps(max_pose_samples=128)" not in scaffold_text
    assert (
        "ctx.warn_if_overlaps(max_pose_samples=128, ignore_adjacent=True, ignore_fixed=True)"
        not in scaffold_text
    )
    assert "Preferred default QC stack" in scaffold_text
    assert "likely-failure broad-part floating check for isolated parts" in scaffold_text
    assert (
        "noisier warning-tier sensor for same-part disconnected geometry islands" in scaffold_text
    )
    assert "likely-failure rest-pose part-to-part overlap backstop" in scaffold_text
    assert "Investigate all three. Warning-tier signals are not free passes." in scaffold_text
    assert "justify it with `ctx.allow_overlap(...)`" in scaffold_text
    assert "expect_aabb_" not in scaffold_text
