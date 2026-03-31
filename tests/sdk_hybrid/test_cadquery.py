from __future__ import annotations

from pathlib import Path

import pytest

from sdk._core.v0.assets import AssetContext
from sdk_hybrid import ArticulatedObject, TestContext, cadquery_local_aabb
from sdk_hybrid.v0.cadquery import (
    export_cadquery_components,
    mesh_components_from_cadquery,
    mesh_from_cadquery,
)

cq = pytest.importorskip("cadquery")


def test_cadquery_workplane_stack_exports_all_objects() -> None:
    box1 = cq.Workplane("XY").box(1.0, 1.0, 1.0).val()
    box2 = cq.Workplane("XY").center(3.0, 0.0).box(1.0, 1.0, 1.0).val()
    workplane = cq.Workplane("XY").newObject([box1, box2])

    aabb = cadquery_local_aabb(workplane)

    assert aabb == ((-0.5, -0.5, -0.5), (3.5, 0.5, 0.5))


def test_export_cadquery_components_splits_workplane_stack(tmp_path) -> None:
    assets = AssetContext(tmp_path)
    box1 = cq.Workplane("XY").box(1.0, 1.0, 1.0).val()
    box2 = cq.Workplane("XY").center(3.0, 0.0).box(1.0, 1.0, 1.0).val()
    workplane = cq.Workplane("XY").newObject([box1, box2])

    exports = export_cadquery_components(workplane, "pair.obj", assets=assets)

    assert len(exports) == 2
    assert exports[0].mesh.filename == "assets/meshes/pair__component_001.obj"
    assert exports[1].mesh.filename == "assets/meshes/pair__component_002.obj"
    assert Path(str(exports[0].mesh.materialized_path)).exists()
    assert Path(str(exports[1].mesh.materialized_path)).exists()
    assert exports[0].local_aabb == ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
    assert exports[1].local_aabb == ((2.5, -0.5, -0.5), (3.5, 0.5, 0.5))


def test_mesh_components_from_cadquery_preserves_assembly_locations(tmp_path) -> None:
    assets = AssetContext(tmp_path)
    assembly = cq.Assembly(name="root")
    box = cq.Workplane("XY").box(1.0, 1.0, 1.0)
    assembly.add(box, name="left", loc=cq.Location(cq.Vector(-2.0, 0.0, 0.0)))
    assembly.add(box, name="right", loc=cq.Location(cq.Vector(2.0, 0.0, 0.0)))

    exports = export_cadquery_components(assembly, "assembly.obj", assets=assets)
    meshes = mesh_components_from_cadquery(assembly, "assembly.obj", assets=assets)

    assert len(exports) == 2
    assert exports[0].local_aabb == ((-2.5, -0.5, -0.5), (-1.5, 0.5, 0.5))
    assert exports[1].local_aabb == ((1.5, -0.5, -0.5), (2.5, 0.5, 0.5))
    assert len(meshes) == 2
    assert meshes[0].filename == "assets/meshes/assembly__component_001.obj"
    assert meshes[1].filename == "assets/meshes/assembly__component_002.obj"


def test_mesh_from_cadquery_still_triggers_disconnected_geometry_warning_for_multi_solid_shape(
    tmp_path,
) -> None:
    assets = AssetContext(tmp_path)
    box1 = cq.Workplane("XY").box(1.0, 1.0, 1.0).val()
    box2 = cq.Workplane("XY").center(3.0, 0.0).box(1.0, 1.0, 1.0).val()
    workplane = cq.Workplane("XY").newObject([box1, box2])

    model = ArticulatedObject(name="cadquery_connectivity", assets=assets)
    frame = model.part("frame")
    frame.visual(mesh_from_cadquery(workplane, "frame.obj", assets=assets), name="frame_body")

    ctx = TestContext(model)

    assert not ctx.warn_if_part_contains_disconnected_geometry_islands()

    report = ctx.report()
    assert report.passed
    assert len(report.warnings) == 1
    assert "frame_body__component_002:Mesh" in report.warnings[0]
