# Procedural Meshes (`sdk.mesh`)

## Purpose

Use these helpers when the visible shape should be authored as procedural mesh
geometry and then exported as an OBJ-backed `sdk.Mesh`.

## Import

```python
from sdk import (
    MeshGeometry,
    BoxGeometry,
    CapsuleGeometry,
    CylinderGeometry,
    ConeGeometry,
    DomeGeometry,
    SphereGeometry,
    TorusGeometry,
    LatheGeometry,
    LoftGeometry,
    ExtrudeGeometry,
    ExtrudeWithHolesGeometry,
    PerforatedPanelGeometry,
    SlotPatternPanelGeometry,
    ClevisBracketGeometry,
    PivotForkGeometry,
    TrunnionYokeGeometry,
    FanRotorGeometry,
    BlowerWheelGeometry,
    VentGrilleGeometry,
    SweepGeometry,
    rounded_rect_profile,
    superellipse_profile,
    sample_catmull_rom_spline_2d,
    sample_cubic_bezier_spline_2d,
    superellipse_side_loft,
    split_superellipse_side_loft,
    resample_side_sections,
    cut_opening_on_face,
    mesh_from_geometry,
)
```

## Recommended Surface

- `MeshGeometry`
- primitive builders: `BoxGeometry`, `CylinderGeometry`, `ConeGeometry`,
  `SphereGeometry`, `DomeGeometry`, `CapsuleGeometry`, `TorusGeometry`
- loft/extrude/sweep builders: `LatheGeometry`, `ExtrudeGeometry`,
  `ExtrudeWithHolesGeometry`, `PerforatedPanelGeometry`,
  `SlotPatternPanelGeometry`, `VentGrilleGeometry`, `SweepGeometry`
- bracket/fan helpers: `ClevisBracketGeometry`, `PivotForkGeometry`,
  `TrunnionYokeGeometry`, `FanRotorGeometry`, `BlowerWheelGeometry`
- profile helpers: `rounded_rect_profile`, `superellipse_profile`
- shell helpers: `superellipse_side_loft`, `split_superellipse_side_loft`,
  `resample_side_sections`
- `cut_opening_on_face(...)`
- `mesh_from_geometry(...)`

## Core Mesh Type

### `MeshGeometry`

```python
MeshGeometry(
    vertices: list[tuple[float, float, float]] = [],
    faces: list[tuple[int, int, int]] = [],
)
```

Methods:

```python
geom.add_vertex(x, y, z) -> int
geom.add_face(a, b, c) -> None
geom.copy() -> MeshGeometry
geom.clone() -> MeshGeometry
geom.merge(other) -> MeshGeometry
geom.translate(dx, dy, dz) -> MeshGeometry
geom.scale(sx, sy=None, sz=None) -> MeshGeometry
geom.rotate(axis, angle, origin=(0.0, 0.0, 0.0)) -> MeshGeometry
geom.rotate_x(angle) -> MeshGeometry
geom.rotate_y(angle) -> MeshGeometry
geom.rotate_z(angle) -> MeshGeometry
geom.to_obj() -> str
geom.save_obj(path) -> None
```

- Vertices are 3D points in meters.
- Faces are 0-based triangle indices.
- All transforms mutate in place and return `self`.

## Primitive Builders

```python
BoxGeometry(size)
CylinderGeometry(radius, height, *, radial_segments=24, closed=True)
ConeGeometry(radius, height, *, radial_segments=24, closed=True)
SphereGeometry(radius, *, width_segments=24, height_segments=16)
DomeGeometry(radius, *, radial_segments=24, height_segments=12, closed=True)
CapsuleGeometry(radius, length, *, radial_segments=24, height_segments=8)
TorusGeometry(radius, tube, *, radial_segments=16, tubular_segments=32)
```

Notes:

- `BoxGeometry` is centered at the origin.
- `CylinderGeometry` and `ConeGeometry` are centered and extend along local `Z`.
- `CapsuleGeometry.length` is the cylindrical mid-section length between caps.
- `DomeGeometry` builds the upper half with its base on `z=0`.

