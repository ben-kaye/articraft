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

## Resolve once, assert many

Prefer object-first tests:

- At the top of `run_tests()`, resolve each needed `Part` with `object_model.get_part(...)`.
- Resolve each needed `Articulation` with `object_model.get_articulation(...)`.
- Resolve named local features from those parts with `part.get_visual(...)`, then pass the resulting `Visual` objects into `elem_a=`, `elem_b=`, `positive_elem=`, `negative_elem=`, `inner_elem=`, or `outer_elem=`.
- After that, pass only objects into `ctx.expect_*`, `ctx.allow_*`, and `ctx.pose({joint: value})`.
- For `ctx.expect_*`, keep the first body/link arguments as `Part` objects. Do not pass a `Visual` as `link_a`, `link_b`, `positive_link`, `negative_link`, `inner`, or `outer`.
- Use string names only at the lookup boundary. Avoid global `REFS` bags or string-driven test calls as the main pattern.

## Default scaffold stack

The scaffolded `run_tests()` starts from this preferred default stack:

```python
ctx.check_model_valid()
ctx.check_mesh_files_exist()
ctx.check_no_isolated_parts()
ctx.warn_if_part_geometry_disconnected()
ctx.check_no_part_overlaps()
```

Mesh-backed models:

- If any part uses `Mesh(filename="assets/meshes/...")` or `mesh_from_geometry(...)`, keep either model assets or `asset_root=...` wired into `TestContext`.
- Without that, mesh-aware checks can fail because the SDK cannot resolve relative mesh paths for compile/test/export.

What they catch:

- `check_model_valid`: structural SDK/model validation.
- `check_mesh_files_exist`: missing mesh references.
- `check_no_isolated_parts`: blocking broad-part support failures, surfaced as isolated parts.
- `warn_if_part_geometry_disconnected`: warning-tier exact within-part connectivity sensor for disconnected geometry islands.
- `check_no_part_overlaps`: blocking current-pose part-level overlap gate for broad top-level interpenetration. In the default scaffold, this means the rest pose.

These checks are scope-specific sensors, not semantic proof. Add prompt-specific `expect_*` assertions as the actual regression tests for silhouette, structure, proportions, attachment, and mechanism behavior.

Recommended default:

- Keep the scaffolded default stack.
- Treat isolated parts as broad-part floating failures.
- Treat disconnected geometry islands as within-part warning evidence by default.
- Use `allow_overlap(...)` only when a seated or nested part overlap is intentional and justified.
- Use `allow_isolated_part(...)` only when a broad isolated part is intentional and justified.
- If the object has a mounted subassembly, write explicit `expect_contact(...)`, `expect_gap(...)`, `expect_overlap(...)`, and `expect_within(...)` checks against the relevant local features.
- If support or floating is ambiguous, use `probe_model` helpers first, then encode the real invariant in `run_tests()`.
- If a warning-tier heuristic fires, investigate it with `probe_model` before editing geometry or relaxing thresholds.
- Add `warn_if_articulation_overlaps(...)` only when joint clearance is genuinely uncertain or mechanically important.
- Do not add same-part overlap hunting as a blanket default. Within-part issues are tracked canonically as disconnected geometry islands, not overlap findings.

Important:

- `warn_if_articulation_origin_near_geometry(...)` and `warn_if_overlaps(...)` are deprecated as blanket scaffold defaults in new generated code.
- `warn_if_articulation_origin_near_geometry(...)` is not scale-aware; its tolerance is a fixed metric distance in meters.
- A tolerance that is sensible for a compact consumer object may be too strict, too loose, or simply irrelevant for a very large assembly.
- For large objects, treat it as a loose warning sensor or omit it, then use prompt-specific `expect_*` checks to prove the actual mounting and placement claims you care about.

## Optional warning heuristics

Use broad warning heuristics only when they answer a concrete uncertainty that your exact tests do not already cover.

- `warn_if_articulation_overlaps(...)` is useful when joint clearance is uncertain or mechanically important.
- `warn_if_articulation_origin_near_geometry(...)` can still be useful as an opt-in point-to-geometry sanity check, but it is no longer recommended as a blanket default because it is fixed-scale and often noisy.
- `warn_if_overlaps(...)` can still be useful as an opt-in broad overlap sensor, but it is no longer recommended as a blanket default because it is noisy and underconstrained for attachment quality.

