# Testing

Import:

```python
from sdk import TestContext, TestFailure, TestReport
```

`TestContext` is the required test harness for generated models.

## Construction

```python
ctx = TestContext(
    object_model,
    asset_root=HERE,
    seed=0,
)
```

`TestContext` reasons about authored visual geometry. During compile/test setup, the SDK mirrors those visuals into internal collision entries for URDF export and exact geometry queries.

If the model was constructed with `ArticulatedObject(..., assets=AssetContext.from_script(__file__))`, `TestContext(object_model, ...)` can infer the mesh root automatically. If not, pass `asset_root=HERE` explicitly whenever the model uses mesh files.

## TestReport contract

Generated models should finish `run_tests()` with:

```python
return ctx.report()
```

`ctx.report()` returns a `TestReport` with these fields:

- `passed`: `True` when no blocking failures were recorded
- `checks_run`: total number of recorded checks
- `checks`: ordered check names
- `failures`: blocking `TestFailure(name, details)` entries
- `warnings`: non-blocking warning strings
- `allowances`: recorded `allow_*` justifications
- `allowed_isolated_parts`: part names explicitly allowed to remain isolated

`allowed_isolated_parts` is consumed by the compile-time isolated-part QC pass. If you intentionally allow a freestanding part in `run_tests()`, that allowance must be visible in the returned `TestReport`.

## Resolve once, assert many

Prefer object-first tests:

- At the top of `run_tests()`, resolve each needed `Part` with `object_model.get_part(...)`.
- Resolve each needed `Articulation` with `object_model.get_articulation(...)`.
- Resolve named local features from those parts with `part.get_visual(...)`, then pass the resulting `Visual` objects into `elem_a=`, `elem_b=`, `positive_elem=`, `negative_elem=`, `inner_elem=`, or `outer_elem=`.
- After that, pass only objects into `ctx.expect_*`, `ctx.allow_*`, and `ctx.pose({joint: value})`.
- Use string names only at the lookup boundary. Avoid global `REFS` bags or string-driven test calls as the main pattern.

## Default sensors and backstops

The scaffolded `run_tests()` starts from these default checks:

```python
ctx.check_model_valid()
ctx.check_mesh_files_exist()
ctx.warn_if_articulation_origin_near_geometry(tol=0.015)
ctx.warn_if_part_geometry_disconnected()
ctx.check_articulation_overlaps(max_pose_samples=128)
ctx.warn_if_coplanar_surfaces(ignore_adjacent=True, ignore_fixed=True)
ctx.warn_if_overlaps(max_pose_samples=128, ignore_adjacent=True, ignore_fixed=True)
```

Mesh-backed models:

- If any part uses `Mesh(filename="assets/meshes/...")` or `mesh_from_geometry(...)`, keep either model assets or `asset_root=...` wired into `TestContext`.
- Without that, mesh-aware checks can fail because the SDK cannot resolve relative mesh paths for compile/test/export.

What they catch:

- `warn_if_articulation_origin_near_geometry`: an exact point-to-geometry distance warning for joint placement in parent and child frames; default `tol=0.015`. The harness truncates this tolerance to 3 decimals and caps it at `0.15`.
- `warn_if_part_geometry_disconnected`: an exact within-part connectivity warning that checks whether authored visuals form disconnected geometry islands.
- `warn_if_coplanar_surfaces`: a deliberately noisy visual heuristic for nearly coplanar flush surfaces. Flush mounts, bezels, grilles, and panel seams can trigger it even when the model is acceptable.
- `check_articulation_overlaps`: a failure-tier overlap gate for non-fixed articulation-linked parent/child pairs. It is the recommended way to prove that `REVOLUTE`, `PRISMATIC`, and `CONTINUOUS` joints do not interpenetrate.
- `warn_if_overlaps`: a deliberately broad exact-geometry overlap sensor over mirrored visual geometry. It can still be noisy for thin wires, thin blades, concave shells, and other awkward geometry.

These broad checks are warning-tier sensors, not semantic proof. Add prompt-specific `expect_*` assertions as the actual regression tests for silhouette, structure, proportions, attachment, and mechanism behavior.

Recommended default:

- Keep the scaffolded broad-check block unless parameter tuning is justified.
- Include `warn_if_overlaps(...)` on every generated model as a broad warning-tier sensor, even when you do not want overlap findings to fail the run.
- Include `check_articulation_overlaps(...)` on articulated models with non-fixed joints when joint clearance is a real requirement.
- Use `warn_if_coplanar_surfaces(...)` when flush-surface duplication is genuinely a useful sensor for the object, and prefer `ignore_adjacent=True, ignore_fixed=True` unless you have a specific reason not to.

Important:

