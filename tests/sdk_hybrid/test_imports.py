from __future__ import annotations

import sdk_hybrid
from sdk_hybrid.v0.cadquery import mesh_from_cadquery


def test_sdk_hybrid_exports() -> None:
    assert hasattr(sdk_hybrid, "ArticulatedObject")
    assert hasattr(sdk_hybrid, "SurfaceFrame")
    assert hasattr(sdk_hybrid, "SurfaceWrapMapping")
    assert hasattr(sdk_hybrid, "ValidationError")
    assert hasattr(sdk_hybrid, "TestContext")
    assert hasattr(sdk_hybrid, "UnsupportedPartFinding")
    assert hasattr(sdk_hybrid, "surface_frame")
    assert hasattr(sdk_hybrid, "place_on_surface")
    assert hasattr(sdk_hybrid, "wrap_profile_onto_surface")
    assert hasattr(sdk_hybrid, "wrap_mesh_onto_surface")
    assert callable(mesh_from_cadquery)
    assert not hasattr(sdk_hybrid, "SectionLoftSpec")
    assert not hasattr(sdk_hybrid, "section_loft")
    assert not hasattr(sdk_hybrid, "repair_loft")
    assert not hasattr(sdk_hybrid, "ShellPartitionRegion")
    assert not hasattr(sdk_hybrid, "ShellPartitionSpec")
    assert not hasattr(sdk_hybrid, "partition_shell")
