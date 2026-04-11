# Panels and Grilles

## Purpose

Use these helpers when the visible result should read as one connected panel
face with repeated openings or louvers, rather than a hand-assembled set of
floating bars and boxes.

## Import

```python
from sdk import (
    PerforatedPanelGeometry,
    SlotPatternPanelGeometry,
    VentGrilleGeometry,
    mesh_from_geometry,
)
```

## Recommended APIs

| Shape intent | Helper |
| --- | --- |
| Round-hole speaker, appliance, or cover plate | `PerforatedPanelGeometry` |
| Rounded-slot filter, grille, or intake face | `SlotPatternPanelGeometry` |
| Complete vent/register shell with fused slats and rear sleeve | `VentGrilleGeometry` |

## API Reference

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
- Use this for a full vent/register face, not for a loose louver insert.

## Advice

- Use a panel helper when the face should read as one stamped, cut, or molded
  piece with repeated openings.
- Use explicit bars, rods, or wires only when the object should read as a true
  assembled cage or frame.
- Leave a visible border frame on consumer and appliance panels unless the real
  object is genuinely edge-to-edge perforated.

## Examples

### Round perforated face

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

### Slotted filter face

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

### Wall vent shell

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

- `40_mesh_geometry.md` for low-level extrudes, sweeps, profiles, and export
- `45_wires.md` for true wire/cage geometry
- For a fuller worked script, see the base SDK wall vent/register example.