## Loft / Extrude / Sweep Builders

### `LatheGeometry`

```python
LatheGeometry(profile, *, segments=32, closed=True)
LatheGeometry.from_shell_profiles(
    outer_profile,
    inner_profile,
    *,
    segments=32,
    start_cap="flat",
    end_cap="flat",
    lip_samples=6,
)
```

- `profile`: iterable of `(radius, z)` points.
- Radii must be non-negative.
- `from_shell_profiles(...)` is the recommended entry point for thin-walled
  revolved shells.

### `LoftGeometry`

```python
LoftGeometry(profiles, *, cap=True, closed=True)
```

- `profiles`: iterable of 3D point loops.
- All profiles must have the same point count.
- This is a low-level mesh loft helper. Prefer `section_loft(...)` for new
  authored shell work.

### `ExtrudeGeometry`

```python
ExtrudeGeometry(profile, height, *, cap=True, center=True, closed=True)
ExtrudeGeometry.centered(profile, height, *, cap=True, closed=True)
ExtrudeGeometry.from_z0(profile, height, *, cap=True, closed=True)
```

- `profile`: 2D closed profile in local XY.
- `height`: positive extrusion length along Z.

### `ExtrudeWithHolesGeometry`

```python
ExtrudeWithHolesGeometry(
    outer_profile,
    hole_profiles,
    height,
    *,
    cap=True,
    center=True,
    closed=True,
)
```

- `outer_profile`: outer 2D loop.
- `hole_profiles`: zero or more through-cut loops inside the outer profile.

### `PerforatedPanelGeometry`

```python
PerforatedPanelGeometry(
    panel_size,
    thickness,
    *,
    hole_diameter,
    pitch,
    frame: float = 0.008,
    corner_radius: float = 0.0,
    stagger: bool = False,
    center: bool = True,
)
```

- Builds a rectangular plate with a centered grid of round through-holes.
- `panel_size`: `(width, height)` in local XY.
- `pitch`: either a scalar or `(x_pitch, y_pitch)`.
- `stagger=True` offsets alternating rows by half of the X pitch.
- `frame` reserves a solid border margin around the perforated region.
- `center=False` places the rear face on `z=0`.

### `SlotPatternPanelGeometry`

```python
SlotPatternPanelGeometry(
    panel_size,
    thickness,
    *,
    slot_size,
    pitch,
    frame: float = 0.008,
    corner_radius: float = 0.0,
    slot_angle_deg: float = 0.0,
    stagger: bool = False,
    center: bool = True,
)
```

- Builds a rectangular plate with rounded through-slots.
- `slot_size`: `(length, width)` of each slot before rotation.
- `pitch`: either a scalar or `(x_pitch, y_pitch)`.
- `slot_angle_deg` uses degrees.
- `frame` reserves a solid border margin around the slot field.
- `center=False` places the rear face on `z=0`.

### `ClevisBracketGeometry`

```python
ClevisBracketGeometry(
    overall_size,
    *,
    gap_width,
    bore_diameter,
    bore_center_z,
    base_thickness,
    corner_radius: float = 0.0,
    center: bool = True,
)
```

- Builds a U-shaped clevis with a bottom base and a transverse bore.
- `overall_size`: `(width_x, depth_y, height_z)`.
- `gap_width` is the clear spacing between the cheeks.
- `bore_center_z` is measured upward from the bottom face.
- This is a good default for pinned brackets and linkage end mounts.
- `center=False` places the bottom mounting face on `z=0`.

### `PivotForkGeometry`

```python
PivotForkGeometry(
    overall_size,
    *,
    gap_width,
    bore_diameter,
    bore_center_z,
    bridge_thickness,
    corner_radius: float = 0.0,
    center: bool = True,
)
```

- Builds an open-front fork with two tines and a rear bridge.
- `overall_size`: `(width_x, depth_y, height_z)`.
- `gap_width` is the clear spacing between the tines.
- `bridge_thickness` is the rear connecting bridge thickness along local `Y`.
- `bore_center_z` is measured upward from the bottom face.
- This is useful when the front of the fork must stay open for insertion.