## Sensor taxonomy

This is the canonical meaning of each testing sensor family in `TestContext`.

### Structural preconditions

- `check_model_valid(...)`
  Use for SDK-level structural validation. This is not a realism check; it verifies that the articulated object is well-formed.
- `check_mesh_files_exist(...)`
  Use for mesh path hygiene. This is required whenever the model references mesh files.

### Broad-part support and isolation

- `check_no_isolated_parts(...)`
  Use as the broad-part floating failure signal. It checks whether each part is supported by contacting another part in the checked pose.
- `allow_isolated_part(...)`
  Use only when a whole part is intentionally freestanding or otherwise isolated in the checked pose.

### Within-part connectivity

- `warn_if_part_geometry_disconnected(...)`
  Use as the default within-part warning sensor. It detects disconnected geometry islands inside one part. This is the preferred scaffold helper when same-part floating should be surfaced but not block.
- `check_part_geometry_connected(...)`
  Use only when disconnected geometry islands inside one part should be treated as blocking. This is stricter than the default scaffold policy.
- `warn_if_part_geometry_connected(...)`
  Legacy alias for the warning-tier within-part connectivity sensor. Prefer `warn_if_part_geometry_disconnected(...)` in new code.

### Overlap sensors

- `check_no_part_overlaps(...)`
  Use as the default blocking overlap sensor. It checks current-pose overlap between distinct parts and aggregates findings by part pair. In the scaffold, that means rest-pose part overlap.
- `check_no_overlaps(...)`
  Use for a broader sampled-pose overlap sweep across part pairs. This is more aggressive and noisier than `check_no_part_overlaps(...)`.
- `check_articulation_overlaps(...)`
  Use when overlap across motion is a blocking requirement for articulated parent/child pairs connected by `REVOLUTE`, `PRISMATIC`, or `CONTINUOUS` joints.
- `warn_if_articulation_overlaps(...)`
  Use as a warning-tier articulation clearance sensor when joint clearance is uncertain or mechanically important.
- `warn_if_overlaps(...)`
  Use only as an opt-in broad overlap warning when a specific uncertainty remains after exact checks. Do not use it as a blanket scaffold default.
- `warn_if_coplanar_surfaces(...)`
  Use as a warning-tier heuristic for suspicious broad coplanar face relationships. This is a composition hint, not proof of an error.
- `allow_overlap(...)`
  Use to justify legitimate nested or sleeve-like part-to-part overlap.
- `allow_coplanar_surfaces(...)`
  Use to justify legitimate coplanar-surface findings when the relationship is intentional.

### Exact intent checks

- `expect_origin_distance(...)`
  Use for point-to-point placement claims between part origins.
- `expect_origin_gap(...)`
  Use for directional origin spacing claims when the origin placement itself matters.
- `expect_contact(...)`
  Use when the core invariant is direct touch between two parts or named local features.
- `expect_gap(...)`
  Use for directional seat, clearance, and separation checks. This is usually the primary exact attachment check.
- `expect_overlap(...)`
  Use for exact footprint/coverage overlap along chosen axes, typically to prove seating or footprint registration.
- `expect_within(...)`
  Use for containment or in-footprint checks, for example proving that one feature stays inside another outline.

### Deprecated exact helpers

- `expect_aabb_within(...)`
- `expect_aabb_gap(...)`
- `expect_aabb_overlap(...)`
- `expect_aabb_contact(...)`
  These older AABB-envelope helpers still exist for backward compatibility, but new code should prefer the exact `expect_*` family above.
- `expect_joint_motion_axis(...)`
  Deprecated direction-only motion probe. Prefer pose-specific exact checks in important poses.

### Low-level recorders

- `check(...)`
- `fail(...)`
- `warn(...)`
  These are low-level reporting primitives. Prefer named geometry/mechanism helpers in generated code unless you are recording a genuinely custom assertion.

## Allowances

```python
door = object_model.get_part("door")
body = object_model.get_part("body")

ctx.allow_overlap(door, body, reason="hinge barrel nests around the pin")
```