- `warn_if_articulation_origin_near_geometry(...)` is not scale-aware; its tolerance is a fixed metric distance in meters.
- A tolerance that is sensible for a compact consumer object may be too strict, too loose, or simply irrelevant for a very large assembly.
- For large objects, treat it as a loose warning sensor or omit it, then use prompt-specific `expect_*` checks to prove the actual mounting and placement claims you care about.

The harness also runs automatic isolated-part checks at compile time:

- it checks multi-part objects for parts that are not contacting any other part in the checked pose
- isolated-part findings are blocking by default because the part still does not touch anything
- an isolated-part failure should usually be treated as a real floating-geometry or bad-mount bug

If a part is intentionally freestanding in the checked pose, justify it explicitly:

```python
accent = object_model.get_part("accent")
ctx.allow_isolated_part(accent, reason="intentionally freestanding accent")
```

Use this narrowly. `ctx.allow_isolated_part(...)` records the justification in `report.allowances` and exposes the part name in `report.allowed_isolated_parts` so compile-time isolated-part QC can treat that specific case as allowed instead of blocking.

## Allowances

```python
door = object_model.get_part("door")
body = object_model.get_part("body")

ctx.allow_overlap(door, body, reason="hinge barrel nests around the pin")
ctx.allow_coplanar_surfaces(door, body, reason="flush mounted panel")
```

Use allowances narrowly. Slight intended interpenetration can be acceptable when it makes a mounted or nested assembly look attached instead of floating. For articulated mechanisms, use `ctx.allow_overlap(...)` only for specific justified cases such as bearing sleeves, hinge barrels, or enclosed hubs. Still call `ctx.warn_if_overlaps(...)` so the allowance is tracked.

Prefer these allowance entry points in new code:

- `ctx.allow_overlap(...)` for legitimate nested or sleeve-like overlap
- `ctx.allow_coplanar_surfaces(...)` for intentional flush mounts or panel seams
- `ctx.allow_isolated_part(...)` for intentionally freestanding parts in the checked pose

## Canonical helper names

Prefer this naming and helper set in new generated tests:

- use articulation terminology consistently: `object_model.get_articulation(...)`, `check_articulation_overlaps(...)`, and `warn_if_articulation_origin_near_geometry(...)`
- use `warn_if_part_geometry_disconnected(...)` for disconnected within-part geometry islands
- use exact `expect_within(...)`, `expect_gap(...)`, `expect_overlap(...)`, and `expect_contact(...)` as the primary intent checks
- use pose-specific exact checks instead of direction-only motion probes

Legacy aliases and deprecated helpers still exist for backward compatibility, but do not use them in new generated code:

- prefer `warn_if_articulation_origin_near_geometry(...)` over `warn_if_joint_origin_near_geometry(...)`
- prefer `check_articulation_origin_near_geometry(...)` over `check_joint_origin_near_geometry(...)`
- prefer `warn_if_part_geometry_disconnected(...)` over the legacy alias `warn_if_part_geometry_connected(...)`
- prefer exact `expect_*` helpers over deprecated `expect_aabb_*` helpers
- prefer pose-specific exact checks over deprecated `expect_joint_motion_axis(...)`

## Articulation-overlap QC

```python
ctx.check_articulation_overlaps(
    max_pose_samples=128,
    overlap_tol=0.001,
    overlap_volume_tol=0.0,
)
```

Use this as the failure-tier QC gate for non-fixed articulation-linked pairs.

- It checks only parent/child pairs connected by `REVOLUTE`, `PRISMATIC`, or `CONTINUOUS` articulations.
- It does not check `FIXED` or `FLOATING` pairs in v1.
- It respects `ctx.allow_overlap(...)`, which is the intended escape hatch for legitimate nested mechanisms.
- It complements rather than replaces broad `warn_if_overlaps(...)` sensing.

## Pose-aware queries

```python
lid = object_model.get_part("lid")
lid_hinge = object_model.get_articulation("lid_hinge")
```

Use temporary mechanism poses with the context manager:

```python
base = object_model.get_part("base")
frame = object_model.get_part("frame")
hinge_leaf = lid.get_visual("hinge_leaf")
frame_leaf = frame.get_visual("frame_leaf")

with ctx.pose({lid_hinge: 0.5}):
    ctx.expect_overlap(lid, base, axes="xy", min_overlap=0.05)

with ctx.pose(lid_hinge=1.0):
    ctx.expect_contact(lid, base, elem_a=hinge_leaf, elem_b=frame_leaf)
```

`ctx.pose(...)` takes either:

- a mapping of articulation object or joint name to position, for example `{hinge: 0.5}`
- keyword arguments, for example `hinge=0.5`

Do not pass positional `(joint_name, value)` arguments.

## Intent checks

