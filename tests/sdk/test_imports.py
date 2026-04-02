from __future__ import annotations

import sdk


def test_sdk_exports() -> None:
    assert hasattr(sdk, "ArticulatedObject")
    assert hasattr(sdk, "CapsuleGeometry")
    assert hasattr(sdk, "DomeGeometry")
    assert hasattr(sdk, "MeshGeometry")
    assert hasattr(sdk, "SurfaceFrame")
    assert hasattr(sdk, "SurfaceWrapMapping")
    assert hasattr(sdk, "ValidationError")
    assert hasattr(sdk, "TestContext")
    assert hasattr(sdk, "SectionLoftSpec")
    assert hasattr(sdk, "section_loft")
    assert hasattr(sdk, "repair_loft")
    assert hasattr(sdk, "ShellPartitionRegion")
    assert hasattr(sdk, "ShellPartitionSpec")
    assert hasattr(sdk, "partition_shell")
    assert hasattr(sdk, "surface_frame")
    assert hasattr(sdk, "align_centers")
    assert hasattr(sdk, "place_on_surface")
    assert hasattr(sdk, "place_on_face")
    assert hasattr(sdk, "wrap_profile_onto_surface")
    assert hasattr(sdk, "wrap_mesh_onto_surface")
    assert hasattr(sdk, "scale_geometry_to_size")
    assert not hasattr(sdk, "BufferGeometry")
    assert not hasattr(sdk, "place_on_top")
    assert not hasattr(sdk, "place_in_front_of")
    assert not hasattr(sdk, "align_centers_xy")
