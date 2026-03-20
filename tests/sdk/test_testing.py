from __future__ import annotations

from sdk import (
    ArticulatedObject,
    ArticulationType,
    Box,
    MotionLimits,
    Origin,
)
from sdk import (
    TestContext as SDKTestContext,
)


def _build_joint_origin_model(*, joint_z: float) -> ArticulatedObject:
    model = ArticulatedObject(name="joint_origin_tolerance")

    base = model.part("base")
    base.visual(Box((0.1, 0.1, 0.1)), origin=Origin(xyz=(0.0, 0.0, 0.05)))

    child = model.part("child")
    child.visual(Box((0.1, 0.1, 0.1)), origin=Origin(xyz=(0.0, 0.0, 0.05)))

    model.articulation(
        "base_to_child",
        ArticulationType.REVOLUTE,
        parent=base,
        child=child,
        origin=Origin(xyz=(0.0, 0.0, joint_z)),
        axis=(0.0, 1.0, 0.0),
        motion_limits=MotionLimits(effort=1.0, velocity=1.0, lower=0.0, upper=1.0),
    )
    return model


def _build_disconnected_part_model() -> ArticulatedObject:
    model = ArticulatedObject(name="disconnected_part")

    base = model.part("base")
    base.visual(Box((0.1, 0.1, 0.1)), origin=Origin(xyz=(0.0, 0.0, 0.05)))
    base.visual(Box((0.1, 0.1, 0.1)), origin=Origin(xyz=(0.4, 0.0, 0.05)))

    return model


def _build_overlapping_parts_model() -> ArticulatedObject:
    model = ArticulatedObject(name="overlapping_parts")

    base = model.part("base")
    base.visual(Box((0.2, 0.2, 0.2)), origin=Origin(xyz=(0.0, 0.0, 0.1)))

    child = model.part("child")
    child.visual(Box((0.2, 0.2, 0.2)), origin=Origin(xyz=(0.0, 0.0, 0.1)))

    return model


def _build_coplanar_surface_model() -> ArticulatedObject:
    model = ArticulatedObject(name="coplanar_surfaces")

    base = model.part("base")
    base.visual(Box((0.2, 0.2, 0.2)), origin=Origin(xyz=(0.0, 0.0, 0.1)))

    cap = model.part("cap")
    cap.visual(Box((0.12, 0.12, 0.02)), origin=Origin(xyz=(0.0, 0.0, 0.19)))

    return model


def test_articulation_origin_tolerance_is_truncated_to_three_decimals() -> None:
    ctx = SDKTestContext(_build_joint_origin_model(joint_z=0.115), geometry_source="visual")

    assert ctx.check_articulation_origin_near_geometry(tol=0.0159)

    report = ctx.report()
    assert report.passed
    assert report.checks == ("check_articulation_origin_near_geometry(tol=0.015)",)


def test_articulation_origin_tolerance_is_capped_at_point_one_five() -> None:
    ctx = SDKTestContext(_build_joint_origin_model(joint_z=0.25), geometry_source="visual")

    assert ctx.check_articulation_origin_near_geometry(tol=0.159)

    report = ctx.report()
    assert report.passed
    assert report.checks == ("check_articulation_origin_near_geometry(tol=0.15)",)


def test_warn_if_articulation_origin_near_geometry_records_warning_only() -> None:
    ctx = SDKTestContext(_build_joint_origin_model(joint_z=0.2), geometry_source="visual")

    assert not ctx.warn_if_articulation_origin_near_geometry(tol=0.015)

    report = ctx.report()
    assert report.passed
    assert report.failures == ()
    assert report.checks == ("warn_if_articulation_origin_near_geometry(tol=0.015)",)
    assert len(report.warnings) == 1
    assert "warn_if_articulation_origin_near_geometry(tol=0.015)" in report.warnings[0]
    assert "Articulation origin(s) far from geometry" in report.warnings[0]


def test_warn_if_part_geometry_connected_records_warning_only() -> None:
    ctx = SDKTestContext(_build_disconnected_part_model(), geometry_source="visual")

    assert not ctx.warn_if_part_geometry_connected(use="visual")

    report = ctx.report()
    assert report.passed
    assert report.failures == ()
    assert report.checks == ("warn_if_part_geometry_connected(use=visual,tol=0.005)",)
    assert len(report.warnings) == 1
    assert "warn_if_part_geometry_connected(use=visual,tol=0.005)" in report.warnings[0]
    assert "Disconnected geometry islands detected" in report.warnings[0]


def test_warn_if_overlaps_records_warning_only() -> None:
    ctx = SDKTestContext(_build_overlapping_parts_model(), geometry_source="visual")

    assert not ctx.warn_if_overlaps(max_pose_samples=8)

    report = ctx.report()
    assert report.passed
    assert report.failures == ()
    assert report.checks == ("warn_if_overlaps(samples=8,ignore_adjacent=False,ignore_fixed=True)",)
    assert len(report.warnings) == 1
    assert (
        "warn_if_overlaps(samples=8,ignore_adjacent=False,ignore_fixed=True)" in report.warnings[0]
    )
    assert "Overlaps detected" in report.warnings[0]


def test_warn_if_coplanar_surfaces_records_warning_only() -> None:
    ctx = SDKTestContext(_build_coplanar_surface_model(), geometry_source="visual")

    assert not ctx.warn_if_coplanar_surfaces(
        max_pose_samples=1,
        use="visual",
        plane_tol=0.001,
        min_overlap=0.05,
    )

    report = ctx.report()
    assert report.passed
    assert report.failures == ()
    assert report.checks == (
        "warn_if_coplanar_surfaces(samples=1,use=visual,plane_tol=0.001,min_overlap=0.05,ignore_adjacent=False,ignore_fixed=False)",
    )
    assert len(report.warnings) == 1
    assert (
        "warn_if_coplanar_surfaces(samples=1,use=visual,plane_tol=0.001,min_overlap=0.05,ignore_adjacent=False,ignore_fixed=False)"
        in report.warnings[0]
    )
    assert "Coplanar or nearly coplanar surfaces detected" in report.warnings[0]
    assert "pair=('base','cap')" in report.warnings[0]
