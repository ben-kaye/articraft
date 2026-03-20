# Placement Helpers

Import:

```python
from sdk import (
    align_centers_xy,
    part_local_aabb,
    place_on_surface,
    place_in_front_of,
    place_on_face,
    place_on_face_uv,
    place_on_top,
    proud_for_flush_mount,
    surface_frame,
    wrap_mesh_onto_surface,
    wrap_profile_onto_surface,
)
```

Use these helpers when you need to position one thing relative to another.

The most important split is:

- Use `place_on_surface(...)` when the child stays rigid and only needs one tangent-frame mount.
- Use `wrap_profile_onto_surface(...)` when a thin authored shape must hug a curved surface.
- Use `wrap_mesh_onto_surface(...)` when you already have mesh geometry that must conform.

Quick chooser:

| Intent | Helper |
| --- | --- |
| Put one part on top of or in front of another using AABB logic | `place_on_top(...)`, `place_in_front_of(...)`, `align_centers_xy(...)` |
| Mount a part on a box-like face | `place_on_face(...)`, `place_on_face_uv(...)`, `proud_for_flush_mount(...)` |
| Query a local frame on a surface | `surface_frame(...)` |
| Rigidly mount a child on a curved target | `place_on_surface(...)` |
| Wrap a thin profile onto a surface | `wrap_profile_onto_surface(...)` |
| Wrap an existing mesh onto a surface | `wrap_mesh_onto_surface(...)` |

## AABB helpers

These are still the default tools for simple cabinet-like or stacked placement.

- `align_centers_xy(child_aabb, parent_aabb) -> Origin`
- `part_local_aabb(part, asset_root=...) -> AABB | None`
- `place_on_top(child_aabb, parent_aabb, clearance=0.0, align_xy=True) -> Origin`
- `place_in_front_of(child_aabb, parent_aabb, gap=0.0, align_yz=True) -> Origin`

## Face mounting

Use these when the parent is naturally box-like and you want a clean semantic face reference.

```python
origin = place_on_face(
    parent_part,
    "+x",
    face_pos=(0.03, 0.04),
    proud=0.005,
    asset_root=HERE,
)
```

Normalized face coordinates:

```python
origin = place_on_face_uv(
    parent_part,
    "+x",
    uv=(0.8, 0.5),
    proud=0.005,
    asset_root=HERE,
)
```

When the child is centered about its origin, `proud_for_flush_mount(...)` computes the offset needed to keep it flush instead of half-embedded:

```python
proud = proud_for_flush_mount(child_part, axis="z", clearance=0.001, asset_root=HERE)
```

This computes the offset needed so a mounted child sits flush instead of being embedded in its parent.

## Surface frames

`surface_frame(...)` is the low-level query primitive for curved targets.

```python
frame = surface_frame(
    Sphere(radius=0.10),
    direction=(1.0, 0.2, 0.1),
)
```

It returns:

- `point`: the surface point that was hit
- `normal`: the outward normal at that point
- `tangent_u`, `tangent_v`: a local tangent basis

Use `direction=...` when you want to address the target by outward direction from its center-ish region. This is the natural choice for spheres and other radial layouts.

Use `point_hint=...` when you already know a nearby world-space point and want the nearest surface point there.

Most code should not build transforms from `SurfaceFrame` manually. Prefer the higher-level helpers below unless you are authoring your own custom placement math.

## Rigid surface mounting

Use `place_on_surface(...)` when the child remains rigid and only needs one tangent-frame mount.

```python
origin = place_on_surface(
    child=button_geom,
    target=panel_shell,
    point_hint=(0.12, 0.00, 0.04),
    child_axis="+z",
    clearance=0.0005,
    spin=math.radians(15.0),
    asset_root=HERE,
)
```

Key parameters:

- `child_axis`: which local axis should point outward from the surface
- `clearance`: extra offset along the surface normal after flush mounting
- `spin`: extra rotation around the surface normal

Important: `place_on_surface(...)` returns a rigid `Origin`. It does not deform the child. This is correct for buttons, pads, tabs, and feet. It is the wrong tool for stickers, labels, plaques, or other thin shapes that must follow curvature over their full area.

## Conformal surface wrapping

### Prefer `wrap_profile_onto_surface(...)` for thin authored parts

This is the ergonomic default for decals, badges, plaques, raised trim, and similar thin geometry.

```python
wrapped = wrap_profile_onto_surface(
    profile,
    Sphere(radius=0.0915),
    thickness=0.0016,
    direction=surface_direction,
    mapping="intrinsic",
    visible_relief=0.00005,
    surface_max_edge=0.006,
)
```

The contract is:

- the profile is authored in local XY
- the visible face starts on local `z=0`
- thickness extends inward along local `-z`
- `visible_relief` controls how far the visible face sits proud of the target

This is intentionally “sticker-first” behavior.

If your wrapped part needs through-cuts, pass `hole_profiles=[...]`.

### Globe-style example

The desktop globe record uses the conformal profile path for its continent pieces. The important part looks like this:

```python
def _surface_direction(lat_deg: float, lon_deg: float) -> tuple[float, float, float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    return (
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat),
    )


profile = sample_catmull_rom_spline_2d(points, samples_per_segment=10, closed=True)

wrapped = wrap_profile_onto_surface(
    profile,
    Sphere(radius=GLOBE_RADIUS),
    thickness=0.0016,
    direction=_surface_direction(10.0, -95.0),
    mapping="intrinsic",
    visible_relief=0.00005,
    surface_max_edge=0.006,
)
```

Why this is the right API for the globe:

- the continents are thin authored outlines, not prebuilt imported meshes
- they need to preserve their 2D shape on the sphere
- they need thickness that mostly embeds inward, with only a tiny visible relief

### `mapping`

`wrap_profile_onto_surface(...)` and `wrap_mesh_onto_surface(...)` both support:

- `mapping="auto"`: prefer intrinsic wrapping when the target supports it, otherwise fall back to nearest-surface projection
- `mapping="intrinsic"`: require intrinsic wrapping and raise if unsupported
- `mapping="nearest"`: always use nearest-surface projection

Current rule of thumb:

- use `mapping="intrinsic"` for spheres and cylinder sidewalls when you care about preserving local 2D shape
- use `mapping="auto"` when you want best-effort behavior
- use `mapping="nearest"` only when you explicitly want approximation on arbitrary targets

### `surface_max_edge`

Large triangles can visually cut chords through a curved target. Lower `surface_max_edge` when the visible wrapped face is disappearing into the target between vertices.

This matters most for:

- large decals on small radii
- strongly curved targets
- thin shapes with sparse boundary sampling

Start with something modest like `surface_max_edge=0.005` to `0.01` for desktop-scale objects and tune visually.

### Use `wrap_mesh_onto_surface(...)` when you already have a mesh

If you have already built a `MeshGeometry` or loaded a `Mesh`, use `wrap_mesh_onto_surface(...)` directly:

```python
wrapped = wrap_mesh_onto_surface(
    existing_mesh,
    Cylinder(radius=0.03, length=0.20),
    direction=(1.0, 0.0, 0.0),
    child_axis="+z",
    mapping="intrinsic",
    visible_relief=0.0,
)
```

Prefer `wrap_profile_onto_surface(...)` over `wrap_mesh_onto_surface(...)` when you are starting from a 2D outline. It is easier to author, clearer to read, and now handles the common thin-part case directly.
