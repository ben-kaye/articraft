# Knobs and Controls

## Purpose

Use `KnobGeometry` for rotary control caps and appliance knobs before reaching
for manual revolve-plus-detail construction.

## Import

```python
from sdk import (
    KnobGeometry,
    KnobSkirt,
    KnobGrip,
    KnobIndicator,
    KnobTopFeature,
    KnobBore,
    KnobRelief,
    mesh_from_geometry,
)
```

## Recommended APIs

| Shape intent | Helper |
| --- | --- |
| Plain appliance, range, encoder, clamp, or pointer knob | `KnobGeometry` |
| Skirt ring and flare details | `KnobSkirt` |
| Fluted, ribbed, scalloped, or knurled side detail | `KnobGrip` |
| Pointer lines, notches, wedges, dots | `KnobIndicator` |
| Caps, recesses, and top inserts | `KnobTopFeature` |
| Shaft interface details | `KnobBore` |
| Side windows, top recesses, coin slots | `KnobRelief` |

## API Reference

### `KnobGeometry`

```python
KnobGeometry(
    diameter,
    height,
    *,
    body_style: Literal["cylindrical", "tapered", "domed", "mushroom", "skirted", "hourglass"] = "cylindrical",
    top_diameter=None,
    base_diameter=None,
    crown_radius: float = 0.0,
    edge_radius: float = 0.0,
    side_draft_deg: float = 0.0,
    skirt: KnobSkirt | None = None,
    grip: KnobGrip | None = None,
    indicator: KnobIndicator | None = None,
    top_feature: KnobTopFeature | None = None,
    bore: KnobBore | None = None,
    body_reliefs: Sequence[KnobRelief] = (),
    center: bool = True,
)
```

- Builds a rotary knob aligned to local `Z`.
- `center=False` places the mounting face on `z=0`.
- Use the detail dataclasses to add visible grip, pointer, bore, and cap
  features without switching to manual mesh work.
- This helper is intended to cover plain appliance knobs, fluted or knurled
  knobs, mushroom clamp knobs, and pointer-style dial caps.

## Advice

- Start with `KnobGeometry` whenever the part is visibly a knob, even if the
  final result has multiple detail features.
- Model the shaft interface when it would be visible or when the prompt calls
  out a D-shaft, splined, or keyed connection.
- Use indicators and top features for semantic detail instead of engraving them
  manually with ad hoc booleans.

## Examples

### Range knob

```python
range_knob = KnobGeometry(
    0.042,
    0.024,
    body_style="skirted",
    top_diameter=0.034,
    skirt=KnobSkirt(0.052, 0.006, flare=0.08),
    grip=KnobGrip(style="fluted", count=18, depth=0.0014),
    indicator=KnobIndicator(style="line", mode="engraved", depth=0.0008),
    bore=KnobBore(style="d_shaft", diameter=0.006, flat_depth=0.001),
)
mesh = mesh_from_geometry(range_knob, "range_knob")
```

### Knurled encoder knob

```python
encoder_knob = KnobGeometry(
    0.020,
    0.015,
    body_style="cylindrical",
    grip=KnobGrip(style="knurled", count=36, depth=0.0008, helix_angle_deg=20.0),
    indicator=KnobIndicator(style="dot", mode="raised", angle_deg=0.0),
)
mesh = mesh_from_geometry(encoder_knob, "encoder_knob")
```

## See Also

- `40_mesh_geometry.md` for lower-level lathe, profile, and export helpers
- For a fuller worked script, see the base SDK fluted range knob example.