Use allowances narrowly. Slight intended interpenetration can be acceptable when it makes a mounted or nested assembly look attached instead of floating. For articulated mechanisms, use `ctx.allow_overlap(...)` only for specific justified cases such as bearing sleeves, hinge barrels, or enclosed hubs.

Prefer these allowance entry points in new code:

- `ctx.allow_overlap(...)` for legitimate nested or sleeve-like overlap

## Canonical helper names

Prefer this naming and helper set in new generated tests:

- use articulation terminology consistently: `object_model.get_articulation(...)`, `warn_if_articulation_overlaps(...)`, `check_articulation_overlaps(...)`, and `warn_if_articulation_origin_near_geometry(...)`
- use `check_no_isolated_parts(...)`, `warn_if_part_geometry_disconnected(...)`, and `check_no_part_overlaps(...)` as the preferred default signal stack
- use exact `expect_within(...)`, `expect_gap(...)`, `expect_overlap(...)`, and `expect_contact(...)` as the primary intent checks
- use `warn_if_articulation_overlaps(...)` only when joint clearance is genuinely uncertain or mechanically important
- use pose-specific exact checks instead of direction-only motion probes

Legacy aliases and deprecated helpers still exist for backward compatibility, but do not use them in new generated code:

- prefer `warn_if_articulation_origin_near_geometry(...)` over `warn_if_joint_origin_near_geometry(...)`
- prefer `check_articulation_origin_near_geometry(...)` over `check_joint_origin_near_geometry(...)`
- prefer `warn_if_part_geometry_disconnected(...)` over the legacy alias `warn_if_part_geometry_connected(...)`
- use `check_part_geometry_connected(...)` only when within-part disconnected geometry should block
- prefer exact `expect_*` helpers over deprecated `expect_aabb_*` helpers
- prefer pose-specific exact checks over deprecated `expect_joint_motion_axis(...)`

## Articulation-overlap QC

```python
ctx.warn_if_articulation_overlaps(
    max_pose_samples=128,
    overlap_tol=0.001,
    overlap_volume_tol=0.0,
)
```

Use this as an opt-in warning-tier QC sensor for non-fixed articulation-linked pairs when joint clearance is genuinely uncertain or mechanically important.

- It checks only parent/child pairs connected by `REVOLUTE`, `PRISMATIC`, or `CONTINUOUS` articulations.
- It does not check `FIXED` or `FLOATING` pairs in v1.
- It respects `ctx.allow_overlap(...)`, which is the intended escape hatch for legitimate nested mechanisms.
- It complements rather than replaces prompt-specific exact checks on the local mounting features that matter.

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

Treat these intent checks as primary. They should carry the burden of proving that mounted parts look attached and that moving parts stay believable across key poses, while optional warning heuristics remain secondary sensors.

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

The exact helpers use a two-level target pattern:

- The first body/link arguments identify the owning parts being compared.
- The optional `elem_*` / `positive_elem` / `negative_elem` / `inner_elem` / `outer_elem` kwargs narrow those part-level comparisons to specific named visuals.

Do this:

```python
base = object_model.get_part("base")
bowl = object_model.get_part("bowl")
foot_shell = base.get_visual("foot_shell")

ctx.expect_overlap(bowl, base, axes="xy", min_overlap=0.10, elem_b=foot_shell)
```

Not this:

```python
ctx.expect_overlap(bowl, foot_shell, axes="xy", min_overlap=0.10)
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

- `positive_link`, `negative_link`: the two owning bodies being compared, ordered by the positive-axis convention; pass the `Part` objects here, not `Visual` objects
- `axis`: the positive world axis to measure along; use `"x"`, `"y"`, or `"z"`
- `min_gap`: lower bound on the signed gap; use this when you want to allow or require a specific amount of separation
- `max_gap`: upper bound on the signed gap; use this for "must stay visually seated" style checks
- `max_penetration`: shorthand for how much overlap is allowed when `min_gap` is omitted
- `positive_elem`, `negative_elem`: optional named local features on those owning parts; prefer passing the exact `Visual` objects here rather than replacing the owning part arguments
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
ctx.check_no_isolated_parts()
ctx.warn_if_part_geometry_disconnected()
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

If that hinge still has uncertain clearance after the exact checks are in place, add `ctx.warn_if_articulation_overlaps(...)` as an extra sensor and investigate any warning with `probe_model` before changing geometry.
