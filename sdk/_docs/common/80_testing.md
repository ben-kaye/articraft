# Testing

Import from top-level `sdk`:

```python
from sdk import TestContext, TestFailure, TestReport
```

`TestContext` is the SDK test harness for authored models. It records blocking
failures, non-blocking warnings, and explicit allowances, then returns a
`TestReport` from `run_tests()`.

## Public Types

### `TestFailure`

```python
TestFailure(name: str, details: str)
```

- `name`: recorded check name.
- `details`: failure detail string stored in the report.

### `TestReport`

```python
TestReport(
    passed: bool,
    checks_run: int,
    checks: tuple[str, ...],
    failures: tuple[TestFailure, ...],
    warnings: tuple[str, ...] = (),
    allowances: tuple[str, ...] = (),
    allowed_isolated_parts: tuple[str, ...] = (),
)
```

- `passed`: `True` when no blocking failures were recorded.
- `checks_run`: number of recorded checks.
- `checks`: ordered check names.
- `failures`: blocking failures.
- `warnings`: warning messages and failed warning-tier checks.
- `allowances`: human-readable entries recorded by `allow_*`.
- `allowed_isolated_parts`: names of parts explicitly allowed by `allow_isolated_part(...)`.

## Construction

```python
ctx = TestContext(model, asset_root=None, seed=0)
```

- `model`: the `ArticulatedObject` under test.
- `asset_root`: optional root used to resolve relative mesh paths. Pass this when
  the model uses mesh files and did not already capture assets via
  `AssetContext.from_script(...)`.
- `seed`: deterministic sampling seed for pose-sampled checks.

Generated models should end `run_tests()` with:

```python
return ctx.report()
```

## Recommended Baseline

Use this as the default scaffold for new tests:

```python
ctx.check_model_valid()
ctx.check_mesh_files_exist()
ctx.fail_if_isolated_parts()
ctx.warn_if_part_contains_disconnected_geometry_islands()
ctx.fail_if_parts_overlap_in_current_pose()
```

Then add prompt-specific exact assertions such as `expect_gap(...)`,
`expect_overlap(...)`, `expect_contact(...)`, and `expect_within(...)`.

For bounded `REVOLUTE` and `PRISMATIC` joints, also add explicit lower/upper
pose checks for both no overlap and no floating:

```python
hinge = object_model.get_articulation("lid_hinge")
limits = hinge.motion_limits
if limits is not None and limits.lower is not None and limits.upper is not None:
    with ctx.pose({hinge: limits.lower}):
        ctx.fail_if_parts_overlap_in_current_pose(name="lid_hinge_lower_no_overlap")
        ctx.fail_if_isolated_parts(name="lid_hinge_lower_no_floating")
    with ctx.pose({hinge: limits.upper}):
        ctx.fail_if_parts_overlap_in_current_pose(name="lid_hinge_upper_no_overlap")
        ctx.fail_if_isolated_parts(name="lid_hinge_upper_no_floating")
```

This pattern is not applicable to `CONTINUOUS` joints because they do not expose
finite `lower` / `upper` limits.

`ctx.fail_if_isolated_parts()` and `find_unsupported_parts()` use
grounded-component semantics: they group parts by actual physical contact and
flag any floating connected component that has no rooted body part. This catches
detached groups such as `lid + top_vent`, not only singleton orphan parts.

## Parameter Conventions

These rules apply across the API unless a method says otherwise.

- `link_*`, `part`, `positive_link`, `negative_link`, `inner_link`, and
  `outer_link` accept either a `Part` object or a part name string. The API uses
  both `link` and `part` terminology; both refer to authored parts.
- `elem_*`, `positive_elem`, `negative_elem`, `inner_elem`, and `outer_elem`
  accept either a named `Visual` object or a visual name string belonging to the
  referenced part.
- `axis` must be `"x"`, `"y"`, or `"z"` and always refers to the positive world
  axis direction.
- `axes` accepts `"x"`, `"y"`, `"z"`, combinations such as `"xy"`, or a sequence
  such as `("x", "y")`.
- Distances and tolerances are meters.
- `name` overrides the recorded check name in the final report.
- `max_pose_samples` controls how many sampled articulation poses are checked.
- `contact_tol=None`, `overlap_tol=None`, and `overlap_volume_tol=None` mean
  “use the SDK default”.

## Reporting Helpers

### `report() -> TestReport`

Returns the final report for the checks recorded so far.

### `check(name: str, ok: bool, details: str = "") -> bool`

Records a custom blocking check.

- `name`: report name.
- `ok`: pass/fail result.
- `details`: stored when `ok` is `False`.

### `fail(name: str, details: str) -> bool`

Convenience wrapper for `check(name, False, details)`.