### `TrunnionYokeGeometry`

```python
TrunnionYokeGeometry(
    overall_size,
    *,
    span_width,
    trunnion_diameter,
    trunnion_center_z,
    base_thickness,
    corner_radius: float = 0.0,
    center: bool = True,
)
```

- Builds a trunnion support yoke with cheek-mounted trunnion bores.
- `overall_size`: `(width_x, depth_y, height_z)`.
- `span_width` is the clear opening between the cheeks.
- `trunnion_center_z` is measured upward from the bottom face.
- This is intended for yokes that cradle a rotating trunnion or barrel.
- `center=False` places the base on `z=0`.

### `FanRotorGeometry`

```python
FanRotorGeometry(
    outer_radius,
    hub_radius,
    blade_count,
    *,
    thickness,
    blade_pitch_deg: float = 28.0,
    blade_sweep_deg: float = 20.0,
    blade_root_chord=None,
    blade_tip_chord=None,
    center: bool = True,
)
```

- Builds an axial fan rotor that spins about local `Z`.
- `thickness` controls the hub thickness and overall blade section depth.
- `blade_pitch_deg` and `blade_sweep_deg` use degrees.
- `blade_root_chord` and `blade_tip_chord` let you widen or taper the blades.
- Use this for exposed axial rotors such as PC, appliance, or small cooling fans.
- `center=False` places the rear-most face on `z=0`.

### `BlowerWheelGeometry`

```python
BlowerWheelGeometry(
    outer_radius,
    inner_radius,
    width,
    blade_count,
    *,
    blade_thickness,
    blade_sweep_deg: float = 35.0,
    backplate: bool = True,
    shroud: bool = True,
    center: bool = True,
)
```

- Builds a squirrel-cage blower wheel that spins about local `Z`.
- `width` is the overall axial width along local `Z`.
- `blade_thickness` controls the blade arc thickness in plan view.
- `backplate=False` and `shroud=False` produce a lighter visual variant.
- The vane passages open into the interior drum cavity rather than stopping at a flat inner wall.
- `center=False` places the rear-most face on `z=0`.

### `VentGrilleGeometry`

```python
VentGrilleGeometry(
    panel_size,
    *,
    frame: float = 0.012,
    face_thickness: float = 0.004,
    duct_depth: float = 0.026,
    duct_wall: float = 0.003,
    slat_pitch: float = 0.018,
    slat_width: float = 0.009,
    slat_angle_deg: float = 35.0,
    slat_thickness: float | None = None,
    corner_radius: float = 0.0,
)
```

- Builds a vent grille shell with true open slots, fused slats, and a shallow
  rear sleeve.
- `panel_size`: `(width, height)` of the front flange.
- The front flange is centered on local `z=0`; the sleeve extends toward `-Z`.
- `slat_pitch` must be greater than `slat_width`.
- `slat_angle_deg` uses degrees.
- This helper is intended for complete vent/register-style shells rather than
  a standalone louver insert panel.

### Choosing Panel vs Member Construction

- Use perforated, slotted, or cutout panel strategies when the visible result
  should read as one connected face with repeated openings.
- Use explicit bars, rings, rods, or similar member-by-member construction only
  when the visible result should read as an assembly of discrete members.
- When choosing between these approaches, preserve the visible manufacturing
  logic of the object before optimizing for convenience.

### `SweepGeometry`

```python
SweepGeometry(profile, path, *, cap=False, closed=True)
```

- `profile`: 2D profile.
- `path`: 3D path points.
- Use this only for simple translational sweeps. For tube- and rail-like parts,
  see `45_wires.md`.

## Profile and Shell Helpers

### `rounded_rect_profile(...)`

```python
rounded_rect_profile(
    width: float,
    height: float,
    radius: float,
    *,
    corner_segments: int = 6,
) -> list[tuple[float, float]]
```

### `superellipse_profile(...)`