Use these to encode the intended layout and motion:

- `ctx.expect_origin_distance(...)`
- `ctx.expect_origin_gap(...)`
- `ctx.expect_within(...)`
- `ctx.expect_gap(...)`
- `ctx.expect_overlap(...)`
- `ctx.expect_contact(...)`

Treat these intent checks as primary. They should carry the burden of proving that mounted parts look attached and that moving parts stay believable across key poses, while `check_articulation_overlaps(...)` enforces non-fixed joint clearance and `warn_if_overlaps(...)` remains the global backstop.

Preferred signatures:

```python
upper = object_model.get_part("upper")
lower = object_model.get_part("lower")
lid = object_model.get_part("lid")
bracket = object_model.get_part("bracket")
frame = object_model.get_part("frame")

ctx.expect_gap(upper, lower, axis="z", max_gap=0.001, max_penetration=0.0)
ctx.expect_contact(bracket, frame)
ctx.expect_overlap(lid, frame, axes="xy", min_overlap=0.05)
ctx.expect_within(bracket, frame, axes="xy")
```

`expect_gap(...)` is directional: it measures the signed gap from the positive-side geometry minimum to the negative-side geometry maximum along the chosen axis. When whole-link geometry is too broad, resolve the named `Visual` objects from the part with `part.get_visual(...)` and pass those objects directly:

```python
mount_block = base.get_visual("mount_block")
hub = arm.get_visual("hub")

ctx.expect_gap(
    arm,
    base,
    axis="z",
    max_gap=0.001,
    max_penetration=0.0,
    positive_elem=hub,
    negative_elem=mount_block,
)
```

Argument guide:

- `positive_link`, `negative_link`: the two bodies being compared, ordered by the positive-axis convention; prefer passing `Part` objects
- `axis`: the positive world axis to measure along; use `"x"`, `"y"`, or `"z"`
- `min_gap`: lower bound on the signed gap; use this when you want to allow or require a specific amount of separation
- `max_gap`: upper bound on the signed gap; use this for "must stay visually seated" style checks
- `max_penetration`: shorthand for how much overlap is allowed when `min_gap` is omitted
- `positive_elem`, `negative_elem`: optional named local features to test instead of the whole part; prefer passing the exact `Visual` objects
- `name`: override the recorded check name when the default is too generic

Practical defaults:

- use `max_gap=0.001, max_penetration=0.0` for "should look seated" checks
- add `positive_elem` / `negative_elem` when some unrelated geometry would otherwise let the check pass

For mounted or nested assemblies:

- default to near-zero `expect_gap(...)` checks unless the real object visibly has more clearance
- pair gap checks with footprint/overlap checks such as `expect_overlap(..., axes="xy", ...)` or containment checks such as `expect_within(..., axes="xy", ...)`
- use `expect_contact(...)` when the core invariant is direct touch rather than a bounded directional gap
- use `positive_elem` / `negative_elem` when the real invariant is a local mating feature such as a hinge hub, bracket cheek, collar, or seat rather than the whole part
- add pose-specific checks at important limits so the assembly still looks attached when articulated

For pairs that truly must not intersect across motion, add selective separation checks in the relevant poses rather than relying only on global overlap QC.

## Example

```python
lid = object_model.get_part("lid")
base = object_model.get_part("base")
lid_hinge = object_model.get_articulation("lid_hinge")
frame = object_model.get_part("frame")
hinge_leaf = lid.get_visual("hinge_leaf")
frame_leaf = frame.get_visual("frame_leaf")

ctx.check_model_valid()
ctx.check_mesh_files_exist()
ctx.warn_if_articulation_origin_near_geometry(tol=0.015)
ctx.warn_if_part_geometry_disconnected()
ctx.check_articulation_overlaps(max_pose_samples=128)
ctx.warn_if_coplanar_surfaces(ignore_adjacent=True, ignore_fixed=True)
ctx.warn_if_overlaps(max_pose_samples=128, ignore_adjacent=True, ignore_fixed=True)
ctx.expect_overlap(lid, base, axes="xy", min_overlap=0.05)
ctx.expect_origin_distance(lid, base, axes="xy", max_dist=0.02)
ctx.expect_gap(lid, base, axis="z", max_gap=0.001, max_penetration=0.0)
ctx.expect_gap(
    lid,
    base,
    axis="z",
    max_gap=0.001,
    max_penetration=0.0,
    positive_elem=hinge_leaf,
    negative_elem=frame_leaf,
)
ctx.expect_contact(lid, frame, elem_a=hinge_leaf, elem_b=frame_leaf)
with ctx.pose({lid_hinge: 1.0}):
    ctx.expect_overlap(lid, base, axes="xy", min_overlap=0.02)
```