### `warn(text: str) -> None`

Appends a non-blocking warning string to the report.

## Allowances

### `allow_overlap(link_a, link_b, *, reason, elem_a=None, elem_b=None) -> None`

Records an intentional real 3D interpenetration so overlap checks do not fail on
that case. Do not use this just because one part sits inside another part's
footprint or cavity.

- `reason`: required justification string.
- `elem_a`, `elem_b`: optional element-level scope. If omitted, the allowance
  applies to the full part pair.

### `allow_isolated_part(part, *, reason) -> None`

Records that a named part is allowed to remain isolated in
`fail_if_isolated_parts(...)`.

If the intentional floating assembly is a multi-part group, allow each authored
part in that group.

### `allow_coplanar_surfaces(link_a, link_b, *, reason, elem_a=None, elem_b=None) -> None`

Records an intentional coplanar-surface relationship for
`warn_if_coplanar_surfaces(...)`.

## Pose and World-Space Queries

### `pose(joint_positions: dict[object, float] | None = None, **kwargs: float) -> Iterator[None]`

Temporary pose override context manager.

```python
with ctx.pose({hinge: 0.5}):
    ...

with ctx.pose(hinge=0.5):
    ...
```

- `joint_positions`: mapping of articulation object or joint name to position.
- `**kwargs`: joint-name shorthand.
- Restores the previous pose on exit.

### `part_world_position(part) -> tuple[float, float, float] | None`

Returns the part origin position in world coordinates for the current pose.

### `link_world_position(link) -> tuple[float, float, float] | None`

Alias for `part_world_position(...)`.

### `part_world_aabb(part) -> tuple[Vec3, Vec3] | None`

Returns the world-space AABB of the full part in the current pose.

### `link_world_aabb(link) -> tuple[Vec3, Vec3] | None`

Alias for `part_world_aabb(...)`.

### `part_element_world_aabb(part, *, elem) -> tuple[Vec3, Vec3] | None`

Returns the world-space AABB of one named visual element on a part.

## Structural and QC Checks

All methods in this section record a named check and return `True` on pass,
`False` on fail.

### `check_model_valid() -> bool`

Runs `model.validate(strict=True)`.

### `check_mesh_files_exist() -> bool`

Verifies that every referenced mesh file exists after resolving relative paths
against `asset_root`.

### `fail_if_articulation_origin_far_from_geometry(*, tol=0.015, reason=None, name=None) -> bool`

Fails when an articulation origin is farther than `tol` from nearby geometry.

- `tol`: non-negative absolute tolerance in meters.
- `reason`: optional note recorded as a warning when using a relaxed tolerance.

Available, but not part of the recommended default stack because the tolerance
is absolute rather than scale-aware.

### `warn_if_articulation_origin_far_from_geometry(*, tol=0.015, reason=None, name=None) -> bool`

Warning-tier version of the same check.

Available, but no longer recommended as a blanket default for new generated
tests.

### `fail_if_part_contains_disconnected_geometry_islands(*, tol=1e-6, name=None) -> bool`

Fails when one part contains disconnected geometry islands.

- `tol`: non-negative contact tolerance used when deciding connectivity.

### `warn_if_part_contains_disconnected_geometry_islands(*, tol=1e-6, name=None) -> bool`

Warning-tier version of the same connectivity check. This is the recommended
default.

### `fail_if_isolated_parts(*, max_pose_samples=1, contact_tol=None, name=None) -> bool`

Fails when a support-connected component is unsupported or floating in the
checked pose set.

This catches disconnected floating groups such as `lid + top_vent`, not only
singleton parts.

- `max_pose_samples`: number of sampled poses to inspect. `1` means only the
  current pose.
- `contact_tol`: non-negative support/contact tolerance.

### `fail_if_parts_overlap_in_current_pose(*, overlap_tol=None, overlap_volume_tol=None, name=None) -> bool`

Fails when distinct parts overlap in the current pose.

- `overlap_tol`: per-axis overlap tolerance.
- `overlap_volume_tol`: minimum overlap volume tolerance.

This is the recommended default overlap gate.

### `fail_if_parts_overlap_in_sampled_poses(*, max_pose_samples=128, overlap_tol=None, overlap_volume_tol=None, ignore_adjacent=False, ignore_fixed=True) -> bool`

Fails on sampled-pose overlaps across the full model.

- `ignore_adjacent`: ignore directly articulated parent/child pairs.
- `ignore_fixed`: ignore `FIXED` articulation pairs.

Use when a broader pose sweep is required than the rest-pose default.

### `fail_if_articulation_overlaps(*, max_pose_samples=128, overlap_tol=None, overlap_volume_tol=None, name=None) -> bool`

