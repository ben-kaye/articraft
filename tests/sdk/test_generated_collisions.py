from __future__ import annotations

from math import pi

import pytest

from sdk import ArticulatedObject, AssetContext, Cylinder, Sphere
from sdk._core.v0 import generated_collisions as gc
from sdk._core.v0.mesh import (
    BoxGeometry,
    CylinderGeometry,
    MeshGeometry,
    TorusGeometry,
    mesh_from_geometry,
    tube_from_spline_points,
    tube_network_from_paths,
)


def _build_model_with_mesh(tmp_path, mesh) -> ArticulatedObject:
    assets = AssetContext(tmp_path)
    model = ArticulatedObject(name="recipe_collision_model", assets=assets)
    part = model.part("body")
    part.visual(mesh)
    return model


def test_compile_generated_collisions_uses_tube_recipe_without_coacd(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mesh = mesh_from_geometry(
        tube_from_spline_points(
            [
                (0.0, 0.0, 0.0),
                (0.08, 0.02, 0.06),
                (0.14, -0.01, 0.12),
            ],
            radius=0.01,
            samples_per_segment=12,
            radial_segments=12,
        ),
        tmp_path / "assets" / "meshes" / "tube.obj",
    )

    def fail_run_coacd(*_args, **_kwargs):
        raise AssertionError("CoACD should not run for recipe-backed spline tubes")

    monkeypatch.setattr(gc.coacd, "run_coacd", fail_run_coacd)

    compiled = gc.compile_object_model_with_generated_collisions(
        _build_model_with_mesh(tmp_path, mesh),
        asset_root=tmp_path,
    )

    collisions = compiled.parts[0].collisions
    assert collisions
    assert all(isinstance(c.geometry, (Cylinder, Sphere)) for c in collisions)


def test_merge_of_recipe_bearing_geometry_preserves_collision_recipe(tmp_path) -> None:
    merged = CylinderGeometry(0.01, 0.10).rotate_y(pi / 2.0).translate(0.05, 0.0, 0.0)
    merged.merge(CylinderGeometry(0.01, 0.08).rotate_x(pi / 2.0).translate(0.0, 0.04, 0.0))

    mesh = mesh_from_geometry(merged, tmp_path / "assets" / "meshes" / "merged.obj")

    assert mesh.source_geometry is None
    assert mesh.source_collisions is not None
    assert len(mesh.source_collisions) == 2
    assert all(isinstance(c.geometry, Cylinder) for c in mesh.source_collisions)


def test_compile_generated_collisions_uses_torus_recipe_without_coacd(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mesh = mesh_from_geometry(
        TorusGeometry(0.12, 0.015, tubular_segments=64),
        tmp_path / "assets" / "meshes" / "torus.obj",
    )

    def fail_run_coacd(*_args, **_kwargs):
        raise AssertionError("CoACD should not run for recipe-backed torus meshes")

    monkeypatch.setattr(gc.coacd, "run_coacd", fail_run_coacd)

    compiled = gc.compile_object_model_with_generated_collisions(
        _build_model_with_mesh(tmp_path, mesh),
        asset_root=tmp_path,
    )

    collisions = compiled.parts[0].collisions
    assert collisions
    assert all(isinstance(c.geometry, (Cylinder, Sphere)) for c in collisions)


def test_compile_generated_collisions_uses_merged_recipe_assembly_without_coacd(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assembly = TorusGeometry(0.12, 0.015, tubular_segments=64)
    assembly.merge(CylinderGeometry(0.01, 0.24).rotate_y(pi / 2.0))

    mesh = mesh_from_geometry(
        assembly,
        tmp_path / "assets" / "meshes" / "wheel_like.obj",
    )

    def fail_run_coacd(*_args, **_kwargs):
        raise AssertionError("CoACD should not run for merged recipe-backed assemblies")

    monkeypatch.setattr(gc.coacd, "run_coacd", fail_run_coacd)

    compiled = gc.compile_object_model_with_generated_collisions(
        _build_model_with_mesh(tmp_path, mesh),
        asset_root=tmp_path,
    )

    collisions = compiled.parts[0].collisions
    assert collisions
    assert all(isinstance(c.geometry, (Cylinder, Sphere)) for c in collisions)


def test_compile_generated_collisions_uses_tube_network_recipe_without_coacd(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mesh = mesh_from_geometry(
        tube_network_from_paths(
            [
                [(-0.08, 0.0, 0.0), (0.0, 0.0, 0.0), (0.08, 0.0, 0.0)],
                [(0.0, -0.08, 0.0), (0.0, 0.0, 0.0), (0.0, 0.08, 0.0)],
            ],
            radius=0.01,
        ),
        tmp_path / "assets" / "meshes" / "network.obj",
    )

    def fail_run_coacd(*_args, **_kwargs):
        raise AssertionError("CoACD should not run for recipe-backed tube networks")

    monkeypatch.setattr(gc.coacd, "run_coacd", fail_run_coacd)

    compiled = gc.compile_object_model_with_generated_collisions(
        _build_model_with_mesh(tmp_path, mesh),
        asset_root=tmp_path,
    )

    collisions = compiled.parts[0].collisions
    assert collisions
    assert all(isinstance(c.geometry, (Cylinder, Sphere)) for c in collisions)


def test_merge_with_unknown_geometry_clears_collision_recipe(tmp_path) -> None:
    merged = BoxGeometry((0.1, 0.02, 0.02))
    merged.merge(
        MeshGeometry(
            vertices=[
                (0.0, 0.0, 0.0),
                (0.02, 0.0, 0.0),
                (0.0, 0.02, 0.0),
            ],
            faces=[(0, 1, 2)],
        )
    )

    mesh = mesh_from_geometry(merged, tmp_path / "assets" / "meshes" / "mixed.obj")

    assert mesh.source_geometry is None
    assert mesh.source_collisions is None