```python
superellipse_profile(
    width: float,
    height: float,
    exponent: float = 2.6,
    *,
    segments: int = 48,
) -> list[tuple[float, float]]
```

### `sample_catmull_rom_spline_2d(...)`

```python
sample_catmull_rom_spline_2d(
    points,
    *,
    samples_per_segment: int = 12,
    closed: bool = False,
    alpha: float = 0.5,
) -> list[tuple[float, float]]
```

### `sample_cubic_bezier_spline_2d(...)`

```python
sample_cubic_bezier_spline_2d(
    control_points,
    *,
    samples_per_segment: int = 12,
) -> list[tuple[float, float]]
```

### `superellipse_side_loft(...)`

```python
superellipse_side_loft(
    sections,
    *,
    exponents=2.8,
    segments: int = 56,
    cap: bool = True,
    closed: bool = True,
    min_height: float = 0.0001,
    min_width: float = 0.0001,
) -> MeshGeometry
```

### `split_superellipse_side_loft(...)`

```python
split_superellipse_side_loft(
    sections,
    *,
    split_y: float,
    exponents=2.8,
    segments: int = 56,
    cap: bool = True,
    closed: bool = True,
    min_height: float = 0.0001,
    min_width: float = 0.0001,
) -> tuple[MeshGeometry, MeshGeometry, tuple[float, float, float, float]]
```

### `resample_side_sections(...)`

```python
resample_side_sections(
    sections,
    *,
    samples_per_span: int = 2,
    smooth_passes: int = 0,
    min_height: float = 0.0001,
    min_width: float = 0.0001,
) -> list[tuple[float, float, float, float]]
```

## Panel Openings

### `cut_opening_on_face(...)`

```python
cut_opening_on_face(
    shell_geometry: MeshGeometry,
    *,
    face: str,
    opening_profile,
    depth: float,
    offset=(0.0, 0.0),
    taper: float = 0.0,
) -> MeshGeometry
```

- Cuts an opening into the chosen box-like face of an existing mesh shell.
- `face`: one of `"+x"`, `"-x"`, `"+y"`, `"-y"`, `"+z"`, `"-z"`.

## Exporting to `sdk.Mesh`

### `mesh_from_geometry(...)`

```python
mesh_from_geometry(
    geometry: MeshGeometry,
    name: str,
) -> Mesh
```

- Materializes the mesh to an internal OBJ managed by the runtime.
- Returns an `sdk.Mesh` descriptor pointing at the managed asset.
- Use this when the final authored visual should be mesh-backed.

## Advice

### Mutating behavior

- `MeshGeometry` transforms mutate in place.
- Call `copy()` or `clone()` before reusing a base mesh in multiple variants.

### Choosing higher-level helpers

- Prefer `section_loft(...)` over raw `LoftGeometry(...)` for new shell/exterior
  loft authoring.
- Prefer the spline-first wire/tube guidance in `45_wires.md` over manual
  sweeps for rails, loops, and frames. In practice, start with
  `tube_from_spline_points(...)` or `sweep_profile_along_spline(...)` unless
  the geometry is intentionally hard-cornered.

### Exporting mesh-backed visuals

- Use procedural meshes to author visible shape.
- Convert the final mesh to `sdk.Mesh` with `mesh_from_geometry(...)`.
- Use stable logical names such as `"shell"` or `"rear_bracket"` rather than
  paths.

## Examples

```python
shell = ExtrudeGeometry(
    rounded_rect_profile(0.12, 0.08, 0.01),
    0.03,
    cap=True,
    center=True,
)
mesh = mesh_from_geometry(shell, "shell")
```

```python
lip = LatheGeometry.from_shell_profiles(
    [(0.42, -0.30), (0.55, -0.12), (0.62, 0.00)],
    [(0.30, -0.24), (0.40, -0.10), (0.48, 0.00)],
    segments=72,
    end_cap="round",
    lip_samples=10,
)
```

