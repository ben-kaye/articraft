# SDK Quickstart

## Purpose

Use this page to start a new `sdk` script. It defines the required script
contract, the canonical import pattern, and one minimal end-to-end example.
Detailed type, assembly, placement, probe, and testing APIs live in the
specialized docs referenced at the end.

## Script Contract

Every generated script should define:

- `build_object_model() -> ArticulatedObject`
- `run_tests() -> TestReport`
- `object_model = build_object_model()`

The harness compiles `object_model`, derives exact collisions from visuals, runs
tests, and exports the result. Do not emit URDF XML directly.

## Recommended Imports

```python
from sdk import (
    ArticulatedObject,
    ArticulationType,
    Box,
    Inertial,
    MotionLimits,
    Origin,
    TestContext,
    TestReport,
)
```

## Managed Mesh Pattern

Use logical mesh names. The runtime decides where OBJ files live.

- Generate procedural meshes with `mesh_from_geometry(..., "part_name")`.
- Import existing OBJ inputs with `mesh_from_input("mesh_name")`.
- Use `TestContext(object_model)`; do not wire asset roots manually.

## Minimal Example

```python
from sdk import (
    ArticulatedObject,
    ArticulationType,
    Box,
    Inertial,
    MotionLimits,
    Origin,
    TestContext,
    TestReport,
)


def build_object_model() -> ArticulatedObject:
    model = ArticulatedObject(name="example_box_lid")

    base = model.part("base")
    base.visual(
        Box((0.20, 0.20, 0.05)),
        origin=Origin(xyz=(0.0, 0.0, 0.025)),
        name="base_shell",
    )
    base.inertial = Inertial.from_geometry(
        Box((0.20, 0.20, 0.05)),
        mass=1.0,
        origin=Origin(xyz=(0.0, 0.0, 0.025)),
    )

    lid = model.part("lid")
    lid.visual(
        Box((0.18, 0.18, 0.02)),
        # The lid part frame sits on the hinge line; the panel extends along +X.
        origin=Origin(xyz=(0.09, 0.0, 0.01)),
        name="lid_shell",
    )
    lid.inertial = Inertial.from_geometry(
        Box((0.18, 0.18, 0.02)),
        mass=0.3,
        origin=Origin(xyz=(0.09, 0.0, 0.01)),
    )

    model.articulation(
        "base_to_lid",
        ArticulationType.REVOLUTE,
        parent=base,
        child=lid,
        # Positive q should open the lid upward, not into the base.
        # Because the closed lid extends along local +X from the hinge,
        # choose -Y so positive rotation lifts the free edge toward +Z.
        origin=Origin(xyz=(-0.09, 0.0, 0.05)),
        axis=(0.0, -1.0, 0.0),
        motion_limits=MotionLimits(effort=5.0, velocity=3.0, lower=0.0, upper=1.2),
    )

    return model


def run_tests() -> TestReport:
    ctx = TestContext(object_model)
    base = object_model.get_part("base")
    lid = object_model.get_part("lid")
    hinge = object_model.get_articulation("base_to_lid")

    ctx.check_model_valid()
    ctx.check_mesh_assets_ready()
    ctx.fail_if_isolated_parts()
    ctx.warn_if_part_contains_disconnected_geometry_islands()
    ctx.fail_if_parts_overlap_in_current_pose()

    with ctx.pose({hinge: 0.0}):
        ctx.expect_gap(lid, base, axis="z", max_gap=0.001, max_penetration=0.0)
        ctx.expect_overlap(lid, base, axes="xy", min_overlap=0.05)

    return ctx.report()


object_model = build_object_model()
```

This example uses a hinge-line part frame for the lid. At `q=0`, the child
frame coincides with the articulation frame at the left edge of the lid. Since
the closed lid panel extends along local `+X` from that hinge, `axis=(0, -1, 0)`
makes positive angles open upward.

`ctx.fail_if_isolated_parts()` also catches floating multi-part groups that are
internally connected to each other but disconnected from the rooted body.

## Recommended Workflow

1. Build parts with `model.part(...)`.
2. Add visuals with `part.visual(...)`.
3. Add inertials when needed with `Inertial.from_geometry(...)`.
4. Add motion with `model.articulation(...)`.
5. Keep `run_tests()` focused on the default QC stack plus prompt-specific
   `expect_*` assertions.

## See Also

- `20_core_types.md` for geometry, material, inertial, and motion types
- `30_articulated_object.md` for model authoring and lookup helpers
- `50_placement.md` for mounting and wrapping helpers
- `70_probe_tooling.md` for inspection helpers
- `80_testing.md` for the full testing API