Fails on sampled overlaps only for `REVOLUTE`, `PRISMATIC`, and `CONTINUOUS`
parent/child articulation pairs.

### `warn_if_articulation_overlaps(*, max_pose_samples=128, overlap_tol=None, overlap_volume_tol=None, name=None) -> bool`

Warning-tier articulation overlap sweep. Use when articulation clearance is
important but not a blocking requirement.

### `warn_if_overlaps(*, max_pose_samples=128, overlap_tol=None, overlap_volume_tol=None, ignore_adjacent=False, ignore_fixed=True, name=None) -> bool`

Warning-tier sampled overlap sweep across the model.

Available, but no longer recommended as a blanket scaffold default for new
tests.

### `warn_if_coplanar_surfaces(*, max_pose_samples=32, plane_tol=0.001, min_overlap=0.02, min_overlap_ratio=0.35, ignore_adjacent=True, ignore_fixed=True, name=None) -> bool`

Warning-tier heuristic for suspicious coplanar or nearly coplanar surfaces.

- `plane_tol`: maximum plane separation.
- `min_overlap`: minimum in-plane overlap distance on both in-plane axes.
- `min_overlap_ratio`: minimum overlap area ratio, in `[0, 1]`.
- `ignore_adjacent`, `ignore_fixed`: same meaning as the sampled overlap checks.

Use only when this specific heuristic answers a real uncertainty.

## Exact Assertions

All methods in this section record a named check and return `True` on pass,
`False` on fail.

### `expect_origin_distance(link_a, link_b, *, axes="xy", min_dist=0.0, max_dist=None, name=None) -> bool`

Checks the distance between part origins along the requested axes.

- `min_dist`: inclusive lower bound.
- `max_dist`: optional inclusive upper bound.

### `expect_origin_gap(positive_link, negative_link, *, axis, min_gap=0.0, max_gap=None, name=None) -> bool`

Checks the signed origin-to-origin gap along one positive world axis.

- `positive_link`: object expected on the positive side of the axis.
- `negative_link`: object expected on the negative side of the axis.
- `min_gap`: inclusive lower bound.
- `max_gap`: optional inclusive upper bound.

### `expect_contact(link_a, link_b, *, contact_tol=1e-6, elem_a=None, elem_b=None, name=None) -> bool`

Checks exact minimum distance between two parts or two named elements.

- `contact_tol`: maximum allowed separation to still count as contact.
- `elem_a`, `elem_b`: optional named element scope.

### `expect_gap(positive_link, negative_link, *, axis, min_gap=None, max_gap=None, max_penetration=None, positive_elem=None, negative_elem=None, name=None) -> bool`

Checks signed exact-geometry gap along a positive world axis.

- The measured gap is `positive.min[axis] - negative.max[axis]`.
- `min_gap`: inclusive lower bound. If omitted, it is derived from
  `max_penetration`.
- `max_gap`: optional inclusive upper bound.
- `max_penetration`: convenience way to express the allowed overlap depth;
  equivalent to a lower bound of `-max_penetration`.
- `positive_elem`, `negative_elem`: optional named element scope.

This is the main exact clearance and seating helper.

### `expect_overlap(link_a, link_b, *, axes="xy", min_overlap=0.0, elem_a=None, elem_b=None, name=None) -> bool`

Checks exact projected overlap between two parts or named elements. This is a
footprint/projection check, not a collision/contact check.

- `min_overlap`: required overlap on every requested axis.
- `elem_a`, `elem_b`: optional named element scope.

### `expect_within(inner_link, outer_link, *, axes="xy", margin=0.0, inner_elem=None, outer_elem=None, name=None) -> bool`

Checks that one part or named element stays within another on the requested
axes.

- `margin`: allowed slack outside the outer bounds.
- `inner_elem`, `outer_elem`: optional named element scope.

## Minimal Example

```python
from pathlib import Path

from sdk import TestContext

HERE = Path(__file__).resolve().parent


def run_tests(object_model):
    ctx = TestContext(object_model, asset_root=HERE, seed=0)

    base = object_model.get_part("base")
    lid = object_model.get_part("lid")
    hinge = object_model.get_articulation("lid_hinge")

    ctx.check_model_valid()
    ctx.check_mesh_files_exist()
    ctx.fail_if_isolated_parts()
    ctx.warn_if_part_contains_disconnected_geometry_islands()
    ctx.fail_if_parts_overlap_in_current_pose()

    with ctx.pose({hinge: 0.0}):
        ctx.expect_gap(lid, base, axis="z", max_gap=0.001, max_penetration=0.0)
        ctx.expect_overlap(lid, base, axes="xy", min_overlap=0.05)

    return ctx.report()
```