```python
speaker_face = PerforatedPanelGeometry(
    (0.16, 0.10),
    0.004,
    hole_diameter=0.006,
    pitch=(0.012, 0.012),
    frame=0.010,
    corner_radius=0.004,
    stagger=True,
)
mesh = mesh_from_geometry(speaker_face, "speaker_face")
```

```python
filter_face = SlotPatternPanelGeometry(
    (0.18, 0.09),
    0.004,
    slot_size=(0.024, 0.006),
    pitch=(0.032, 0.016),
    frame=0.010,
    corner_radius=0.004,
    slot_angle_deg=18.0,
    stagger=True,
)
mesh = mesh_from_geometry(filter_face, "filter_face")
```

```python
clevis = ClevisBracketGeometry(
    (0.08, 0.04, 0.06),
    gap_width=0.032,
    bore_diameter=0.012,
    bore_center_z=0.038,
    base_thickness=0.012,
)
clevis_mesh = mesh_from_geometry(clevis, "clevis")

pivot_fork = PivotForkGeometry(
    (0.08, 0.05, 0.05),
    gap_width=0.034,
    bore_diameter=0.010,
    bore_center_z=0.028,
    bridge_thickness=0.012,
)
pivot_fork_mesh = mesh_from_geometry(pivot_fork, "pivot_fork")

trunnion_yoke = TrunnionYokeGeometry(
    (0.12, 0.05, 0.08),
    span_width=0.060,
    trunnion_diameter=0.016,
    trunnion_center_z=0.050,
    base_thickness=0.014,
)
trunnion_yoke_mesh = mesh_from_geometry(trunnion_yoke, "trunnion_yoke")
```

```python
fan_rotor = FanRotorGeometry(
    0.070,
    0.020,
    5,
    thickness=0.010,
    blade_pitch_deg=24.0,
    blade_sweep_deg=14.0,
)
mesh = mesh_from_geometry(fan_rotor, "fan_rotor")
```

```python
blower_wheel = BlowerWheelGeometry(
    0.080,
    0.040,
    0.050,
    18,
    blade_thickness=0.004,
    blade_sweep_deg=25.0,
)
mesh = mesh_from_geometry(blower_wheel, "blower_wheel")
```

```python
wall_vent = VentGrilleGeometry(
    (0.18, 0.10),
    frame=0.012,
    face_thickness=0.004,
    duct_depth=0.026,
    duct_wall=0.003,
    slat_pitch=0.018,
    slat_width=0.009,
    slat_angle_deg=35.0,
    corner_radius=0.006,
)
mesh = mesh_from_geometry(wall_vent, "wall_vent")
```

## See Also

- `45_wires.md` for rails, loops, tubes, and frames
- `46_section_lofts.md` for the recommended loft API
- `50_placement.md` for wrapping and mounting mesh-backed geometry

## Clarifications for agent usage

- Angle arguments are radians and use the right-hand rule.
- `SlotPatternPanelGeometry.slot_angle_deg` uses degrees.
- `FanRotorGeometry.blade_pitch_deg` and `FanRotorGeometry.blade_sweep_deg` use degrees.
- `BlowerWheelGeometry.blade_sweep_deg` uses degrees.
- `VentGrilleGeometry.slat_angle_deg` also uses degrees.
- `LoftGeometry` validates profiles through their XY projection. End caps only behave as expected when the first and last profiles are planar at constant `z`.
- `ExtrudeGeometry(..., center=True)` produces a solid centered on the profile plane, spanning `z in [-height/2, +height/2]`. Use the `from_z0(...)` form when the intended span is `z in [0, height]`.
- `rounded_rect_profile(...)` and `superellipse_profile(...)` return centered counter-clockwise XY loops.
- `cut_opening_on_face(...)` does not subtract material from a closed solid by itself. It adds the interior throat wall geometry and works best when the target face is already open or when you perform the outer cut separately.
- The side-loft helpers use explicit section tuples in the final part frame. For `superellipse_side_loft(...)`, `split_superellipse_side_loft(...)`, and `resample_side_sections(...)`, each section is `(y, z_min, z_max, width)` with the loft axis along `+Y` and each profile section lying in `XZ`.
