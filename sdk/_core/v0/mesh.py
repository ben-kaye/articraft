from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from math import acos, asin, atan2, cos, isfinite, pi, sin, sqrt, tan
from pathlib import Path
from typing import Iterable, List, Literal, Optional, Sequence, Tuple, Union

import manifold3d as _m3d
import numpy as np

from sdk._dependencies import require_cadquery

from .assets import get_active_asset_session
from .types import Box, Cylinder, Mesh, Sphere

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]
Face = Tuple[int, int, int]
Mat4 = Tuple[Tuple[float, float, float, float], ...]
LatheCapMode = Literal["flat", "round"]
_EPS = 1e-9
_OBJ_COORD_DECIMALS = 6
_OBJ_QUANT_STEP = 10.0 ** (-_OBJ_COORD_DECIMALS)
_BRIDGE_EPSILON = 0.1 * _OBJ_QUANT_STEP
logger = logging.getLogger(__name__)


def _identity_mat4() -> Mat4:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def _mat4_mul(a: Mat4, b: Mat4) -> Mat4:
    rows: list[tuple[float, float, float, float]] = []
    for i in range(4):
        row = []
        for j in range(4):
            row.append(sum(float(a[i][k]) * float(b[k][j]) for k in range(4)))
        rows.append((row[0], row[1], row[2], row[3]))
    return (rows[0], rows[1], rows[2], rows[3])


def _set_primitive_provenance(geometry: "MeshGeometry", primitive: Box | Cylinder | Sphere) -> None:
    setattr(geometry, "_primitive_source", primitive)
    setattr(geometry, "_primitive_transform", _identity_mat4())


def _clear_primitive_provenance(geometry: "MeshGeometry") -> None:
    if hasattr(geometry, "_primitive_source"):
        delattr(geometry, "_primitive_source")
    if hasattr(geometry, "_primitive_transform"):
        delattr(geometry, "_primitive_transform")


def _copy_primitive_provenance(src: "MeshGeometry", dst: "MeshGeometry") -> None:
    primitive = _primitive_source_geometry(src)
    if primitive is None:
        return
    setattr(dst, "_primitive_source", primitive)
    transform = _primitive_source_transform(src)
    if transform is not None:
        setattr(dst, "_primitive_transform", transform)


def _set_manifold_provenance(geometry: "MeshGeometry", manifold) -> None:
    setattr(geometry, "_manifold_source", manifold)


def _clear_manifold_provenance(geometry: "MeshGeometry") -> None:
    if hasattr(geometry, "_manifold_source"):
        delattr(geometry, "_manifold_source")


def _copy_manifold_provenance(src: "MeshGeometry", dst: "MeshGeometry") -> None:
    manifold = getattr(src, "_manifold_source", None)
    if manifold is not None:
        setattr(dst, "_manifold_source", manifold)


def _prepend_primitive_transform(geometry: "MeshGeometry", transform: Mat4) -> None:
    primitive = _primitive_source_geometry(geometry)
    if primitive is None:
        return
    current = _primitive_source_transform(geometry) or _identity_mat4()
    setattr(geometry, "_primitive_transform", _mat4_mul(transform, current))


def _primitive_source_geometry(geometry: "MeshGeometry") -> Box | Cylinder | Sphere | None:
    primitive = getattr(geometry, "_primitive_source", None)
    if isinstance(primitive, (Box, Cylinder, Sphere)):
        return primitive
    return None


def _primitive_source_transform(geometry: "MeshGeometry") -> Mat4 | None:
    transform = getattr(geometry, "_primitive_transform", None)
    if isinstance(transform, tuple) and len(transform) == 4:
        return transform  # type: ignore[return-value]
    return None


def _clone_primitive_geometry(geometry: Box | Cylinder | Sphere) -> Box | Cylinder | Sphere:
    if isinstance(geometry, Box):
        return Box(tuple(float(v) for v in geometry.size))
    if isinstance(geometry, Cylinder):
        return Cylinder(radius=float(geometry.radius), length=float(geometry.length))
    return Sphere(radius=float(geometry.radius))


def _mat4_vec3(mat: Mat4, vec: Vec3) -> Vec3:
    x, y, z = vec
    return (
        float(mat[0][0]) * x + float(mat[0][1]) * y + float(mat[0][2]) * z + float(mat[0][3]),
        float(mat[1][0]) * x + float(mat[1][1]) * y + float(mat[1][2]) * z + float(mat[1][3]),
        float(mat[2][0]) * x + float(mat[2][1]) * y + float(mat[2][2]) * z + float(mat[2][3]),
    )


def _rpy_from_matrix(
    mat: Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]],
) -> Vec3:
    pitch = asin(max(-1.0, min(1.0, -float(mat[2][0]))))
    cp = cos(pitch)
    if abs(cp) > 1e-6:
        roll = atan2(float(mat[2][1]), float(mat[2][2]))
        yaw = atan2(float(mat[1][0]), float(mat[0][0]))
    else:
        roll = 0.0
        yaw = atan2(-float(mat[0][1]), float(mat[1][1]))
    return (roll, pitch, yaw)


def sample_cubic_bezier_spline_2d(
    control_points: Sequence[Vec2],
    *,
    samples_per_segment: int = 12,
) -> List[Vec2]:
    """
    Sample a C1-continuous cubic Bezier spline in 2D.

    The control-point layout follows chained cubic segments:
    ``[P0, P1, P2, P3, P4, P5, P6, ...]`` where each additional segment
    contributes three points and starts at the previous segment's end.

    This is useful for "rail" curves that drive non-uniform lofts.
    """
    pts = [(float(x), float(y)) for (x, y) in control_points]
    if len(pts) < 4:
        raise ValueError("Bezier spline requires at least 4 control points")
    if (len(pts) - 1) % 3 != 0:
        raise ValueError("Bezier spline control points must satisfy (n-1) % 3 == 0")

    seg_count = (len(pts) - 1) // 3
    steps = max(2, int(samples_per_segment))

    def eval_seg(p0: Vec2, p1: Vec2, p2: Vec2, p3: Vec2, t: float) -> Vec2:
        u = 1.0 - t
        b0 = u * u * u
        b1 = 3.0 * u * u * t
        b2 = 3.0 * u * t * t
        b3 = t * t * t
        x = b0 * p0[0] + b1 * p1[0] + b2 * p2[0] + b3 * p3[0]
        y = b0 * p0[1] + b1 * p1[1] + b2 * p2[1] + b3 * p3[1]
        return (x, y)

    out: List[Vec2] = []
    for seg in range(seg_count):
        i = seg * 3
        p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        for j in range(steps):
            if seg > 0 and j == 0:
                continue
            t = float(j) / float(steps)
            out.append(eval_seg(p0, p1, p2, p3, t))
    out.append(pts[-1])
    return out


def sample_cubic_bezier_spline_3d(
    control_points: Sequence[Vec3],
    *,
    samples_per_segment: int = 12,
) -> List[Vec3]:
    """
    Sample a C1-continuous cubic Bezier spline in 3D.

    Control-point layout follows chained cubic segments:
    ``[P0, P1, P2, P3, P4, P5, P6, ...]``.
    """
    pts = [(float(x), float(y), float(z)) for (x, y, z) in control_points]
    if len(pts) < 4:
        raise ValueError("Bezier spline requires at least 4 control points")
    if (len(pts) - 1) % 3 != 0:
        raise ValueError("Bezier spline control points must satisfy (n-1) % 3 == 0")

    seg_count = (len(pts) - 1) // 3
    steps = max(2, int(samples_per_segment))

    def eval_seg(p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: float) -> Vec3:
        u = 1.0 - t
        b0 = u * u * u
        b1 = 3.0 * u * u * t
        b2 = 3.0 * u * t * t
        b3 = t * t * t
        x = b0 * p0[0] + b1 * p1[0] + b2 * p2[0] + b3 * p3[0]
        y = b0 * p0[1] + b1 * p1[1] + b2 * p2[1] + b3 * p3[1]
        z = b0 * p0[2] + b1 * p1[2] + b2 * p2[2] + b3 * p3[2]
        return (x, y, z)

    out: List[Vec3] = []
    for seg in range(seg_count):
        i = seg * 3
        p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        for j in range(steps):
            if seg > 0 and j == 0:
                continue
            t = float(j) / float(steps)
            out.append(eval_seg(p0, p1, p2, p3, t))
    out.append(pts[-1])
    return out


def _tuple_lerp(a: Sequence[float], b: Sequence[float], t: float) -> Tuple[float, ...]:
    return tuple(float(xa) + (float(xb) - float(xa)) * float(t) for xa, xb in zip(a, b))


def _tuple_extrapolate(a: Sequence[float], b: Sequence[float]) -> Tuple[float, ...]:
    return tuple(2.0 * float(xa) - float(xb) for xa, xb in zip(a, b))


def _tuple_distance(a: Sequence[float], b: Sequence[float]) -> float:
    return sqrt(sum((float(xa) - float(xb)) * (float(xa) - float(xb)) for xa, xb in zip(a, b)))


def _catmull_rom_interp(
    a: Sequence[float],
    b: Sequence[float],
    ta: float,
    tb: float,
    t: float,
) -> Tuple[float, ...]:
    if abs(tb - ta) <= _EPS:
        return tuple(float(v) for v in a)
    wa = (tb - t) / (tb - ta)
    wb = (t - ta) / (tb - ta)
    return tuple(wa * float(va) + wb * float(vb) for va, vb in zip(a, b))


def _sample_catmull_rom_segment(
    p0: Sequence[float],
    p1: Sequence[float],
    p2: Sequence[float],
    p3: Sequence[float],
    *,
    steps: int,
    alpha: float,
) -> List[Tuple[float, ...]]:
    def tj(ti: float, pa: Sequence[float], pb: Sequence[float]) -> float:
        dist = max(_tuple_distance(pa, pb), _EPS)
        return ti + dist**alpha

    t0 = 0.0
    t1 = tj(t0, p0, p1)
    t2 = tj(t1, p1, p2)
    t3 = tj(t2, p2, p3)

    out: List[Tuple[float, ...]] = []
    for j in range(steps):
        t = t1 + (t2 - t1) * (float(j) / float(steps))
        a1 = _catmull_rom_interp(p0, p1, t0, t1, t)
        a2 = _catmull_rom_interp(p1, p2, t1, t2, t)
        a3 = _catmull_rom_interp(p2, p3, t2, t3, t)
        b1 = _catmull_rom_interp(a1, a2, t0, t2, t)
        b2 = _catmull_rom_interp(a2, a3, t1, t3, t)
        out.append(_catmull_rom_interp(b1, b2, t1, t2, t))
    return out


def _sample_catmull_rom_spline(
    points: Sequence[Sequence[float]],
    *,
    samples_per_segment: int,
    closed: bool,
    alpha: float,
) -> List[Tuple[float, ...]]:
    pts = [tuple(float(v) for v in point) for point in points]
    if len(pts) < 2:
        raise ValueError("Catmull-Rom spline requires at least two points")
    if not (0.0 <= float(alpha) <= 1.0):
        raise ValueError("Catmull-Rom alpha must be in [0, 1]")

    dedup: List[Tuple[float, ...]] = [pts[0]]
    for point in pts[1:]:
        if _tuple_distance(point, dedup[-1]) > _EPS:
            dedup.append(point)

    if len(dedup) < 2:
        raise ValueError("Catmull-Rom spline requires at least two distinct points")

    steps = max(2, int(samples_per_segment))

    if closed:
        ring = list(dedup)
        if _tuple_distance(ring[0], ring[-1]) <= _EPS:
            ring.pop()
        if len(ring) < 3:
            raise ValueError("Closed Catmull-Rom spline requires at least three distinct points")

        out: List[Tuple[float, ...]] = []
        n = len(ring)
        for i in range(n):
            seg = _sample_catmull_rom_segment(
                ring[(i - 1) % n],
                ring[i],
                ring[(i + 1) % n],
                ring[(i + 2) % n],
                steps=steps,
                alpha=float(alpha),
            )
            out.extend(seg)
        if not out:
            raise ValueError("Closed Catmull-Rom spline produced no samples")
        out.append(out[0])
        return out

    if len(dedup) == 2:
        out = [_tuple_lerp(dedup[0], dedup[1], float(j) / float(steps)) for j in range(steps)]
        out.append(dedup[-1])
        return out

    extended = [
        _tuple_extrapolate(dedup[0], dedup[1]),
        *dedup,
        _tuple_extrapolate(dedup[-1], dedup[-2]),
    ]
    out = []
    for i in range(len(dedup) - 1):
        seg = _sample_catmull_rom_segment(
            extended[i],
            extended[i + 1],
            extended[i + 2],
            extended[i + 3],
            steps=steps,
            alpha=float(alpha),
        )
        out.extend(seg)
    out.append(dedup[-1])
    return out


def sample_catmull_rom_spline_2d(
    points: Sequence[Vec2],
    *,
    samples_per_segment: int = 12,
    closed: bool = False,
    alpha: float = 0.5,
) -> List[Vec2]:
    """
    Sample a centripetal Catmull-Rom spline that passes through the input points.

    This is the recommended helper when you want a smooth spline fitted through
    clicked/estimated points instead of chained Bezier control handles.
    """
    sampled = _sample_catmull_rom_spline(
        points,
        samples_per_segment=samples_per_segment,
        closed=bool(closed),
        alpha=float(alpha),
    )
    return [(float(x), float(y)) for (x, y) in sampled]


def sample_catmull_rom_spline_3d(
    points: Sequence[Vec3],
    *,
    samples_per_segment: int = 12,
    closed: bool = False,
    alpha: float = 0.5,
) -> List[Vec3]:
    """
    Sample a centripetal Catmull-Rom spline that passes through the input points.

    This is the recommended helper for tube centerlines and other fitted 3D paths.
    """
    sampled = _sample_catmull_rom_spline(
        points,
        samples_per_segment=samples_per_segment,
        closed=bool(closed),
        alpha=float(alpha),
    )
    return [(float(x), float(y), float(z)) for (x, y, z) in sampled]


def _v_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_scale(v: Vec3, s: float) -> Vec3:
    return (v[0] * s, v[1] * s, v[2] * s)


def _v_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v_cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _v_norm(v: Vec3) -> float:
    return sqrt(_v_dot(v, v))


def _v_normalize(v: Vec3) -> Vec3:
    n = _v_norm(v)
    if n <= _EPS:
        raise ValueError("Cannot normalize near-zero vector")
    return (v[0] / n, v[1] / n, v[2] / n)


def _v_rotate_rodrigues(v: Vec3, axis: Vec3, angle: float) -> Vec3:
    k = _v_normalize(axis)
    c = cos(float(angle))
    s = sin(float(angle))
    term1 = _v_scale(v, c)
    term2 = _v_scale(_v_cross(k, v), s)
    term3 = _v_scale(k, _v_dot(k, v) * (1.0 - c))
    return _v_add(_v_add(term1, term2), term3)


def _v_lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def _clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


def sample_arc_3d(
    *,
    start_point: Vec3,
    center: Vec3,
    normal: Vec3,
    angle: float,
    segments: int = 16,
) -> List[Vec3]:
    """
    Sample a circular 3D arc from `start_point` around axis (`center`, `normal`).

    `angle` is in radians and follows right-hand rule around `normal`.
    """
    start = (float(start_point[0]), float(start_point[1]), float(start_point[2]))
    ctr = (float(center[0]), float(center[1]), float(center[2]))
    n = _v_normalize((float(normal[0]), float(normal[1]), float(normal[2])))
    steps = max(2, int(segments))

    radius_vec = _v_sub(start, ctr)
    # Arc radius vector must be perpendicular to axis.
    axial = abs(_v_dot(_v_normalize(radius_vec), n)) if _v_norm(radius_vec) > _EPS else 1.0
    if _v_norm(radius_vec) <= _EPS or axial > 1.0 - 1e-6:
        raise ValueError("start_point must be away from center and not collinear with normal")

    out: List[Vec3] = []
    for i in range(steps + 1):
        t = float(i) / float(steps)
        rv = _v_rotate_rodrigues(radius_vec, n, float(angle) * t)
        out.append(_v_add(ctr, rv))
    return out


@dataclass
class WirePath:
    points: List[Vec3]

    def __init__(self, start: Vec3):
        s = (float(start[0]), float(start[1]), float(start[2]))
        self.points = [s]

    @classmethod
    def from_points(cls, points: Iterable[Vec3]) -> "WirePath":
        pts = [(float(x), float(y), float(z)) for (x, y, z) in points]
        if len(pts) < 1:
            raise ValueError("WirePath.from_points requires at least one point")
        out = cls(pts[0])
        for p in pts[1:]:
            out.line_to(p)
        return out

    def _append_if_distinct(self, p: Vec3) -> None:
        last = self.points[-1]
        if _v_norm(_v_sub(last, p)) > _EPS:
            self.points.append((float(p[0]), float(p[1]), float(p[2])))

    def line_to(self, point: Vec3) -> "WirePath":
        p = (float(point[0]), float(point[1]), float(point[2]))
        self._append_if_distinct(p)
        return self

    def line_by(self, dx: float, dy: float, dz: float) -> "WirePath":
        cur = self.points[-1]
        self._append_if_distinct((cur[0] + float(dx), cur[1] + float(dy), cur[2] + float(dz)))
        return self

    def bezier_to(
        self,
        control1: Vec3,
        control2: Vec3,
        end: Vec3,
        *,
        samples: int = 12,
    ) -> "WirePath":
        p0 = self.points[-1]
        pts = sample_cubic_bezier_spline_3d(
            [p0, control1, control2, end],
            samples_per_segment=max(2, int(samples)),
        )
        for p in pts[1:]:
            self._append_if_distinct(p)
        return self

    def arc(
        self,
        *,
        center: Vec3,
        normal: Vec3,
        angle: float,
        segments: int = 16,
    ) -> "WirePath":
        pts = sample_arc_3d(
            start_point=self.points[-1],
            center=center,
            normal=normal,
            angle=angle,
            segments=segments,
        )
        for p in pts[1:]:
            self._append_if_distinct(p)
        return self

    def extend(self, points: Iterable[Vec3]) -> "WirePath":
        for p in points:
            self.line_to(p)
        return self

    def to_points(self) -> List[Vec3]:
        return list(self.points)


def superellipse_side_loft(
    sections: Sequence[Tuple[float, float, float, float]],
    *,
    exponents: Union[float, Sequence[float]] = 2.8,
    segments: int = 56,
    cap: bool = True,
    closed: bool = True,
    min_height: float = 1e-4,
    min_width: float = 1e-4,
) -> "MeshGeometry":
    """
    Build an organic casing from side-profile rails.

    Parameters
    ----------
    sections:
        Ordered tuples ``(y, z_min, z_max, width)`` in the *final* frame.
        The loft axis is +Y, and each cross-section is a superellipse in XZ.
    exponents:
        Superellipse exponent(s). A single float applies to all sections, or
        pass one value per section.

    Notes
    -----
    Internally this uses ``LoftGeometry``'s XY-planar profile convention and
    rotates into XZ/Y world orientation. This avoids repeated ad-hoc axis
    remapping in object scripts.
    """
    if len(sections) < 2:
        raise ValueError("superellipse_side_loft requires at least two sections")

    if isinstance(exponents, (int, float)):
        expo_list = [float(exponents)] * len(sections)
    else:
        expo_list = [float(v) for v in exponents]
        if len(expo_list) != len(sections):
            raise ValueError("exponents must match section count")

    profiles: List[List[Vec3]] = []
    segs = max(12, int(segments))
    min_h = max(1e-9, float(min_height))
    min_w = max(1e-9, float(min_width))

    for i, sec in enumerate(sections):
        y, z_min, z_max, width = sec
        y = float(y)
        z0 = float(z_min)
        z1 = float(z_max)
        if z1 < z0:
            z0, z1 = z1, z0

        height = max(min_h, z1 - z0)
        width = max(min_w, float(width))
        z_center = 0.5 * (z0 + z1)
        exponent = max(0.2, float(expo_list[i]))

        prof_xy = superellipse_profile(width, height, exponent=exponent, segments=segs)
        # Map final (x, y_section, z) into LoftGeometry's expected frame:
        # pre-rotate point is (x, -(z), y_section), then rotate_x(-90deg).
        prof_xyz = [(x, -(z_local + z_center), y) for (x, z_local) in prof_xy]
        profiles.append(prof_xyz)

    geom = LoftGeometry(profiles, cap=cap, closed=closed)
    geom.rotate_x(-pi / 2.0)
    return geom


def split_superellipse_side_loft(
    sections: Sequence[Tuple[float, float, float, float]],
    *,
    split_y: float,
    exponents: Union[float, Sequence[float]] = 2.8,
    segments: int = 56,
    cap: bool = True,
    closed: bool = True,
    min_height: float = 1e-4,
    min_width: float = 1e-4,
) -> Tuple["MeshGeometry", "MeshGeometry", Tuple[float, float, float, float]]:
    """
    Split one continuous side-loft shell into two watertight halves at ``split_y``.

    This function is intended for articulated shells (for example a stand-mixer
    neck/head) where both links should share exactly the same seam profile. The
    seam rail is interpolated from neighboring source rails when needed.

    Returns
    -------
    tuple
        ``(rear_geom, front_geom, seam_section)`` where ``seam_section`` is the
        rail tuple ``(y, z_min, z_max, width)`` shared by both outputs.
    """
    raw = [(float(y), float(z0), float(z1), float(w)) for (y, z0, z1, w) in sections]
    if len(raw) < 3:
        raise ValueError("split_superellipse_side_loft requires at least three sections")

    raw.sort(key=lambda row: row[0])
    split = float(split_y)
    y_min = raw[0][0]
    y_max = raw[-1][0]
    if not (y_min < split < y_max):
        raise ValueError(f"split_y must be strictly inside section range ({y_min}, {y_max})")

    if isinstance(exponents, (int, float)):
        expo_list = [float(exponents)] * len(raw)
    else:
        expo_list = [float(v) for v in exponents]
        if len(expo_list) != len(raw):
            raise ValueError("exponents must match section count")

    # Find seam section and aligned exponent.
    seam_tol = 1e-9
    seam_section: Optional[Tuple[float, float, float, float]] = None
    seam_exponent: Optional[float] = None
    seam_idx: Optional[int] = None
    for i, row in enumerate(raw):
        if abs(row[0] - split) <= seam_tol:
            seam_section = row
            seam_exponent = expo_list[i]
            seam_idx = i
            break

    if seam_section is None:
        insert_i = None
        for i in range(len(raw) - 1):
            y0 = raw[i][0]
            y1 = raw[i + 1][0]
            if y0 <= split <= y1:
                insert_i = i
                break
        if insert_i is None:
            raise ValueError("Unable to locate split interval")

        y0, z00, z01, w0 = raw[insert_i]
        y1, z10, z11, w1 = raw[insert_i + 1]
        if abs(y1 - y0) <= seam_tol:
            raise ValueError("Adjacent sections have identical y; cannot interpolate seam")
        t = (split - y0) / (y1 - y0)

        z0 = z00 + (z10 - z00) * t
        z1 = z01 + (z11 - z01) * t
        w = w0 + (w1 - w0) * t
        seam_section = (split, z0, z1, w)
        seam_exponent = expo_list[insert_i] + (expo_list[insert_i + 1] - expo_list[insert_i]) * t
        seam_idx = insert_i

    assert seam_section is not None
    assert seam_exponent is not None
    assert seam_idx is not None

    # Build aligned rear/front rails with shared seam.
    lower_sections: List[Tuple[float, float, float, float]] = []
    lower_exp: List[float] = []
    upper_sections: List[Tuple[float, float, float, float]] = []
    upper_exp: List[float] = []

    # Existing seam at raw[seam_idx].
    if abs(raw[seam_idx][0] - split) <= seam_tol:
        for i in range(seam_idx + 1):
            lower_sections.append(raw[i])
            lower_exp.append(expo_list[i])
        for i in range(seam_idx, len(raw)):
            upper_sections.append(raw[i])
            upper_exp.append(expo_list[i])
    else:
        for i in range(seam_idx + 1):
            lower_sections.append(raw[i])
            lower_exp.append(expo_list[i])
        lower_sections.append(seam_section)
        lower_exp.append(seam_exponent)

        upper_sections.append(seam_section)
        upper_exp.append(seam_exponent)
        for i in range(seam_idx + 1, len(raw)):
            upper_sections.append(raw[i])
            upper_exp.append(expo_list[i])

    if len(lower_sections) < 2 or len(upper_sections) < 2:
        raise ValueError("split produced an invalid half with fewer than two sections")

    rear_geom = superellipse_side_loft(
        lower_sections,
        exponents=lower_exp,
        segments=segments,
        cap=cap,
        closed=closed,
        min_height=min_height,
        min_width=min_width,
    )
    front_geom = superellipse_side_loft(
        upper_sections,
        exponents=upper_exp,
        segments=segments,
        cap=cap,
        closed=closed,
        min_height=min_height,
        min_width=min_width,
    )
    return rear_geom, front_geom, seam_section


def resample_side_sections(
    sections: Sequence[Tuple[float, float, float, float]],
    *,
    samples_per_span: int = 2,
    smooth_passes: int = 0,
    min_height: float = 1e-4,
    min_width: float = 1e-4,
) -> List[Tuple[float, float, float, float]]:
    """
    Densify and optionally smooth side-loft sections.

    This helper is useful when source rails are sparse/noisy (for example when
    they are estimated from mesh slices). It linearly resamples each span in Y,
    then applies a light 3-point smoothing kernel to ``z_min``, ``z_max``, and
    ``width`` while keeping ``y`` fixed and monotonic.
    """
    raw = [(float(y), float(z0), float(z1), float(w)) for (y, z0, z1, w) in sections]
    if len(raw) < 2:
        raise ValueError("resample_side_sections requires at least two sections")

    raw.sort(key=lambda row: row[0])

    # Merge duplicate y samples by averaging rails.
    merged: List[Tuple[float, float, float, float]] = []
    for row in raw:
        if merged and abs(row[0] - merged[-1][0]) <= 1e-9:
            y0, a0, a1, aw = merged[-1]
            merged[-1] = (
                y0,
                0.5 * (a0 + row[1]),
                0.5 * (a1 + row[2]),
                0.5 * (aw + row[3]),
            )
        else:
            merged.append(row)

    if len(merged) < 2:
        y0, z0, z1, w = merged[0]
        height = max(float(min_height), z1 - z0)
        return [(y0, z0, z0 + height, max(float(min_width), w))]

    spans = max(1, int(samples_per_span))

    def lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    dense: List[Tuple[float, float, float, float]] = []
    for idx in range(len(merged) - 1):
        a = merged[idx]
        b = merged[idx + 1]
        for j in range(spans):
            if idx > 0 and j == 0:
                continue
            t = float(j) / float(spans)
            dense.append(
                (
                    lerp(a[0], b[0], t),
                    lerp(a[1], b[1], t),
                    lerp(a[2], b[2], t),
                    lerp(a[3], b[3], t),
                )
            )
    dense.append(merged[-1])

    passes = max(0, int(smooth_passes))
    if passes > 0 and len(dense) >= 3:
        for _ in range(passes):
            smoothed: List[Tuple[float, float, float, float]] = [dense[0]]
            for idx in range(1, len(dense) - 1):
                left = dense[idx - 1]
                cur = dense[idx]
                right = dense[idx + 1]
                smoothed.append(
                    (
                        cur[0],
                        0.25 * left[1] + 0.50 * cur[1] + 0.25 * right[1],
                        0.25 * left[2] + 0.50 * cur[2] + 0.25 * right[2],
                        0.25 * left[3] + 0.50 * cur[3] + 0.25 * right[3],
                    )
                )
            smoothed.append(dense[-1])
            dense = smoothed

    min_h = max(1e-9, float(min_height))
    min_w = max(1e-9, float(min_width))
    out: List[Tuple[float, float, float, float]] = []
    for y, z0, z1, w in dense:
        low = float(min(z0, z1))
        high = float(max(z0, z1))
        if high - low < min_h:
            center = 0.5 * (low + high)
            low = center - 0.5 * min_h
            high = center + 0.5 * min_h
        out.append((float(y), low, high, max(min_w, float(w))))
    return out


def superellipse_profile(
    width: float,
    height: float,
    exponent: float = 2.6,
    *,
    segments: int = 48,
) -> List[Vec2]:
    """
    Return a CCW superellipse outline centered at the origin.

    Equation: |x/a|^n + |y/b|^n = 1
    - n=2.0 gives an ellipse
    - larger n approaches a rounded rectangle
    """
    width = float(width)
    height = float(height)
    exponent = float(exponent)
    segments = max(12, int(segments))

    if width <= 0 or height <= 0:
        raise ValueError("width/height must be positive")
    if exponent <= 0:
        raise ValueError("exponent must be positive")

    a = width * 0.5
    b = height * 0.5
    power = 2.0 / exponent

    pts: List[Vec2] = []
    for i in range(segments):
        t = 2.0 * pi * i / segments
        ct = cos(t)
        st = sin(t)
        x = a * (abs(ct) ** power)
        y = b * (abs(st) ** power)
        if ct < 0:
            x = -x
        if st < 0:
            y = -y
        pts.append((x, y))
    return pts


def rounded_rect_profile(
    width: float,
    height: float,
    radius: float,
    *,
    corner_segments: int = 6,
) -> List[Vec2]:
    """
    Return a CCW 2D rounded-rectangle outline centered at the origin.

    The profile is suitable for :class:`ExtrudeGeometry` or as the base shape
    for constructing :class:`LoftGeometry` profiles.
    """
    width = float(width)
    height = float(height)
    radius = float(radius)
    if width <= 0 or height <= 0:
        raise ValueError("width/height must be positive")
    corner_segments = max(1, int(corner_segments))
    max_r = 0.5 * min(width, height)
    if radius < 0 or radius > max_r:
        raise ValueError(f"radius must be within [0, {max_r}]")

    if radius <= 1e-12:
        hw = width * 0.5
        hh = height * 0.5
        return [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]

    hw = width * 0.5
    hh = height * 0.5
    r = radius

    def arc(cx: float, cy: float, a0: float, a1: float) -> List[Vec2]:
        pts: List[Vec2] = []
        for i in range(corner_segments + 1):
            t = i / corner_segments
            a = a0 + (a1 - a0) * t
            pts.append((cx + r * cos(a), cy + r * sin(a)))
        return pts

    # Start on +X edge (bottom-right corner) and go CCW.
    pts: List[Vec2] = []
    pts.extend(arc(hw - r, -hh + r, -pi / 2.0, 0.0))  # bottom-right
    pts.extend(arc(hw - r, hh - r, 0.0, pi / 2.0)[1:])  # top-right
    pts.extend(arc(-hw + r, hh - r, pi / 2.0, pi)[1:])  # top-left
    pts.extend(arc(-hw + r, -hh + r, pi, 3.0 * pi / 2.0)[1:])  # bottom-left
    return pts


def _points_match_2d(a: Vec2, b: Vec2, *, tol: float = 1e-9) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _points_match_3d(a: Vec3, b: Vec3, *, tol: float = 1e-9) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol


def _polygon_area(points: List[Vec2]) -> float:
    area = 0.0
    count = len(points)
    for i in range(count):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % count]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def _ensure_ccw(points: List[Vec2]) -> List[Vec2]:
    area = _polygon_area(points)
    if abs(area) <= 1e-9:
        raise ValueError("Profile area must be non-zero")
    if area < 0:
        return list(reversed(points))
    return points


def _profile_points_2d(profile: Iterable[Tuple[float, float]]) -> List[Vec2]:
    points = [(float(x), float(y)) for (x, y) in profile]
    cleaned: List[Vec2] = []
    for pt in points:
        if not cleaned or not _points_match_2d(cleaned[-1], pt):
            cleaned.append(pt)
    if len(cleaned) >= 2 and _points_match_2d(cleaned[0], cleaned[-1]):
        cleaned = cleaned[:-1]
    if len(cleaned) < 3:
        raise ValueError("Profile must have at least 3 unique points")
    return cleaned


def _polyline_points_2d(profile: Iterable[Tuple[float, float]]) -> List[Vec2]:
    points = [(float(x), float(y)) for (x, y) in profile]
    cleaned: List[Vec2] = []
    for pt in points:
        if not cleaned or not _points_match_2d(cleaned[-1], pt):
            cleaned.append(pt)
    if len(cleaned) < 2:
        raise ValueError("Profile must have at least 2 unique points")
    return cleaned


def _lathe_cap_connector(
    start: Vec2,
    end: Vec2,
    *,
    start_tangent: Vec2,
    end_tangent: Vec2,
    mode: LatheCapMode,
    samples: int,
) -> List[Vec2]:
    if _points_match_2d(start, end):
        return [start]
    if mode == "flat":
        return [start, end]
    if mode != "round":
        raise ValueError("Lathe cap mode must be 'flat' or 'round'")

    chord_dx = end[0] - start[0]
    chord_dz = end[1] - start[1]
    chord = sqrt(chord_dx * chord_dx + chord_dz * chord_dz)
    if chord <= _EPS:
        return [start]

    start_len = sqrt(start_tangent[0] * start_tangent[0] + start_tangent[1] * start_tangent[1])
    end_len = sqrt(end_tangent[0] * end_tangent[0] + end_tangent[1] * end_tangent[1])
    if start_len <= _EPS or end_len <= _EPS:
        return [start, end]

    handle = min(chord * 0.75, start_len * 0.5, end_len * 0.5)
    if handle <= _EPS:
        return [start, end]

    p1 = (
        start[0] + start_tangent[0] * (handle / start_len),
        start[1] + start_tangent[1] * (handle / start_len),
    )
    p2 = (
        end[0] - end_tangent[0] * (handle / end_len),
        end[1] - end_tangent[1] * (handle / end_len),
    )
    return sample_cubic_bezier_spline_2d(
        [start, p1, p2, end],
        samples_per_segment=max(3, int(samples)),
    )


def _lathe_shell_profile(
    outer_profile: Iterable[Tuple[float, float]],
    inner_profile: Iterable[Tuple[float, float]],
    *,
    start_cap: LatheCapMode,
    end_cap: LatheCapMode,
    lip_samples: int,
) -> List[Vec2]:
    outer = _polyline_points_2d(outer_profile)
    inner = _polyline_points_2d(inner_profile)

    same_alignment = _tuple_distance(outer[0], inner[0]) + _tuple_distance(outer[-1], inner[-1])
    flipped_alignment = _tuple_distance(outer[0], inner[-1]) + _tuple_distance(outer[-1], inner[0])
    if flipped_alignment < same_alignment:
        inner = list(reversed(inner))

    end_connector = _lathe_cap_connector(
        outer[-1],
        inner[-1],
        start_tangent=(outer[-1][0] - outer[-2][0], outer[-1][1] - outer[-2][1]),
        end_tangent=(inner[-2][0] - inner[-1][0], inner[-2][1] - inner[-1][1]),
        mode=end_cap,
        samples=lip_samples,
    )
    start_connector = _lathe_cap_connector(
        inner[0],
        outer[0],
        start_tangent=(inner[0][0] - inner[1][0], inner[0][1] - inner[1][1]),
        end_tangent=(outer[1][0] - outer[0][0], outer[1][1] - outer[0][1]),
        mode=start_cap,
        samples=lip_samples,
    )

    profile = list(outer)
    profile.extend(end_connector[1:])
    profile.extend(reversed(inner[:-1]))
    profile.extend(start_connector[1:])
    return profile


def _profile_points_3d(profile: Iterable[Tuple[float, float, float]]) -> List[Vec3]:
    points = [(float(x), float(y), float(z)) for (x, y, z) in profile]
    cleaned: List[Vec3] = []
    for pt in points:
        if not cleaned or not _points_match_3d(cleaned[-1], pt):
            cleaned.append(pt)
    if len(cleaned) >= 2 and _points_match_3d(cleaned[0], cleaned[-1]):
        cleaned = cleaned[:-1]
    if len(cleaned) < 2:
        raise ValueError("Profile must have at least 2 unique points")
    return cleaned


def _cross_z(a: Vec2, b: Vec2, c: Vec2) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_in_triangle(p: Vec2, a: Vec2, b: Vec2, c: Vec2) -> bool:
    eps = 1e-9
    c1 = _cross_z(a, b, p)
    c2 = _cross_z(b, c, p)
    c3 = _cross_z(c, a, p)
    return (c1 > eps and c2 > eps and c3 > eps) or (c1 < -eps and c2 < -eps and c3 < -eps)


def _manifold_triangulate_polygons(polygons: Sequence[List[Vec2]]) -> Optional[List[Face]]:
    if not polygons:
        return []
    try:
        triangles = _m3d.triangulate(polygons, epsilon=float(_OBJ_QUANT_STEP))
    except Exception:
        return None
    return [
        (int(tri[0]), int(tri[1]), int(tri[2])) for tri in np.asarray(triangles, dtype=np.int64)
    ]


def _triangulate_polygon_earclip(points: List[Vec2]) -> List[Face]:
    if len(points) < 3:
        return []

    indices = list(range(len(points)))
    triangles: List[Face] = []
    guard = 0
    max_guard = len(points) * len(points)

    while len(indices) > 3:
        ear_found = False
        for i in range(len(indices)):
            i_prev = indices[i - 1]
            i_curr = indices[i]
            i_next = indices[(i + 1) % len(indices)]

            if _cross_z(points[i_prev], points[i_curr], points[i_next]) <= 0:
                continue

            ear = True
            for j in indices:
                if j in (i_prev, i_curr, i_next):
                    continue
                if _point_in_triangle(points[j], points[i_prev], points[i_curr], points[i_next]):
                    ear = False
                    break

            if ear:
                triangles.append((i_prev, i_curr, i_next))
                del indices[i]
                ear_found = True
                break

        guard += 1
        if not ear_found or guard > max_guard:
            raise ValueError("Failed to triangulate profile; ensure it is simple")

    triangles.append((indices[0], indices[1], indices[2]))
    return triangles


def _triangulate_polygon(points: List[Vec2]) -> List[Face]:
    if len(points) < 3:
        return []

    triangles = _manifold_triangulate_polygons([points])
    if triangles is not None:
        return triangles
    return _triangulate_polygon_earclip(points)


def _point_on_segment(p: Vec2, a: Vec2, b: Vec2, *, tol: float = 1e-9) -> bool:
    px, py = p
    ax, ay = a
    bx, by = b
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > tol:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    if dot < -tol:
        return False
    sq_len = (bx - ax) * (bx - ax) + (by - ay) * (by - ay)
    if dot - sq_len > tol:
        return False
    return True


def _segments_intersect(a: Vec2, b: Vec2, c: Vec2, d: Vec2, *, tol: float = 1e-9) -> bool:
    def orient(p: Vec2, q: Vec2, r: Vec2) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)

    if (o1 > tol and o2 < -tol or o1 < -tol and o2 > tol) and (
        o3 > tol and o4 < -tol or o3 < -tol and o4 > tol
    ):
        return True

    if abs(o1) <= tol and _point_on_segment(c, a, b, tol=tol):
        return True
    if abs(o2) <= tol and _point_on_segment(d, a, b, tol=tol):
        return True
    if abs(o3) <= tol and _point_on_segment(a, c, d, tol=tol):
        return True
    if abs(o4) <= tol and _point_on_segment(b, c, d, tol=tol):
        return True
    return False


def _point_in_polygon(point: Vec2, polygon: List[Vec2]) -> bool:
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        if _point_on_segment(point, a, b):
            return True
        yi = a[1]
        yj = b[1]
        intersects = (yi > y) != (yj > y)
        if not intersects:
            continue
        x_on_edge = a[0] + (y - yi) * (b[0] - a[0]) / (yj - yi)
        if x_on_edge >= x:
            inside = not inside
    return inside


def _polygon_centroid(points: List[Vec2]) -> Vec2:
    sx = 0.0
    sy = 0.0
    n = max(1, len(points))
    for x, y in points:
        sx += x
        sy += y
    return (sx / float(n), sy / float(n))


def _reduce_redundant_vertices(points: List[Vec2], *, tol: float = 1e-9) -> List[Vec2]:
    out: List[Vec2] = []
    for pt in points:
        if not out or not _points_match_2d(out[-1], pt, tol=tol):
            out.append(pt)
    if len(out) >= 2 and _points_match_2d(out[0], out[-1], tol=tol):
        out.pop()
    if len(out) < 4:
        return out

    changed = True
    while changed and len(out) >= 4:
        changed = False
        keep: List[Vec2] = []
        n = len(out)
        for i in range(n):
            prev_pt = out[(i - 1) % n]
            cur_pt = out[i]
            next_pt = out[(i + 1) % n]
            if abs(_cross_z(prev_pt, cur_pt, next_pt)) <= tol and _point_on_segment(
                cur_pt, prev_pt, next_pt, tol=tol
            ):
                changed = True
                continue
            keep.append(cur_pt)
        out = keep
    return out


def _bridge_hole_into_outer(
    outer_ring: List[Vec2],
    hole_ring_cw: List[Vec2],
    *,
    all_holes_ccw: List[List[Vec2]],
) -> List[Vec2]:
    if len(outer_ring) < 3 or len(hole_ring_cw) < 3:
        raise ValueError("Cannot bridge degenerate polygon/hole")

    hi = max(range(len(hole_ring_cw)), key=lambda i: (hole_ring_cw[i][0], -hole_ring_cw[i][1]))
    hp = hole_ring_cw[hi]

    candidate_outer = sorted(
        range(len(outer_ring)),
        key=lambda i: (outer_ring[i][0] - hp[0]) ** 2 + (outer_ring[i][1] - hp[1]) ** 2,
    )

    def bridge_visible(oi: int) -> bool:
        op = outer_ring[oi]
        for i in range(len(outer_ring)):
            a = outer_ring[i]
            b = outer_ring[(i + 1) % len(outer_ring)]
            if _points_match_2d(a, op) or _points_match_2d(b, op):
                continue
            if _segments_intersect(op, hp, a, b):
                return False

        for i in range(len(hole_ring_cw)):
            a = hole_ring_cw[i]
            b = hole_ring_cw[(i + 1) % len(hole_ring_cw)]
            if _points_match_2d(a, hp) or _points_match_2d(b, hp):
                continue
            if _segments_intersect(op, hp, a, b):
                return False

        for h in all_holes_ccw:
            for i in range(len(h)):
                a = h[i]
                b = h[(i + 1) % len(h)]
                if _points_match_2d(a, hp) or _points_match_2d(b, hp):
                    continue
                if _segments_intersect(op, hp, a, b):
                    return False

        for t in (0.2, 0.5, 0.8):
            sample = (op[0] + (hp[0] - op[0]) * t, op[1] + (hp[1] - op[1]) * t)
            if not _point_in_polygon(sample, outer_ring):
                return False
            for h in all_holes_ccw:
                if _point_in_polygon(sample, h):
                    return False
        return True

    oi: Optional[int] = None
    for idx in candidate_outer:
        if bridge_visible(idx):
            oi = idx
            break
    if oi is None:
        raise ValueError("Failed to bridge polygon hole; try simpler/non-overlapping profiles")

    hole_path = hole_ring_cw[hi:] + hole_ring_cw[:hi]
    op = outer_ring[oi]
    on = outer_ring[(oi + 1) % len(outer_ring)]
    edge_dx = on[0] - op[0]
    edge_dy = on[1] - op[1]
    edge_len = (edge_dx * edge_dx + edge_dy * edge_dy) ** 0.5
    if edge_len <= 1e-12:
        eps_dir = (1.0, 0.0)
    else:
        eps_dir = (edge_dx / edge_len, edge_dy / edge_len)

    hprev = hole_ring_cw[(hi - 1) % len(hole_ring_cw)]
    hole_dx = hprev[0] - hp[0]
    hole_dy = hprev[1] - hp[1]
    hole_len = (hole_dx * hole_dx + hole_dy * hole_dy) ** 0.5
    if hole_len <= 1e-12:
        hole_eps_dir = (1.0, 0.0)
    else:
        hole_eps_dir = (hole_dx / hole_len, hole_dy / hole_len)

    # Duplicate both bridge endpoints with sub-quantization offsets. This keeps
    # the stitched polygon triangulable while collapsing to a watertight seam
    # after OBJ coordinate quantization.
    hp2 = (hp[0] + hole_eps_dir[0] * _BRIDGE_EPSILON, hp[1] + hole_eps_dir[1] * _BRIDGE_EPSILON)
    op2 = (op[0] + eps_dir[0] * _BRIDGE_EPSILON, op[1] + eps_dir[1] * _BRIDGE_EPSILON)

    merged = list(outer_ring[: oi + 1]) + list(hole_path) + [hp2, op2] + list(outer_ring[oi + 1 :])
    return _reduce_redundant_vertices(merged)


def _triangulate_polygon_with_holes(
    outer_profile: List[Vec2],
    hole_profiles: List[List[Vec2]],
) -> Tuple[List[Vec2], List[Face]]:
    outer = _ensure_ccw(_profile_points_2d(outer_profile))
    holes_ccw = [_ensure_ccw(_profile_points_2d(h)) for h in hole_profiles]

    if not holes_ccw:
        return outer, _triangulate_polygon(outer)

    for h in holes_ccw:
        c = _polygon_centroid(h)
        if not _point_in_polygon(c, outer):
            raise ValueError("Hole profile must lie inside outer profile")

    holes_cw = [list(reversed(h)) for h in holes_ccw]
    flat_ring = list(outer)
    for h in holes_cw:
        flat_ring.extend(h)

    triangles = _manifold_triangulate_polygons([outer] + holes_cw)
    if triangles is not None:
        return flat_ring, triangles

    holes_cw.sort(key=lambda h: max(pt[0] for pt in h), reverse=True)

    stitched = list(outer)
    for hole_cw in holes_cw:
        stitched = _bridge_hole_into_outer(stitched, hole_cw, all_holes_ccw=holes_ccw)

    stitched = _reduce_redundant_vertices(stitched)
    if _polygon_area(stitched) < 0:
        stitched = list(reversed(stitched))
    return stitched, _triangulate_polygon(stitched)


@dataclass
class MeshGeometry:
    vertices: List[Vec3] = field(default_factory=list)
    faces: List[Face] = field(default_factory=list)

    def copy(self) -> "MeshGeometry":
        copied = MeshGeometry(
            vertices=[tuple(vertex) for vertex in self.vertices],
            faces=[tuple(face) for face in self.faces],
        )
        _copy_primitive_provenance(self, copied)
        _copy_manifold_provenance(self, copied)
        return copied

    def clone(self) -> "MeshGeometry":
        return self.copy()

    def add_vertex(self, x: float, y: float, z: float) -> int:
        _clear_manifold_provenance(self)
        self.vertices.append((float(x), float(y), float(z)))
        return len(self.vertices) - 1

    def add_face(self, a: int, b: int, c: int) -> None:
        _clear_manifold_provenance(self)
        self.faces.append((int(a), int(b), int(c)))

    def merge(self, other: "MeshGeometry") -> "MeshGeometry":
        offset = len(self.vertices)
        self.vertices.extend(other.vertices)
        self.faces.extend((a + offset, b + offset, c + offset) for (a, b, c) in other.faces)
        _clear_primitive_provenance(self)
        _clear_manifold_provenance(self)
        return self

    def translate(self, dx: float, dy: float, dz: float) -> "MeshGeometry":
        self.vertices = [(x + dx, y + dy, z + dz) for (x, y, z) in self.vertices]
        transform: Mat4 = (
            (1.0, 0.0, 0.0, float(dx)),
            (0.0, 1.0, 0.0, float(dy)),
            (0.0, 0.0, 1.0, float(dz)),
            (0.0, 0.0, 0.0, 1.0),
        )
        _prepend_primitive_transform(self, transform)
        _clear_manifold_provenance(self)
        return self

    def scale(
        self, sx: float, sy: Optional[float] = None, sz: Optional[float] = None
    ) -> "MeshGeometry":
        if sy is None:
            sy = sx
        if sz is None:
            sz = sx
        self.vertices = [(x * sx, y * sy, z * sz) for (x, y, z) in self.vertices]
        _prepend_primitive_transform(
            self,
            (
                (float(sx), 0.0, 0.0, 0.0),
                (0.0, float(sy), 0.0, 0.0),
                (0.0, 0.0, float(sz), 0.0),
                (0.0, 0.0, 0.0, 1.0),
            ),
        )
        _clear_manifold_provenance(self)
        return self

    def rotate(
        self,
        axis: Sequence[float],
        angle: float,
        *,
        origin: Sequence[float] = (0.0, 0.0, 0.0),
    ) -> "MeshGeometry":
        kx, ky, kz = _v_normalize((float(axis[0]), float(axis[1]), float(axis[2])))
        ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
        c = cos(angle)
        s = sin(angle)
        t = 1.0 - c

        r00 = t * kx * kx + c
        r01 = t * kx * ky - s * kz
        r02 = t * kx * kz + s * ky
        r10 = t * ky * kx + s * kz
        r11 = t * ky * ky + c
        r12 = t * ky * kz - s * kx
        r20 = t * kz * kx - s * ky
        r21 = t * kz * ky + s * kx
        r22 = t * kz * kz + c

        tx = ox - (r00 * ox + r01 * oy + r02 * oz)
        ty = oy - (r10 * ox + r11 * oy + r12 * oz)
        tz = oz - (r20 * ox + r21 * oy + r22 * oz)
        transform: Mat4 = (
            (float(r00), float(r01), float(r02), float(tx)),
            (float(r10), float(r11), float(r12), float(ty)),
            (float(r20), float(r21), float(r22), float(tz)),
            (0.0, 0.0, 0.0, 1.0),
        )

        self.vertices = [
            (
                r00 * x + r01 * y + r02 * z + tx,
                r10 * x + r11 * y + r12 * z + ty,
                r20 * x + r21 * y + r22 * z + tz,
            )
            for (x, y, z) in self.vertices
        ]
        _prepend_primitive_transform(self, transform)
        _clear_manifold_provenance(self)
        return self

    def rotate_x(self, angle: float) -> "MeshGeometry":
        return self.rotate((1.0, 0.0, 0.0), angle)

    def rotate_y(self, angle: float) -> "MeshGeometry":
        return self.rotate((0.0, 1.0, 0.0), angle)

    def rotate_z(self, angle: float) -> "MeshGeometry":
        return self.rotate((0.0, 0.0, 1.0), angle)

    def to_obj(self) -> str:
        lines = ["o mesh"]
        for x, y, z in self.vertices:
            lines.append(
                f"v {x:.{_OBJ_COORD_DECIMALS}f} {y:.{_OBJ_COORD_DECIMALS}f} {z:.{_OBJ_COORD_DECIMALS}f}"
            )
        for a, b, c in self.faces:
            lines.append(f"f {a + 1} {b + 1} {c + 1}")
        lines.append("")
        return "\n".join(lines)

    def save_obj(self, path: Union[str, Path]) -> None:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(self.to_obj())


def _coerce_positive_radii3(
    value: Union[float, Sequence[float]],
    *,
    name: str,
) -> Vec3:
    if isinstance(value, (int, float)):
        radius = float(value)
        if radius <= 0.0:
            raise ValueError(f"{name} must be positive")
        return (radius, radius, radius)
    if len(value) != 3:
        raise ValueError(f"{name} must be a positive float or a 3-sequence")
    rx = float(value[0])
    ry = float(value[1])
    rz = float(value[2])
    if rx <= 0.0 or ry <= 0.0 or rz <= 0.0:
        raise ValueError(f"{name} values must be positive")
    return (rx, ry, rz)


class BoxGeometry(MeshGeometry):
    def __init__(self, size: Sequence[float]):
        super().__init__()
        x, y, z = (float(size[0]), float(size[1]), float(size[2]))
        primitive = Box((x, y, z))
        _set_primitive_provenance(self, primitive)
        hx, hy, hz = x / 2.0, y / 2.0, z / 2.0
        verts = [
            (-hx, -hy, -hz),
            (hx, -hy, -hz),
            (hx, hy, -hz),
            (-hx, hy, -hz),
            (-hx, -hy, hz),
            (hx, -hy, hz),
            (hx, hy, hz),
            (-hx, hy, hz),
        ]
        self.vertices = verts
        faces = [
            (0, 1, 2),
            (0, 2, 3),
            (4, 6, 5),
            (4, 7, 6),
            (0, 4, 5),
            (0, 5, 1),
            (1, 5, 6),
            (1, 6, 2),
            (2, 6, 7),
            (2, 7, 3),
            (3, 7, 4),
            (3, 4, 0),
        ]
        self.faces = faces


class CylinderGeometry(MeshGeometry):
    def __init__(
        self,
        radius: float,
        height: float,
        *,
        radial_segments: int = 24,
        closed: bool = True,
    ):
        super().__init__()
        radius = float(radius)
        height = float(height)
        radial_segments = max(3, int(radial_segments))
        primitive = Cylinder(radius=radius, length=height)
        _set_primitive_provenance(self, primitive)
        half = height / 2.0

        top_indices = []
        bottom_indices = []
        for i in range(radial_segments):
            theta = 2 * pi * i / radial_segments
            x = radius * cos(theta)
            y = radius * sin(theta)
            top_indices.append(self.add_vertex(x, y, half))
            bottom_indices.append(self.add_vertex(x, y, -half))

        for i in range(radial_segments):
            i2 = (i + 1) % radial_segments
            a = top_indices[i]
            b = bottom_indices[i]
            c = bottom_indices[i2]
            d = top_indices[i2]
            self.add_face(a, b, c)
            self.add_face(a, c, d)

        if closed:
            top_center = self.add_vertex(0.0, 0.0, half)
            bottom_center = self.add_vertex(0.0, 0.0, -half)
            for i in range(radial_segments):
                i2 = (i + 1) % radial_segments
                self.add_face(top_center, top_indices[i], top_indices[i2])
                self.add_face(bottom_center, bottom_indices[i2], bottom_indices[i])


class ConeGeometry(MeshGeometry):
    def __init__(
        self,
        radius: float,
        height: float,
        *,
        radial_segments: int = 24,
        closed: bool = True,
    ):
        super().__init__()
        radius = float(radius)
        height = float(height)
        radial_segments = max(3, int(radial_segments))
        half = height / 2.0
        apex = self.add_vertex(0.0, 0.0, half)
        ring_indices = []
        for i in range(radial_segments):
            theta = 2 * pi * i / radial_segments
            x = radius * cos(theta)
            y = radius * sin(theta)
            ring_indices.append(self.add_vertex(x, y, -half))

        for i in range(radial_segments):
            i2 = (i + 1) % radial_segments
            self.add_face(apex, ring_indices[i], ring_indices[i2])

        if closed:
            base_center = self.add_vertex(0.0, 0.0, -half)
            for i in range(radial_segments):
                i2 = (i + 1) % radial_segments
                self.add_face(base_center, ring_indices[i2], ring_indices[i])


class SphereGeometry(MeshGeometry):
    def __init__(
        self,
        radius: float,
        *,
        width_segments: int = 24,
        height_segments: int = 16,
    ):
        super().__init__()
        radius = float(radius)
        width_segments = max(3, int(width_segments))
        height_segments = max(2, int(height_segments))
        primitive = Sphere(radius=radius)
        _set_primitive_provenance(self, primitive)

        for iy in range(height_segments + 1):
            v = iy / height_segments
            phi = pi * v
            for ix in range(width_segments + 1):
                u = ix / width_segments
                theta = 2 * pi * u
                x = radius * sin(phi) * cos(theta)
                y = radius * sin(phi) * sin(theta)
                z = radius * cos(phi)
                self.add_vertex(x, y, z)

        verts_per_row = width_segments + 1
        for iy in range(height_segments):
            for ix in range(width_segments):
                a = iy * verts_per_row + ix
                b = a + verts_per_row
                c = b + 1
                d = a + 1
                if iy != 0:
                    self.add_face(a, b, d)
                if iy != height_segments - 1:
                    self.add_face(b, c, d)


class DomeGeometry(MeshGeometry):
    def __init__(
        self,
        radius: Union[float, Sequence[float]],
        *,
        radial_segments: int = 24,
        height_segments: int = 12,
        closed: bool = True,
    ):
        super().__init__()
        rx, ry, rz = _coerce_positive_radii3(radius, name="radius")
        radial_segments = max(3, int(radial_segments))
        height_segments = max(1, int(height_segments))

        for iy in range(height_segments + 1):
            v = iy / height_segments
            phi = 0.5 * pi * v
            sin_phi = sin(phi)
            cos_phi = cos(phi)
            z = rz * cos_phi
            for ix in range(radial_segments + 1):
                u = ix / radial_segments
                theta = 2.0 * pi * u
                x = rx * sin_phi * cos(theta)
                y = ry * sin_phi * sin(theta)
                self.add_vertex(x, y, z)

        verts_per_row = radial_segments + 1
        for iy in range(height_segments):
            for ix in range(radial_segments):
                a = iy * verts_per_row + ix
                b = a + verts_per_row
                c = b + 1
                d = a + 1
                if iy != 0:
                    self.add_face(a, b, d)
                self.add_face(b, c, d)

        if closed:
            base_center = self.add_vertex(0.0, 0.0, 0.0)
            base_offset = height_segments * verts_per_row
            for ix in range(radial_segments):
                self.add_face(base_center, base_offset + ix, base_offset + ix + 1)


class CapsuleGeometry(MeshGeometry):
    def __init__(
        self,
        radius: float,
        length: float,
        *,
        radial_segments: int = 24,
        height_segments: int = 8,
    ):
        super().__init__()
        radius = float(radius)
        length = float(length)
        radial_segments = max(3, int(radial_segments))
        height_segments = max(2, int(height_segments))

        if radius <= 0.0:
            raise ValueError("radius must be positive")
        if length < 0.0:
            raise ValueError("length must be non-negative")

        if length <= _EPS:
            self.merge(
                SphereGeometry(
                    radius,
                    width_segments=radial_segments,
                    height_segments=max(4, 2 * height_segments),
                )
            )
            return

        half = length * 0.5
        rows: List[Tuple[float, float]] = []

        for iy in range(height_segments + 1):
            v = iy / height_segments
            phi = 0.5 * pi * v
            rows.append((radius * sin(phi), half + radius * cos(phi)))

        for iy in range(height_segments + 1):
            v = iy / height_segments
            phi = 0.5 * pi + 0.5 * pi * v
            rows.append((radius * sin(phi), -half + radius * cos(phi)))

        for ring_radius, z in rows:
            for ix in range(radial_segments + 1):
                u = ix / radial_segments
                theta = 2.0 * pi * u
                x = ring_radius * cos(theta)
                y = ring_radius * sin(theta)
                self.add_vertex(x, y, z)

        verts_per_row = radial_segments + 1
        segment_count = len(rows) - 1
        for iy in range(segment_count):
            for ix in range(radial_segments):
                a = iy * verts_per_row + ix
                b = a + verts_per_row
                c = b + 1
                d = a + 1
                if iy != 0:
                    self.add_face(a, b, d)
                if iy != segment_count - 1:
                    self.add_face(b, c, d)


class TorusGeometry(MeshGeometry):
    def __init__(
        self,
        radius: float,
        tube: float,
        *,
        radial_segments: int = 16,
        tubular_segments: int = 32,
    ):
        super().__init__()
        radius = float(radius)
        tube = float(tube)
        radial_segments = max(3, int(radial_segments))
        tubular_segments = max(3, int(tubular_segments))

        for j in range(radial_segments + 1):
            v = 2 * pi * j / radial_segments
            cv = cos(v)
            sv = sin(v)
            for i in range(tubular_segments + 1):
                u = 2 * pi * i / tubular_segments
                cu = cos(u)
                su = sin(u)
                x = (radius + tube * cv) * cu
                y = (radius + tube * cv) * su
                z = tube * sv
                self.add_vertex(x, y, z)

        verts_per_row = tubular_segments + 1
        for j in range(radial_segments):
            for i in range(tubular_segments):
                a = j * verts_per_row + i
                b = a + verts_per_row
                c = b + 1
                d = a + 1
                self.add_face(a, b, d)
                self.add_face(b, c, d)


class LatheGeometry(MeshGeometry):
    @classmethod
    def from_shell_profiles(
        cls,
        outer_profile: Iterable[Tuple[float, float]],
        inner_profile: Iterable[Tuple[float, float]],
        *,
        segments: int = 32,
        start_cap: LatheCapMode = "flat",
        end_cap: LatheCapMode = "flat",
        lip_samples: int = 6,
    ) -> "LatheGeometry":
        profile = _lathe_shell_profile(
            outer_profile,
            inner_profile,
            start_cap=start_cap,
            end_cap=end_cap,
            lip_samples=lip_samples,
        )
        return cls(profile, segments=segments, closed=True)

    def __init__(
        self,
        profile: Iterable[Tuple[float, float]],
        *,
        segments: int = 32,
        closed: bool = True,
    ):
        super().__init__()
        segments = max(3, int(segments))
        points = _profile_points_2d(profile) if closed else _polyline_points_2d(profile)
        if closed:
            points = _ensure_ccw(points)

        normalized_points: List[Vec2] = []
        for r, z in points:
            if r < -_EPS:
                raise ValueError("Lathe profile radii must be non-negative")
            normalized_points.append((0.0 if abs(r) <= _EPS else float(r), float(z)))
        points = normalized_points

        ring_indices: List[List[int]] = []
        for r, z in points:
            if r <= _EPS:
                axis_vertex = self.add_vertex(0.0, 0.0, z)
                ring_indices.append([axis_vertex] * segments)
                continue

            ring: List[int] = []
            for i in range(segments):
                theta = 2 * pi * i / segments
                ring.append(self.add_vertex(r * cos(theta), r * sin(theta), z))
            ring_indices.append(ring)

        def add_face_if_non_degenerate(a: int, b: int, c: int) -> None:
            if a == b or b == c or c == a:
                return
            self.add_face(a, b, c)

        edge_count = len(points) if closed else len(points) - 1
        for j in range(edge_count):
            j2 = (j + 1) % len(points)
            r0 = points[j][0]
            r1 = points[j2][0]
            if r0 <= _EPS and r1 <= _EPS:
                continue

            ring0 = ring_indices[j]
            ring1 = ring_indices[j2]
            for i in range(segments):
                i2 = (i + 1) % segments
                a = ring0[i]
                b = ring0[i2]
                c = ring1[i2]
                d = ring1[i]
                add_face_if_non_degenerate(a, b, d)
                add_face_if_non_degenerate(b, c, d)


class LoftGeometry(MeshGeometry):
    def __init__(
        self,
        profiles: Iterable[Iterable[Tuple[float, float, float]]],
        *,
        cap: bool = True,
        closed: bool = True,
    ):
        super().__init__()
        profile_list = [_profile_points_3d(profile) for profile in profiles]
        if len(profile_list) < 2:
            raise ValueError("Loft requires at least two profiles")

        ring_count = len(profile_list[0])
        if closed and ring_count < 3:
            raise ValueError("Closed loft profiles must have at least 3 points")

        for profile in profile_list:
            if len(profile) != ring_count:
                raise ValueError("Loft profiles must have the same point count")

        profile_xy = [(x, y) for (x, y, _z) in profile_list[0]]
        base_area = _polygon_area(profile_xy)
        if abs(base_area) <= 1e-9:
            raise ValueError(
                "Loft profile area must be non-zero in XY projection; "
                "profiles should usually be closed XY loops at constant z"
            )

        if base_area < 0:
            profile_list = [list(reversed(profile)) for profile in profile_list]
            base_area = -base_area

        for idx, profile in enumerate(profile_list):
            area = _polygon_area([(x, y) for (x, y, _z) in profile])
            if abs(area) <= 1e-9:
                raise ValueError(
                    "Loft profile area must be non-zero in XY projection; "
                    "profiles should usually be closed XY loops at constant z"
                )
            if area * base_area < 0:
                profile_list[idx] = list(reversed(profile))

        for profile in profile_list:
            for x, y, z in profile:
                self.add_vertex(x, y, z)

        segment_count = ring_count if closed else ring_count - 1
        for i in range(len(profile_list) - 1):
            offset0 = i * ring_count
            offset1 = (i + 1) * ring_count
            for j in range(segment_count):
                j2 = (j + 1) % ring_count
                a = offset0 + j
                b = offset0 + j2
                c = offset1 + j2
                d = offset1 + j
                self.add_face(a, b, c)
                self.add_face(a, c, d)

        if cap and closed:
            first_profile = profile_list[0]
            last_profile = profile_list[-1]
            first_xy = [(x, y) for (x, y, _z) in first_profile]
            last_xy = [(x, y) for (x, y, _z) in last_profile]

            z_spread = max(z for (_x, _y, z) in first_profile) - min(
                z for (_x, _y, z) in first_profile
            )
            if z_spread > 1e-6:
                raise ValueError("Loft caps require planar profiles")

            z_spread = max(z for (_x, _y, z) in last_profile) - min(
                z for (_x, _y, z) in last_profile
            )
            if z_spread > 1e-6:
                raise ValueError("Loft caps require planar profiles")

            triangles = _triangulate_polygon(first_xy)
            for a, b, c in triangles:
                self.add_face(c, b, a)

            offset_last = (len(profile_list) - 1) * ring_count
            triangles = _triangulate_polygon(last_xy)
            for a, b, c in triangles:
                self.add_face(offset_last + a, offset_last + b, offset_last + c)


class ExtrudeGeometry(MeshGeometry):
    @classmethod
    def centered(
        cls,
        profile: Iterable[Tuple[float, float]],
        height: float,
        *,
        cap: bool = True,
        closed: bool = True,
    ) -> "ExtrudeGeometry":
        return cls(profile, height, cap=cap, center=True, closed=closed)

    @classmethod
    def from_z0(
        cls,
        profile: Iterable[Tuple[float, float]],
        height: float,
        *,
        cap: bool = True,
        closed: bool = True,
    ) -> "ExtrudeGeometry":
        return cls(profile, height, cap=cap, center=False, closed=closed)

    def __init__(
        self,
        profile: Iterable[Tuple[float, float]],
        height: float,
        *,
        cap: bool = True,
        center: bool = True,
        closed: bool = True,
    ):
        super().__init__()
        height = float(height)
        if height <= 0:
            raise ValueError("Extrude height must be positive")

        points = _ensure_ccw(_profile_points_2d(profile))
        if not closed:
            cap = False

        z0 = -height / 2.0 if center else 0.0
        z1 = z0 + height

        profiles = [
            [(x, y, z0) for (x, y) in points],
            [(x, y, z1) for (x, y) in points],
        ]
        self.merge(LoftGeometry(profiles, cap=cap, closed=closed))


class ExtrudeWithHolesGeometry(MeshGeometry):
    """
    Extrude a 2D outer profile with one or more through-holes.

    Notes
    -----
    - This is a lightweight CAD-like helper for panel/filter parts.
    - For capped, closed solids, cap triangulation uses the shared manifold-backed
      polygon triangulation path when available.
    """

    def __init__(
        self,
        outer_profile: Iterable[Tuple[float, float]],
        hole_profiles: Iterable[Iterable[Tuple[float, float]]],
        height: float,
        *,
        cap: bool = True,
        center: bool = True,
        closed: bool = True,
    ):
        super().__init__()
        height = float(height)
        if height <= 0:
            raise ValueError("Extrude height must be positive")

        outer = _ensure_ccw(_profile_points_2d(outer_profile))
        holes = [_ensure_ccw(_profile_points_2d(h)) for h in hole_profiles]
        if not closed:
            cap = False

        for hole in holes:
            c = _polygon_centroid(hole)
            if not _point_in_polygon(c, outer):
                raise ValueError("Hole profile must lie inside outer profile")

        if not holes:
            self.merge(
                ExtrudeGeometry(
                    outer,
                    height,
                    cap=cap,
                    center=center,
                    closed=closed,
                )
            )
            return

        z0 = -height / 2.0 if center else 0.0
        z1 = z0 + height

        # Exterior side walls.
        outer_loft = LoftGeometry(
            [[(x, y, z0) for (x, y) in outer], [(x, y, z1) for (x, y) in outer]],
            cap=False,
            closed=closed,
        )
        outer_offset = len(self.vertices)
        self.merge(outer_loft)
        bottom_cap_indices = [outer_offset + i for i in range(len(outer))]
        top_cap_indices = [outer_offset + len(outer) + i for i in range(len(outer))]

        # Interior side walls for each hole.
        holes_cw: List[List[Vec2]] = []
        for hole in holes:
            hole_cw = list(reversed(hole))
            hole_loft = LoftGeometry(
                [[(x, y, z0) for (x, y) in hole_cw], [(x, y, z1) for (x, y) in hole_cw]],
                cap=False,
                closed=closed,
            )
            hole_offset = len(self.vertices)
            self.merge(hole_loft)
            bottom_cap_indices.extend(hole_offset + i for i in range(len(hole_cw)))
            top_cap_indices.extend(hole_offset + len(hole_cw) + i for i in range(len(hole_cw)))
            holes_cw.append(hole_cw)

        if not (cap and closed):
            return

        cap_ring, cap_triangles = _triangulate_polygon_with_holes(outer, holes)
        expected_cap_ring = list(outer)
        for hole_cw in holes_cw:
            expected_cap_ring.extend(hole_cw)

        reuse_sidewall_rims = len(cap_ring) == len(expected_cap_ring) and all(
            _points_match_2d(actual, expected)
            for actual, expected in zip(cap_ring, expected_cap_ring)
        )
        if reuse_sidewall_rims:
            bottom_idx = bottom_cap_indices
            top_idx = top_cap_indices
        else:
            bottom_idx = [self.add_vertex(x, y, z0) for (x, y) in cap_ring]
            top_idx = [self.add_vertex(x, y, z1) for (x, y) in cap_ring]

        for a, b, c in cap_triangles:
            # Bottom points downward, top points upward.
            self.add_face(bottom_idx[c], bottom_idx[b], bottom_idx[a])
            self.add_face(top_idx[a], top_idx[b], top_idx[c])


def _translated_profile(profile: List[Vec2], dx: float, dy: float) -> List[Vec2]:
    return [(x + dx, y + dy) for (x, y) in profile]


def _mesh_bounds(geometry: "MeshGeometry") -> tuple[Vec3, Vec3]:
    if not geometry.vertices:
        raise ValueError("MeshGeometry has no vertices")
    xs = [vertex[0] for vertex in geometry.vertices]
    ys = [vertex[1] for vertex in geometry.vertices]
    zs = [vertex[2] for vertex in geometry.vertices]
    return (
        (min(xs), min(ys), min(zs)),
        (max(xs), max(ys), max(zs)),
    )


def _normalize_pitch_2d(
    pitch: Union[float, Sequence[float]],
    *,
    name: str = "pitch",
) -> tuple[float, float]:
    if isinstance(pitch, Sequence) and not isinstance(pitch, (str, bytes)):
        values = list(pitch)
        if len(values) != 2:
            raise ValueError(f"{name} must be a positive scalar or a 2-tuple")
        pitch_x = float(values[0])
        pitch_y = float(values[1])
    else:
        pitch_x = float(pitch)
        pitch_y = float(pitch)
    if pitch_x <= 0.0 or pitch_y <= 0.0:
        raise ValueError(f"{name} values must be positive")
    return (pitch_x, pitch_y)


def _centered_axis_positions(limit: float, pitch: float) -> list[float]:
    if limit < -1e-9:
        return []
    if limit <= 1e-9:
        return [0.0]
    count = int((2.0 * limit) / pitch) + 1
    if count <= 0:
        return []
    return [((index - (count - 1) * 0.5) * pitch) for index in range(count)]


def _mesh_geometry_shifted_to_z0(geometry: "MeshGeometry") -> "MeshGeometry":
    shifted = geometry.copy()
    mins, _maxs = _mesh_bounds(shifted)
    shifted.translate(0.0, 0.0, -mins[2])
    return shifted


def _mesh_geometry_shifted_to_axis0(geometry: "MeshGeometry", axis: int) -> "MeshGeometry":
    shifted = geometry.copy()
    mins, _maxs = _mesh_bounds(shifted)
    delta = [0.0, 0.0, 0.0]
    delta[int(axis)] = -mins[int(axis)]
    shifted.translate(delta[0], delta[1], delta[2])
    return shifted


def _adopt_mesh_geometry(target: "MeshGeometry", geometry: "MeshGeometry") -> None:
    target.vertices = [tuple(vertex) for vertex in geometry.vertices]
    target.faces = [tuple(face) for face in geometry.faces]
    _copy_manifold_provenance(geometry, target)


@dataclass(frozen=True)
class KnobSkirt:
    diameter: float
    height: float
    flare: float = 0.0
    chamfer: float = 0.0


@dataclass(frozen=True)
class KnobGrip:
    style: Literal[
        "none",
        "fluted",
        "scalloped",
        "knurled",
        "ribbed",
        "diamond_knurl",
    ] = "none"
    count: Optional[int] = None
    depth: float = 0.0
    width: Optional[float] = None
    helix_angle_deg: float = 0.0


@dataclass(frozen=True)
class KnobIndicator:
    style: Literal["none", "line", "notch", "wedge", "dot"] = "none"
    length: Optional[float] = None
    width: Optional[float] = None
    depth: float = 0.0
    angle_deg: float = 0.0
    mode: Literal["engraved", "raised"] = "engraved"


@dataclass(frozen=True)
class KnobTopFeature:
    style: Literal["none", "flush_disk", "recessed_disk", "top_insert"] = "none"
    diameter: Optional[float] = None
    depth: float = 0.0
    height: float = 0.0


@dataclass(frozen=True)
class KnobBore:
    style: Literal["none", "round", "d_shaft", "double_d", "splined", "hex"] = "round"
    diameter: Optional[float] = None
    flat_depth: Optional[float] = None
    spline_count: Optional[int] = None
    spline_depth: float = 0.0
    through: bool = True


@dataclass(frozen=True)
class KnobRelief:
    style: Literal["side_window", "top_recess", "coin_slot"]
    angle_deg: float = 0.0
    width: Optional[float] = None
    height: Optional[float] = None
    depth: float = 0.0


@dataclass(frozen=True)
class BezelFace:
    style: Literal["flat", "rounded", "chamfered", "radiused_step"] = "flat"
    front_lip: float = 0.0
    chamfer: float = 0.0
    fillet: float = 0.0


@dataclass(frozen=True)
class BezelRecess:
    depth: float
    inset: float
    floor_radius: float = 0.0
    wall_draft_deg: float = 0.0


@dataclass(frozen=True)
class BezelVisor:
    top_extension: float = 0.0
    side_extension: float = 0.0
    thickness: float = 0.0
    draft_deg: float = 0.0


@dataclass(frozen=True)
class BezelFlange:
    width: float = 0.0
    thickness: float = 0.0
    offset: float = 0.0


@dataclass(frozen=True)
class BezelMounts:
    style: Literal["none", "bosses", "tabs", "rear_flange"] = "none"
    hole_count: int = 0
    hole_diameter: Optional[float] = None
    boss_diameter: Optional[float] = None
    setback: float = 0.0


@dataclass(frozen=True)
class BezelCutout:
    edge: Literal["top", "bottom", "left", "right"]
    width: float
    depth: float
    offset: float = 0.0


@dataclass(frozen=True)
class BezelEdgeFeature:
    style: Literal["bead", "step", "notch"] = "bead"
    edge: Literal["top", "bottom", "left", "right"] = "top"
    size: float = 0.0
    offset: float = 0.0
    extent: float = 0.0


@dataclass(frozen=True)
class BoltPattern:
    count: int
    circle_diameter: float
    hole_diameter: float
    countersink: float = 0.0


@dataclass(frozen=True)
class WheelRim:
    outer_radius: Optional[float] = None
    inner_radius: Optional[float] = None
    flange_height: float = 0.0
    flange_thickness: float = 0.0
    bead_seat_depth: float = 0.0


@dataclass(frozen=True)
class WheelHub:
    radius: float
    width: float
    cap_style: Literal["flat", "domed", "protruding", "recessed"] = "flat"
    bolt_pattern: Optional[BoltPattern] = None


@dataclass(frozen=True)
class WheelFace:
    dish_depth: float = 0.0
    front_inset: float = 0.0
    rear_inset: float = 0.0
    window_depth: float = 0.0


@dataclass(frozen=True)
class WheelSpokes:
    style: Literal["none", "disc", "solid_slots", "straight", "split_y", "mesh"] = "none"
    count: Optional[int] = None
    thickness: float = 0.0
    window_radius: float = 0.0
    twist_deg: float = 0.0


@dataclass(frozen=True)
class WheelBore:
    style: Literal["round", "keyed", "hex"] = "round"
    diameter: float = 0.0
    key_width: Optional[float] = None


@dataclass(frozen=True)
class WheelFlange:
    radius: float
    thickness: float
    offset: float = 0.0
    side: Literal["front", "rear", "both"] = "both"
    section: Literal["flat", "round"] = "flat"


@dataclass(frozen=True)
class TireCarcass:
    crown_radius: Optional[float] = None
    belt_width_ratio: float = 0.34
    sidewall_bulge: float = 0.08


@dataclass(frozen=True)
class TireTread:
    style: Literal["none", "circumferential", "block", "rib", "chevron", "lug"] = "none"
    depth: float = 0.0
    pitch: Optional[float] = None
    count: Optional[int] = None
    angle_deg: float = 0.0
    land_ratio: float = 0.5


@dataclass(frozen=True)
class TireGroove:
    center_offset: float = 0.0
    width: float = 0.0
    depth: float = 0.0


@dataclass(frozen=True)
class TireSidewall:
    style: Literal["flat", "bulged", "square", "rounded"] = "rounded"
    bulge: float = 0.08
    inset_ratio: float = 0.18


@dataclass(frozen=True)
class TireShoulder:
    style: Literal["soft", "square"] = "soft"
    radius: float = 0.0
    width: float = 0.0


@dataclass(frozen=True)
class HingeHolePattern:
    style: Literal["none", "round", "countersunk", "slotted"] = "none"
    count: int = 0
    diameter: Optional[float] = None
    slot_size: Optional[tuple[float, float]] = None
    edge_margin: float = 0.0
    pitch: Optional[float] = None


@dataclass(frozen=True)
class HingePinStyle:
    head_style: Literal["plain", "button", "flat", "peened"] = "plain"
    head_height: float = 0.0
    head_diameter: Optional[float] = None
    exposed_end: float = 0.0


@dataclass(frozen=True)
class VentGrilleSlats:
    profile: Literal["flat", "airfoil", "boxed"] = "flat"
    direction: Literal["down", "up"] = "down"
    inset: float = 0.0
    divider_count: int = 0
    divider_width: float = 0.004


@dataclass(frozen=True)
class VentGrilleFrame:
    style: Literal["flush", "beveled", "radiused"] = "flush"
    depth: float = 0.0


@dataclass(frozen=True)
class VentGrilleMounts:
    style: Literal["none", "holes"] = "none"
    inset: float = 0.008
    hole_diameter: Optional[float] = None


@dataclass(frozen=True)
class VentGrilleSleeve:
    style: Literal["none", "short", "full"] = "full"
    depth: Optional[float] = None
    wall: Optional[float] = None


@dataclass(frozen=True)
class FanRotorBlade:
    shape: Literal["straight", "scimitar", "broad", "narrow"] = "straight"
    tip_pitch_deg: Optional[float] = None
    camber: float = 0.0
    tip_clearance: float = 0.0


@dataclass(frozen=True)
class FanRotorHub:
    style: Literal["flat", "domed", "capped", "spinner"] = "domed"
    rear_collar_height: Optional[float] = None
    rear_collar_radius: Optional[float] = None
    bore_diameter: Optional[float] = None


@dataclass(frozen=True)
class FanRotorShroud:
    thickness: float
    depth: Optional[float] = None
    clearance: float = 0.0
    lip_depth: float = 0.0


def _cq_polyline_wire(cq_module, points: Sequence[Vec2], plane: str = "XY"):
    return cq_module.Workplane(plane).polyline(points).close()


def _sample_ellipse_profile(width: float, height: float, *, segments: int = 64) -> list[Vec2]:
    rx = float(width) * 0.5
    ry = float(height) * 0.5
    return [
        (rx * cos(2.0 * pi * index / float(segments)), ry * sin(2.0 * pi * index / float(segments)))
        for index in range(segments)
    ]


def _sample_rect_profile(width: float, height: float) -> list[Vec2]:
    hw = float(width) * 0.5
    hh = float(height) * 0.5
    return [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]


def _shape_profile_points_2d(
    shape: str,
    size: Sequence[float],
    *,
    corner_radius: float = 0.0,
    segments: int = 64,
) -> list[Vec2]:
    width = float(size[0])
    height = float(size[1])
    if width <= 0.0 or height <= 0.0:
        raise ValueError("shape size values must be positive")
    if shape == "rect":
        return _sample_rect_profile(width, height)
    if shape == "rounded_rect":
        return rounded_rect_profile(
            width, height, max(0.0, corner_radius), corner_segments=max(4, segments // 16)
        )
    if shape == "circle":
        diameter = min(width, height)
        return _sample_ellipse_profile(diameter, diameter, segments=segments)
    if shape == "ellipse":
        return _sample_ellipse_profile(width, height, segments=segments)
    if shape == "superellipse":
        return superellipse_profile(width, height, exponent=2.8, segments=segments)
    raise ValueError(f"Unsupported shape {shape!r}")


def _shape_size_from_wall(
    inner_size: Sequence[float],
    wall: Union[float, Sequence[float]],
) -> tuple[float, float]:
    inner_w = float(inner_size[0])
    inner_h = float(inner_size[1])
    if isinstance(wall, (int, float)):
        wall_left = wall_right = wall_bottom = wall_top = float(wall)
    else:
        if len(wall) != 4:
            raise ValueError("wall must be a float or a 4-sequence")
        wall_left, wall_right, wall_bottom, wall_top = (float(value) for value in wall)
    if min(wall_left, wall_right, wall_bottom, wall_top) < 0.0:
        raise ValueError("wall values must be non-negative")
    return (
        inner_w + wall_left + wall_right,
        inner_h + wall_bottom + wall_top,
    )


def _cq_ring_solid(
    cq_module,
    outer_points: Sequence[Vec2],
    inner_points: Sequence[Vec2],
    depth: float,
    *,
    center: bool = True,
):
    shape = _cq_polyline_wire(cq_module, outer_points).extrude(float(depth) * 0.5, both=center)
    inner_cut = _cq_polyline_wire(cq_module, inner_points).extrude(
        float(depth) + max(0.002, float(depth) * 0.5),
        both=center,
    )
    return shape.cut(inner_cut)


def _cq_annulus_x(cq_module, outer_radius: float, inner_radius: float, width: float):
    return (
        cq_module.Workplane("YZ")
        .circle(float(outer_radius))
        .circle(max(float(inner_radius), 1.0e-4))
        .extrude(float(width) * 0.5, both=True)
    )


def _centered_pattern_positions(count: int, spacing: float) -> list[float]:
    if count <= 0:
        return []
    if count == 1:
        return [0.0]
    origin = -0.5 * float(spacing) * float(count - 1)
    return [origin + float(index) * float(spacing) for index in range(count)]


def _rounded_slot_profile(length: float, width: float, *, segments: int = 10) -> list[Vec2]:
    radius = width * 0.5
    straight = max(length - width, 0.0)
    half = straight * 0.5
    points: list[Vec2] = []
    for index in range(segments + 1):
        theta = -pi * 0.5 + pi * (index / float(segments))
        points.append((half + radius * cos(theta), radius * sin(theta)))
    for index in range(segments + 1):
        theta = pi * 0.5 + pi * (index / float(segments))
        points.append((-half + radius * cos(theta), radius * sin(theta)))
    return points


def _loft_between_radii_z(
    cq_module,
    radii_and_offsets: Sequence[tuple[float, float]],
):
    wp = None
    previous_offset = 0.0
    for radius, offset in radii_and_offsets:
        if wp is None:
            wp = cq_module.Workplane("XY").workplane(offset=offset).circle(radius)
        else:
            wp = wp.workplane(offset=offset - previous_offset).circle(radius)
        previous_offset = offset
    if wp is None:
        raise ValueError("No loft sections were provided")
    return wp.loft(combine=True, ruled=False)


def _cut_with_pattern(
    shape,
    cutters: Sequence[object],
):
    for cutter in cutters:
        shape = shape.cut(cutter)
    return shape


def _mesh_geometry_from_cadquery_model(
    model: object,
    *,
    tolerance: float = 0.001,
    angular_tolerance: float = 0.1,
) -> "MeshGeometry":
    import trimesh

    shape = model.val() if hasattr(model, "val") else model
    if hasattr(shape, "fix"):
        try:
            shape = shape.fix()
        except Exception:
            pass

    try:
        vertices_raw, triangles_raw = shape.tessellate(
            float(tolerance),
            float(angular_tolerance),
        )
    except TypeError:
        vertices_raw, triangles_raw = shape.tessellate(float(tolerance))

    vertices = [
        (float(vertex.x), float(vertex.y), float(vertex.z))
        if hasattr(vertex, "x")
        else (float(vertex[0]), float(vertex[1]), float(vertex[2]))
        for vertex in vertices_raw
    ]
    faces = [(int(face[0]), int(face[1]), int(face[2])) for face in triangles_raw]
    if not vertices or not faces:
        raise ValueError("CadQuery tessellation produced an empty mesh")

    # CadQuery tessellation can duplicate shared vertices per face. Normalize the
    # triangle soup so downstream manifold checks and OBJ export see one closed mesh.
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices), faces=np.asarray(faces), process=True)
    if len(mesh.vertices) == 0 or len(mesh.faces) == 0:
        raise ValueError("CadQuery tessellation normalization produced an empty mesh")

    geometry = MeshGeometry(
        vertices=[tuple(float(coord) for coord in vertex) for vertex in mesh.vertices],
        faces=[tuple(int(index) for index in face) for face in mesh.faces],
    )
    try:
        _set_manifold_provenance(
            geometry,
            _manifold_from_geometry(geometry, name="cadquery_tessellation"),
        )
    except ValueError:
        pass
    return geometry


class LouverPanelGeometry(MeshGeometry):
    """
    Build a rectangular panel with slot cutouts and fused louver fins.

    The panel lies in XY and is extruded along Z.
    """

    def __init__(
        self,
        panel_size: Sequence[float],
        thickness: float,
        *,
        frame: float = 0.008,
        slat_pitch: float = 0.024,
        slat_width: float = 0.010,
        slat_angle_deg: float = 32.0,
        corner_radius: float = 0.004,
        center: bool = True,
        fin_thickness: Optional[float] = None,
    ):
        super().__init__()
        panel_w = float(panel_size[0])
        panel_h = float(panel_size[1])
        t = float(thickness)
        frame = float(frame)
        pitch = float(slat_pitch)
        slat_w = float(slat_width)
        corner_radius = max(0.0, float(corner_radius))

        if panel_w <= 0 or panel_h <= 0 or t <= 0:
            raise ValueError("panel_size and thickness must be positive")
        if frame <= 0 or frame >= min(panel_w, panel_h) * 0.5:
            raise ValueError("frame must be > 0 and less than half of min(panel_size)")
        if pitch <= 0 or slat_w <= 0:
            raise ValueError("slat_pitch and slat_width must be positive")
        gap = pitch - slat_w
        if gap <= 1e-6:
            raise ValueError("slat_pitch must be greater than slat_width")

        inner_w = panel_w - 2.0 * frame
        inner_h = panel_h - 2.0 * frame
        if inner_w <= 0 or inner_h <= 0:
            raise ValueError("frame leaves no interior area")
        slot_h = min(gap * 0.9, inner_h * 0.8)
        slot_w = inner_w * 0.95
        if slot_h <= 0.0 or slot_w <= 0.0:
            raise ValueError("frame/slat settings leave no slot area")

        slat_rows: List[float] = []
        y = -inner_h * 0.5 + pitch * 0.5
        limit = inner_h * 0.5 - pitch * 0.5
        while y <= limit + 1e-9:
            slat_rows.append(y)
            y += pitch
        if not slat_rows:
            raise ValueError("No louver rows fit panel; increase panel height or reduce slat_pitch")

        fin_t = float(fin_thickness) if fin_thickness is not None else t * 0.35
        fin_t = max(1e-4, fin_t)
        cq = require_cadquery(feature="LouverPanelGeometry")
        shape = cq.Workplane("XY").box(panel_w, panel_h, t)
        if corner_radius > 0.0:
            shape = shape.edges("|Z").fillet(min(corner_radius, panel_w * 0.5, panel_h * 0.5))

        slot_depth = t + max(0.002, t * 0.5)
        slat_span = min(inner_w + frame * 0.35, panel_w - 2.0e-4)
        slat_z = -t * 0.05

        for row_y in slat_rows:
            slot = cq.Workplane("XY").box(slot_w, slot_h, slot_depth).translate((0.0, row_y, 0.0))
            shape = shape.cut(slot)

            slat = cq.Workplane("XY").box(slat_span, slat_w, fin_t)
            slat = slat.rotate((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), -float(slat_angle_deg))
            slat = slat.translate((0.0, row_y + slot_h * 0.20, slat_z))
            shape = shape.union(slat)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom.translate(0.0, 0.0, t * 0.5)
        self.vertices = [tuple(vertex) for vertex in geom.vertices]
        self.faces = [tuple(face) for face in geom.faces]
        _copy_manifold_provenance(geom, self)


class VentGrilleGeometry(MeshGeometry):
    """
    Build a rectangular vent grille with real openings and a shallow rear sleeve.

    The front flange is centered on local z=0 and the sleeve extends toward -Z.
    """

    def __init__(
        self,
        panel_size: Sequence[float],
        *,
        frame: float = 0.012,
        face_thickness: float = 0.004,
        duct_depth: float = 0.026,
        duct_wall: float = 0.003,
        slat_pitch: float = 0.018,
        slat_width: float = 0.009,
        slat_angle_deg: float = 35.0,
        slat_thickness: Optional[float] = None,
        corner_radius: float = 0.0,
        slats: Optional[VentGrilleSlats] = None,
        frame_profile: Optional[VentGrilleFrame] = None,
        mounts: Optional[VentGrilleMounts] = None,
        sleeve: Optional[VentGrilleSleeve] = None,
        center: bool = True,
    ):
        super().__init__()
        panel_w = float(panel_size[0])
        panel_h = float(panel_size[1])
        frame = float(frame)
        face_t = float(face_thickness)
        duct_depth = float(duct_depth)
        duct_wall = float(duct_wall)
        slat_pitch = float(slat_pitch)
        slat_w = float(slat_width)
        slat_t = float(slat_thickness) if slat_thickness is not None else max(0.001, face_t * 0.35)
        corner_radius = max(0.0, float(corner_radius))
        slats = slats or VentGrilleSlats()
        frame_profile = frame_profile or VentGrilleFrame()
        mounts = mounts or VentGrilleMounts()
        sleeve = sleeve or VentGrilleSleeve()

        if panel_w <= 0 or panel_h <= 0:
            raise ValueError("panel_size must be positive")
        if face_t <= 0 or duct_depth <= 0 or duct_wall <= 0:
            raise ValueError("face_thickness, duct_depth, and duct_wall must be positive")
        if frame <= 0 or frame >= min(panel_w, panel_h) * 0.5:
            raise ValueError("frame must be > 0 and less than half of min(panel_size)")
        if slat_pitch <= 0 or slat_w <= 0 or slat_t <= 0:
            raise ValueError("slat_pitch, slat_width, and slat_thickness must be positive")
        if slat_pitch <= slat_w:
            raise ValueError("slat_pitch must be greater than slat_width")

        slat_profile = str(slats.profile)
        if slat_profile not in {"flat", "airfoil", "boxed"}:
            raise ValueError("slats.profile must be one of flat, airfoil, or boxed")
        slat_direction = str(slats.direction)
        if slat_direction not in {"down", "up"}:
            raise ValueError("slats.direction must be one of down or up")
        slat_inset = float(slats.inset)
        divider_count = int(slats.divider_count)
        divider_width = float(slats.divider_width)
        if slat_inset < 0.0:
            raise ValueError("slats.inset must be non-negative")
        if divider_count < 0:
            raise ValueError("slats.divider_count must be non-negative")
        if divider_count > 0 and divider_width <= 0.0:
            raise ValueError("slats.divider_width must be positive when dividers are requested")

        frame_style = str(frame_profile.style)
        if frame_style not in {"flush", "beveled", "radiused"}:
            raise ValueError("frame_profile.style must be one of flush, beveled, or radiused")
        frame_depth = float(frame_profile.depth)
        if frame_depth < 0.0:
            raise ValueError("frame_profile.depth must be non-negative")

        mount_style = str(mounts.style)
        if mount_style not in {"none", "holes"}:
            raise ValueError("mounts.style must be one of none or holes")
        mount_inset = float(mounts.inset)
        if mount_inset < 0.0:
            raise ValueError("mounts.inset must be non-negative")
        mount_hole_diameter = (
            float(mounts.hole_diameter)
            if mounts.hole_diameter is not None
            else max(frame * 0.36, 0.0032)
        )
        if mount_style != "none" and mount_hole_diameter <= 0.0:
            raise ValueError("mounts.hole_diameter must be positive when mounts are enabled")

        sleeve_style = str(sleeve.style)
        if sleeve_style not in {"none", "short", "full"}:
            raise ValueError("sleeve.style must be one of none, short, or full")
        sleeve_depth = float(sleeve.depth) if sleeve.depth is not None else duct_depth
        sleeve_wall = float(sleeve.wall) if sleeve.wall is not None else duct_wall
        if sleeve_style == "short" and sleeve.depth is None:
            sleeve_depth = max(face_t * 1.8, duct_depth * 0.45)
        if sleeve_style == "none":
            sleeve_depth = 0.0
        if sleeve_style != "none" and sleeve_depth <= 0.0:
            raise ValueError("sleeve.depth must be positive when sleeve.style is not none")
        if sleeve_style != "none" and sleeve_wall <= 0.0:
            raise ValueError("sleeve.wall must be positive when sleeve.style is not none")

        opening_w = panel_w - 2.0 * frame
        opening_h = panel_h - 2.0 * frame
        if sleeve_style != "none" and (
            opening_w <= 2.0 * sleeve_wall or opening_h <= 2.0 * sleeve_wall
        ):
            raise ValueError("frame/duct_wall leave no open sleeve area")
        y = -opening_h * 0.5 + slat_pitch * 0.5
        limit = opening_h * 0.5 - slat_pitch * 0.5
        slat_rows: List[float] = []
        while y <= limit + 1e-9:
            slat_rows.append(y)
            y += slat_pitch
        if not slat_rows:
            raise ValueError("No slat rows fit panel; increase panel height or reduce slat_pitch")

        if divider_count > 0:
            usable_divider_span = opening_w - divider_width
            if usable_divider_span <= 0.0:
                raise ValueError("slats.divider_width leaves no grille opening")
            divider_pitch = usable_divider_span / float(divider_count + 1)
            if divider_pitch <= divider_width:
                raise ValueError("slats.divider_count/divider_width leave no usable openings")

        mount_positions = [
            (panel_w * 0.5 - mount_inset, panel_h * 0.5 - mount_inset),
            (-panel_w * 0.5 + mount_inset, panel_h * 0.5 - mount_inset),
            (panel_w * 0.5 - mount_inset, -panel_h * 0.5 + mount_inset),
            (-panel_w * 0.5 + mount_inset, -panel_h * 0.5 + mount_inset),
        ]
        if mount_style != "none":
            hole_radius = mount_hole_diameter * 0.5
            if hole_radius >= frame * 0.80:
                raise ValueError("mounts.hole_diameter is too large for the frame width")
            for hole_x, hole_y in mount_positions:
                if (
                    abs(hole_x) + hole_radius > panel_w * 0.5
                    or abs(hole_y) + hole_radius > panel_h * 0.5
                ):
                    raise ValueError("mounts.inset places holes outside the face")

        cq = require_cadquery(feature="VentGrilleGeometry")
        shape = cq.Workplane("XY").box(panel_w, panel_h, face_t)
        if corner_radius > 0.0:
            shape = shape.edges("|Z").fillet(
                min(corner_radius, panel_w * 0.5 - frame, panel_h * 0.5 - frame)
            )
        if frame_style == "beveled" and frame_depth > 1.0e-9:
            shape = shape.edges(">Z").chamfer(min(frame_depth, frame * 0.7, face_t * 0.7))
        elif frame_style == "radiused" and frame_depth > 1.0e-9:
            shape = shape.edges(">Z").fillet(min(frame_depth, frame * 0.7, face_t * 0.48))

        shape = shape.cut(
            cq.Workplane("XY").box(
                opening_w,
                opening_h,
                face_t + max(0.002, face_t * 0.5),
            )
        )

        if sleeve_style != "none":
            duct_outer = cq.Workplane("XY").box(opening_w, opening_h, sleeve_depth)
            duct_inner = cq.Workplane("XY").box(
                opening_w - 2.0 * sleeve_wall,
                opening_h - 2.0 * sleeve_wall,
                sleeve_depth + face_t + 0.004,
            )
            duct_shell = duct_outer.cut(duct_inner).translate(
                (0.0, 0.0, -face_t * 0.5 - sleeve_depth * 0.5 + min(face_t * 0.25, 0.001))
            )
            shape = shape.union(duct_shell)

        slat_embed = min(frame * 0.5, 0.002)
        slat_clear_w = opening_w - max(0.0, divider_count * divider_width)
        slat_chord = max(1.0e-4, slat_clear_w + 2.0 * slat_embed)
        slat_z = -face_t * 0.25 - slat_inset
        slat_angle = abs(float(slat_angle_deg)) * (-1.0 if slat_direction == "down" else 1.0)

        def _make_slat():
            if slat_profile == "flat":
                return cq.Workplane("XY").box(slat_chord, slat_w, slat_t)
            if slat_profile == "boxed":
                box_t = max(slat_t * 1.35, slat_w * 0.42)
                return cq.Workplane("XY").box(slat_chord, slat_w, box_t)

            section_points = [
                (-0.50 * slat_w, 0.00),
                (-0.22 * slat_w, 0.56 * slat_t),
                (0.08 * slat_w, 0.64 * slat_t),
                (0.44 * slat_w, 0.10 * slat_t),
                (0.34 * slat_w, -0.22 * slat_t),
                (-0.10 * slat_w, -0.38 * slat_t),
                (-0.44 * slat_w, -0.14 * slat_t),
            ]
            return (
                cq.Workplane("YZ")
                .workplane(offset=-slat_chord * 0.5)
                .polyline(section_points)
                .close()
                .extrude(slat_chord)
            )

        for row_y in slat_rows:
            slat = _make_slat()
            slat = slat.rotate((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), slat_angle)
            slat = slat.translate((0.0, row_y, slat_z))
            shape = shape.union(slat)

        if divider_count > 0:
            divider_positions = _centered_axis_positions(
                opening_w * 0.5 - divider_width * 0.5,
                (opening_w - divider_width) / float(divider_count + 1),
            )
            divider_positions = (
                divider_positions[1:-1]
                if len(divider_positions) > divider_count
                else divider_positions
            )
            divider_depth = max(face_t * 0.90, slat_t * 1.10)
            divider_span_y = opening_h + min(frame * 0.35, 0.003)
            for x_pos in divider_positions[:divider_count]:
                divider = cq.Workplane("XY").box(divider_width, divider_span_y, divider_depth)
                divider = divider.translate((x_pos, 0.0, -face_t * 0.18))
                shape = shape.union(divider)

        if mount_style != "none":
            hole_depth = face_t + max(sleeve_depth, 0.0) + 0.01
            for hole_x, hole_y in mount_positions:
                hole = (
                    cq.Workplane("XY")
                    .circle(mount_hole_diameter * 0.5)
                    .extrude(hole_depth * 0.5, both=True)
                    .translate((hole_x, hole_y, -max(sleeve_depth, 0.0) * 0.5))
                )
                shape = shape.cut(hole)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        self.vertices = [tuple(vertex) for vertex in geom.vertices]
        self.faces = [tuple(face) for face in geom.faces]
        _copy_manifold_provenance(geom, self)


class PerforatedPanelGeometry(MeshGeometry):
    """
    Build a rectangular plate with a grid of round through-holes.

    The panel lies in XY and is extruded along Z.
    """

    def __init__(
        self,
        panel_size: Sequence[float],
        thickness: float,
        *,
        hole_diameter: float,
        pitch: Union[float, Sequence[float]],
        frame: float = 0.008,
        corner_radius: float = 0.0,
        stagger: bool = False,
        center: bool = True,
    ):
        super().__init__()
        panel_w = float(panel_size[0])
        panel_h = float(panel_size[1])
        thickness = float(thickness)
        hole_diameter = float(hole_diameter)
        frame = float(frame)
        corner_radius = max(0.0, float(corner_radius))
        pitch_x, pitch_y = _normalize_pitch_2d(pitch)

        if panel_w <= 0.0 or panel_h <= 0.0 or thickness <= 0.0:
            raise ValueError("panel_size and thickness must be positive")
        if hole_diameter <= 0.0:
            raise ValueError("hole_diameter must be positive")
        if frame < 0.0 or frame >= min(panel_w, panel_h) * 0.5:
            raise ValueError("frame must be >= 0 and less than half of min(panel_size)")
        if pitch_x <= hole_diameter or pitch_y <= hole_diameter:
            raise ValueError("pitch must be greater than hole_diameter on both axes")

        hole_radius = hole_diameter * 0.5
        x_limit = panel_w * 0.5 - frame - hole_radius
        y_limit = panel_h * 0.5 - frame - hole_radius
        if x_limit < -1e-9 or y_limit < -1e-9:
            raise ValueError("frame/hole_diameter leave no usable perforation area")

        y_positions = _centered_axis_positions(y_limit, pitch_y)
        if not y_positions:
            raise ValueError("No perforation rows fit panel; increase panel size or reduce pitch")

        point_rows: list[list[tuple[float, float]]] = []
        for row_index, y in enumerate(y_positions):
            x_offset = pitch_x * 0.5 if stagger and row_index % 2 == 1 else 0.0
            row_limit = x_limit - abs(x_offset)
            if row_limit < -1e-9:
                continue
            x_positions = _centered_axis_positions(row_limit, pitch_x)
            row_points = [(x + x_offset, y) for x in x_positions]
            if row_points:
                point_rows.append(row_points)
        if not point_rows:
            raise ValueError(
                "No perforation columns fit panel; increase panel size or reduce pitch"
            )

        cq = require_cadquery(feature="PerforatedPanelGeometry")
        shape = cq.Workplane("XY").box(panel_w, panel_h, thickness)
        if corner_radius > 0.0:
            shape = shape.edges("|Z").fillet(
                min(corner_radius, panel_w * 0.5 - 1e-4, panel_h * 0.5 - 1e-4)
            )

        cut_depth = thickness + max(0.002, thickness * 0.5)
        cut_shape = None
        for row_points in point_rows:
            row_cut = (
                cq.Workplane("XY")
                .pushPoints(row_points)
                .circle(hole_radius)
                .extrude(
                    cut_depth,
                    both=True,
                )
            )
            cut_shape = row_cut if cut_shape is None else cut_shape.union(row_cut)
        if cut_shape is not None:
            shape = shape.cut(cut_shape)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class SlotPatternPanelGeometry(MeshGeometry):
    """
    Build a rectangular plate with a grid of rounded through-slots.

    The panel lies in XY and is extruded along Z.
    """

    def __init__(
        self,
        panel_size: Sequence[float],
        thickness: float,
        *,
        slot_size: Sequence[float],
        pitch: Union[float, Sequence[float]],
        frame: float = 0.008,
        corner_radius: float = 0.0,
        slot_angle_deg: float = 0.0,
        stagger: bool = False,
        center: bool = True,
    ):
        super().__init__()
        panel_w = float(panel_size[0])
        panel_h = float(panel_size[1])
        thickness = float(thickness)
        slot_length = float(slot_size[0])
        slot_width = float(slot_size[1])
        frame = float(frame)
        corner_radius = max(0.0, float(corner_radius))
        slot_angle_deg = float(slot_angle_deg)
        pitch_x, pitch_y = _normalize_pitch_2d(pitch)

        if panel_w <= 0.0 or panel_h <= 0.0 or thickness <= 0.0:
            raise ValueError("panel_size and thickness must be positive")
        if slot_length <= 0.0 or slot_width <= 0.0:
            raise ValueError("slot_size values must be positive")
        if slot_length < slot_width:
            raise ValueError("slot_size[0] must be greater than or equal to slot_size[1]")
        if frame < 0.0 or frame >= min(panel_w, panel_h) * 0.5:
            raise ValueError("frame must be >= 0 and less than half of min(panel_size)")
        if abs(slot_angle_deg) >= 90.0:
            raise ValueError("abs(slot_angle_deg) must be < 90")

        slot_angle_rad = slot_angle_deg * pi / 180.0
        slot_half_x = 0.5 * (
            abs(slot_length * cos(slot_angle_rad)) + abs(slot_width * sin(slot_angle_rad))
        )
        slot_half_y = 0.5 * (
            abs(slot_length * sin(slot_angle_rad)) + abs(slot_width * cos(slot_angle_rad))
        )
        if pitch_x <= 2.0 * slot_half_x or pitch_y <= 2.0 * slot_half_y:
            raise ValueError("pitch must be greater than the rotated slot envelope on both axes")

        x_limit = panel_w * 0.5 - frame - slot_half_x
        y_limit = panel_h * 0.5 - frame - slot_half_y
        if x_limit < -1e-9 or y_limit < -1e-9:
            raise ValueError("frame/slot_size leave no usable slot area")

        y_positions = _centered_axis_positions(y_limit, pitch_y)
        if not y_positions:
            raise ValueError("No slot rows fit panel; increase panel size or reduce pitch")

        point_rows: list[list[tuple[float, float]]] = []
        for row_index, y in enumerate(y_positions):
            x_offset = pitch_x * 0.5 if stagger and row_index % 2 == 1 else 0.0
            row_limit = x_limit - abs(x_offset)
            if row_limit < -1e-9:
                continue
            x_positions = _centered_axis_positions(row_limit, pitch_x)
            row_points = [(x + x_offset, y) for x in x_positions]
            if row_points:
                point_rows.append(row_points)
        if not point_rows:
            raise ValueError("No slot columns fit panel; increase panel size or reduce pitch")

        cq = require_cadquery(feature="SlotPatternPanelGeometry")
        shape = cq.Workplane("XY").box(panel_w, panel_h, thickness)
        if corner_radius > 0.0:
            shape = shape.edges("|Z").fillet(
                min(corner_radius, panel_w * 0.5 - 1e-4, panel_h * 0.5 - 1e-4)
            )

        cut_depth = thickness + max(0.002, thickness * 0.5)
        slot_core_length = max(slot_length - slot_width, 0.0)

        def build_slot_cut(center_xy: tuple[float, float]):
            slot_cut = None
            if slot_core_length > 1e-6:
                slot_cut = cq.Workplane("XY").box(slot_core_length, slot_width, cut_depth)
            cap_radius = slot_width * 0.5
            cap_offset = slot_core_length * 0.5
            left_cap = (
                cq.Workplane("XY")
                .circle(cap_radius)
                .extrude(cut_depth, both=True)
                .translate((-cap_offset, 0.0, 0.0))
            )
            right_cap = (
                cq.Workplane("XY")
                .circle(cap_radius)
                .extrude(
                    cut_depth,
                    both=True,
                )
                .translate((cap_offset, 0.0, 0.0))
            )
            slot_cut = (
                left_cap.union(right_cap)
                if slot_cut is None
                else slot_cut.union(left_cap).union(right_cap)
            )
            slot_cut = slot_cut.rotate((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), slot_angle_deg)
            return slot_cut.translate((center_xy[0], center_xy[1], 0.0))

        cut_shape = None
        for row_points in point_rows:
            for point in row_points:
                slot_cut = build_slot_cut(point)
                cut_shape = slot_cut if cut_shape is None else cut_shape.union(slot_cut)
        if cut_shape is not None:
            shape = shape.cut(cut_shape)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class ClevisBracketGeometry(MeshGeometry):
    """
    Build a U-shaped clevis bracket with a bottom base and a transverse pin bore.
    """

    def __init__(
        self,
        overall_size: Sequence[float],
        *,
        gap_width: float,
        bore_diameter: float,
        bore_center_z: float,
        base_thickness: float,
        corner_radius: float = 0.0,
        center: bool = True,
    ):
        super().__init__()
        width = float(overall_size[0])
        depth = float(overall_size[1])
        height = float(overall_size[2])
        gap_width = float(gap_width)
        bore_diameter = float(bore_diameter)
        bore_center_z = float(bore_center_z)
        base_thickness = float(base_thickness)
        corner_radius = max(0.0, float(corner_radius))

        if width <= 0.0 or depth <= 0.0 or height <= 0.0:
            raise ValueError("overall_size values must be positive")
        if gap_width <= 0.0 or gap_width >= width:
            raise ValueError("gap_width must be positive and less than overall_size[0]")
        cheek_thickness = 0.5 * (width - gap_width)
        if cheek_thickness <= 1e-6:
            raise ValueError("gap_width leaves no side wall material")
        if bore_diameter <= 0.0 or bore_diameter >= min(cheek_thickness * 2.0, depth, height):
            raise ValueError("bore_diameter is too large for the clevis envelope")
        if base_thickness <= 0.0 or base_thickness >= height:
            raise ValueError("base_thickness must be positive and less than overall_size[2]")
        bore_radius = bore_diameter * 0.5
        if bore_center_z - bore_radius <= base_thickness or bore_center_z + bore_radius >= height:
            raise ValueError(
                "bore_center_z must leave material above the base and below the top edge"
            )

        cq = require_cadquery(feature="ClevisBracketGeometry")
        shape = cq.Workplane("XY").box(width, depth, height)
        slot_cut = (
            cq.Workplane("XY")
            .box(gap_width, depth + 0.004, height - base_thickness)
            .translate((0.0, 0.0, base_thickness * 0.5))
        )
        shape = shape.cut(slot_cut)
        if corner_radius > 0.0:
            shape = shape.edges("|Z").fillet(
                min(corner_radius, cheek_thickness * 0.6, depth * 0.25, height * 0.25)
            )

        bore_z = -height * 0.5 + bore_center_z
        bore = (
            cq.Workplane("YZ")
            .circle(bore_radius)
            .extrude(width + 0.01, both=True)
            .translate((0.0, 0.0, bore_z))
        )
        shape = shape.cut(bore)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class PivotForkGeometry(MeshGeometry):
    """
    Build an open-front pivot fork with a rear bridge and a transverse pin bore.
    """

    def __init__(
        self,
        overall_size: Sequence[float],
        *,
        gap_width: float,
        bore_diameter: float,
        bore_center_z: float,
        bridge_thickness: float,
        corner_radius: float = 0.0,
        center: bool = True,
    ):
        super().__init__()
        width = float(overall_size[0])
        depth = float(overall_size[1])
        height = float(overall_size[2])
        gap_width = float(gap_width)
        bore_diameter = float(bore_diameter)
        bore_center_z = float(bore_center_z)
        bridge_thickness = float(bridge_thickness)
        corner_radius = max(0.0, float(corner_radius))

        if width <= 0.0 or depth <= 0.0 or height <= 0.0:
            raise ValueError("overall_size values must be positive")
        if gap_width <= 0.0 or gap_width >= width:
            raise ValueError("gap_width must be positive and less than overall_size[0]")
        cheek_thickness = 0.5 * (width - gap_width)
        if cheek_thickness <= 1e-6:
            raise ValueError("gap_width leaves no side wall material")
        if bridge_thickness <= 0.0 or bridge_thickness >= depth:
            raise ValueError("bridge_thickness must be positive and less than overall_size[1]")
        if bore_diameter <= 0.0 or bore_diameter >= min(cheek_thickness * 2.0, depth, height):
            raise ValueError("bore_diameter is too large for the pivot fork envelope")
        bore_radius = bore_diameter * 0.5
        if bore_center_z - bore_radius <= 0.0 or bore_center_z + bore_radius >= height:
            raise ValueError("bore_center_z must keep the bore inside the fork cheeks")

        cq = require_cadquery(feature="PivotForkGeometry")
        tine_depth = depth
        left_tine = (
            cq.Workplane("XY")
            .box(cheek_thickness, tine_depth, height)
            .translate((-(gap_width * 0.5 + cheek_thickness * 0.5), 0.0, 0.0))
        )
        right_tine = (
            cq.Workplane("XY")
            .box(cheek_thickness, tine_depth, height)
            .translate(((gap_width * 0.5 + cheek_thickness * 0.5), 0.0, 0.0))
        )
        rear_bridge = (
            cq.Workplane("XY")
            .box(width, bridge_thickness, height)
            .translate((0.0, -depth * 0.5 + bridge_thickness * 0.5, 0.0))
        )
        shape = left_tine.union(right_tine).union(rear_bridge)
        if corner_radius > 0.0:
            shape = shape.edges("|Z").fillet(
                min(corner_radius, cheek_thickness * 0.6, bridge_thickness * 0.6, height * 0.25)
            )

        bore_z = -height * 0.5 + bore_center_z
        bore = (
            cq.Workplane("YZ")
            .circle(bore_radius)
            .extrude(width + 0.01, both=True)
            .translate((0.0, 0.0, bore_z))
        )
        shape = shape.cut(bore)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class TrunnionYokeGeometry(MeshGeometry):
    """
    Build a trunnion support yoke with a bottom base and cheek-mounted trunnion bores.
    """

    def __init__(
        self,
        overall_size: Sequence[float],
        *,
        span_width: float,
        trunnion_diameter: float,
        trunnion_center_z: float,
        base_thickness: float,
        corner_radius: float = 0.0,
        center: bool = True,
    ):
        super().__init__()
        width = float(overall_size[0])
        depth = float(overall_size[1])
        height = float(overall_size[2])
        span_width = float(span_width)
        trunnion_diameter = float(trunnion_diameter)
        trunnion_center_z = float(trunnion_center_z)
        base_thickness = float(base_thickness)
        corner_radius = max(0.0, float(corner_radius))

        if width <= 0.0 or depth <= 0.0 or height <= 0.0:
            raise ValueError("overall_size values must be positive")
        if span_width <= 0.0 or span_width >= width:
            raise ValueError("span_width must be positive and less than overall_size[0]")
        cheek_thickness = 0.5 * (width - span_width)
        if cheek_thickness <= 1e-6:
            raise ValueError("span_width leaves no side wall material")
        if base_thickness <= 0.0 or base_thickness >= height:
            raise ValueError("base_thickness must be positive and less than overall_size[2]")
        if trunnion_diameter <= 0.0 or trunnion_diameter >= min(
            cheek_thickness * 2.0, depth, height
        ):
            raise ValueError("trunnion_diameter is too large for the yoke envelope")
        trunnion_radius = trunnion_diameter * 0.5
        if (
            trunnion_center_z - trunnion_radius <= base_thickness
            or trunnion_center_z + trunnion_radius >= height
        ):
            raise ValueError(
                "trunnion_center_z must leave material above the base and below the top edge"
            )

        cq = require_cadquery(feature="TrunnionYokeGeometry")
        base = (
            cq.Workplane("XY")
            .box(width, depth, base_thickness)
            .translate((0.0, 0.0, -height * 0.5 + base_thickness * 0.5))
        )
        cheek_height = height - base_thickness
        cheek_z = -height * 0.5 + base_thickness + cheek_height * 0.5
        left_cheek = (
            cq.Workplane("XY")
            .box(cheek_thickness, depth, cheek_height)
            .translate((-(span_width * 0.5 + cheek_thickness * 0.5), 0.0, cheek_z))
        )
        right_cheek = (
            cq.Workplane("XY")
            .box(cheek_thickness, depth, cheek_height)
            .translate(((span_width * 0.5 + cheek_thickness * 0.5), 0.0, cheek_z))
        )
        boss_radius = max(trunnion_radius * 1.4, cheek_thickness * 0.55)
        boss_length = min(cheek_thickness * 0.75, depth * 0.35)
        boss_z = -height * 0.5 + trunnion_center_z
        left_boss = (
            cq.Workplane("YZ")
            .circle(boss_radius)
            .extrude(boss_length, both=False)
            .translate((-(span_width * 0.5 + cheek_thickness), 0.0, boss_z))
        )
        right_boss = (
            cq.Workplane("YZ")
            .circle(boss_radius)
            .extrude(-boss_length, both=False)
            .translate(((span_width * 0.5 + cheek_thickness), 0.0, boss_z))
        )
        shape = base.union(left_cheek).union(right_cheek).union(left_boss).union(right_boss)
        if corner_radius > 0.0:
            shape = shape.edges("|Z").fillet(
                min(corner_radius, cheek_thickness * 0.5, depth * 0.2, height * 0.2)
            )

        trunnion_bore = (
            cq.Workplane("YZ")
            .circle(trunnion_radius)
            .extrude(
                width + boss_length * 2.0 + 0.01,
                both=True,
            )
            .translate((0.0, 0.0, boss_z))
        )
        shape = shape.cut(trunnion_bore)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class FanRotorGeometry(MeshGeometry):
    """
    Build an axial fan rotor with a central hub and pitched blades.
    """

    def __init__(
        self,
        outer_radius: float,
        hub_radius: float,
        blade_count: int,
        *,
        thickness: float,
        blade_pitch_deg: float = 28.0,
        blade_sweep_deg: float = 20.0,
        blade_root_chord: Optional[float] = None,
        blade_tip_chord: Optional[float] = None,
        blade: Optional[FanRotorBlade] = None,
        hub: Optional[FanRotorHub] = None,
        shroud: Optional[FanRotorShroud] = None,
        center: bool = True,
    ):
        super().__init__()
        outer_radius = float(outer_radius)
        hub_radius = float(hub_radius)
        thickness = float(thickness)
        blade_pitch_deg = float(blade_pitch_deg)
        blade_sweep_deg = float(blade_sweep_deg)
        blade_count = int(blade_count)
        blade = blade or FanRotorBlade()
        hub = hub or FanRotorHub()

        if outer_radius <= 0.0 or hub_radius <= 0.0 or thickness <= 0.0:
            raise ValueError("outer_radius, hub_radius, and thickness must be positive")
        if blade_count < 2:
            raise ValueError("blade_count must be at least 2")
        if hub_radius >= outer_radius:
            raise ValueError("hub_radius must be less than outer_radius")
        if abs(blade_pitch_deg) >= 85.0:
            raise ValueError("abs(blade_pitch_deg) must be < 85")
        if abs(blade_sweep_deg) >= 85.0:
            raise ValueError("abs(blade_sweep_deg) must be < 85")

        radial_span = outer_radius - hub_radius
        root_chord = (
            float(blade_root_chord)
            if blade_root_chord is not None
            else max(radial_span * 0.32, thickness * 1.5)
        )
        tip_chord = (
            float(blade_tip_chord)
            if blade_tip_chord is not None
            else max(radial_span * 0.20, thickness * 1.2)
        )
        if root_chord <= 0.0 or tip_chord <= 0.0:
            raise ValueError("blade_root_chord and blade_tip_chord must be positive")
        if max(root_chord, tip_chord) >= outer_radius * 1.6:
            raise ValueError("blade chords are too large for the rotor envelope")

        blade_shape = str(blade.shape)
        if blade_shape not in {"straight", "scimitar", "broad", "narrow"}:
            raise ValueError("blade.shape must be one of straight, scimitar, broad, or narrow")
        hub_style = str(hub.style)
        if hub_style not in {"flat", "domed", "capped", "spinner"}:
            raise ValueError("hub.style must be one of flat, domed, capped, or spinner")

        tip_pitch_deg = (
            float(blade.tip_pitch_deg)
            if blade.tip_pitch_deg is not None
            else blade_pitch_deg * 0.56
        )
        if abs(tip_pitch_deg) >= 85.0:
            raise ValueError("abs(blade.tip_pitch_deg) must be < 85")
        camber = float(blade.camber)
        if abs(camber) > 0.50:
            raise ValueError("abs(blade.camber) must be <= 0.5")
        tip_clearance = float(blade.tip_clearance)
        if tip_clearance < 0.0:
            raise ValueError("blade.tip_clearance must be non-negative")

        shroud_thickness = 0.0
        shroud_depth = 0.0
        ring_inner_radius: Optional[float] = None
        ring_outer_radius: Optional[float] = None
        shroud_lip_depth = 0.0
        if shroud is not None:
            shroud_thickness = float(shroud.thickness)
            shroud_depth = (
                float(shroud.depth) if shroud.depth is not None else max(thickness * 0.80, 1.0e-4)
            )
            shroud_clearance = float(shroud.clearance)
            shroud_lip_depth = float(shroud.lip_depth)
            if shroud_thickness <= 0.0:
                raise ValueError("shroud.thickness must be positive")
            if shroud_depth <= 0.0:
                raise ValueError("shroud.depth must be positive")
            if shroud_clearance < 0.0:
                raise ValueError("shroud.clearance must be non-negative")
            if shroud_lip_depth < 0.0:
                raise ValueError("shroud.lip_depth must be non-negative")
            if tip_clearance > 1.0e-9:
                raise ValueError("blade.tip_clearance cannot be used with shroud")
            ring_outer_radius = outer_radius - shroud_clearance
            ring_inner_radius = ring_outer_radius - shroud_thickness
            if ring_outer_radius <= 0.0 or ring_inner_radius <= 0.0:
                raise ValueError("shroud dimensions exceed the rotor envelope")
            if ring_inner_radius <= hub_radius + max(thickness * 0.25, 1.0e-4):
                raise ValueError("shroud leaves no usable blade span")

        def lerp(a: float, b: float, t: float) -> float:
            return float(a) + (float(b) - float(a)) * float(t)

        def chord_scale(t: float) -> float:
            if blade_shape == "straight":
                return 1.00
            if blade_shape == "scimitar":
                return 1.08 - 0.16 * t + 0.05 * sin(pi * t)
            if blade_shape == "broad":
                return 1.05 + 0.10 * sin(pi * t) - 0.03 * t
            return 0.92 - 0.12 * t

        def sweep_factor(t: float) -> float:
            if blade_shape == "straight":
                return t
            if blade_shape == "scimitar":
                return min(1.25, 0.52 * t + 0.76 * t * t)
            if blade_shape == "broad":
                return min(1.08, 0.82 * t + 0.22 * sin(pi * t))
            return 0.82 * t

        cq = require_cadquery(feature="FanRotorGeometry")

        def rotate_section_points(
            points: list[tuple[float, float]],
            angle_rad: float,
        ) -> list[tuple[float, float]]:
            c = cos(angle_rad)
            s = sin(angle_rad)
            return [(y * c - z * s, y * s + z * c) for (y, z) in points]

        def blade_section_points(
            chord: float,
            section_thickness: float,
            pitch_deg: float,
            sweep_y: float,
            span_t: float,
        ) -> list[tuple[float, float]]:
            half_t = max(section_thickness * 0.5, chord * 0.011)
            camber_amplitude = camber * chord * 0.060
            skew_gain = 0.0
            if blade_shape == "scimitar":
                skew_gain = chord * (0.05 + 0.08 * span_t)
            elif blade_shape == "broad":
                skew_gain = chord * 0.03 * span_t
            elif blade_shape == "narrow":
                skew_gain = -chord * 0.04 * span_t

            upper: list[tuple[float, float]] = []
            lower: list[tuple[float, float]] = []
            for u in (0.00, 0.10, 0.24, 0.42, 0.62, 0.82, 1.00):
                chord_pos = (u - 0.5) * chord
                thickness_scale = max(0.12, sin(pi * u) ** 0.82)
                thickness_z = half_t * thickness_scale
                camber_z = camber_amplitude * sin(pi * u)
                skew_y = skew_gain * sin(pi * u) * (u - 0.20)
                upper.append((chord_pos + skew_y, camber_z + thickness_z))
                lower.append((chord_pos + skew_y, camber_z - thickness_z * 0.90))

            raw = upper + list(reversed(lower[1:-1]))
            rotated = rotate_section_points(raw, pitch_deg * pi / 180.0)
            return [(sweep_y + y, z) for (y, z) in rotated]

        hub_body_height = thickness * 0.36
        rear_collar_height = (
            float(hub.rear_collar_height)
            if hub.rear_collar_height is not None
            else thickness * 0.18
        )
        rear_collar_radius = (
            float(hub.rear_collar_radius)
            if hub.rear_collar_radius is not None
            else hub_radius * 0.78
        )
        if rear_collar_height < 0.0:
            raise ValueError("hub.rear_collar_height must be non-negative")
        if rear_collar_height > 1.0e-9 and rear_collar_radius <= 0.0:
            raise ValueError("hub.rear_collar_radius must be positive when rear_collar_height > 0")
        if rear_collar_radius >= hub_radius * 1.05:
            raise ValueError("hub.rear_collar_radius must fit within the hub radius")

        hub_body = cq.Workplane("XY").circle(hub_radius).extrude(hub_body_height * 0.5, both=True)
        shape = hub_body
        if rear_collar_height > 1.0e-9:
            rear_collar = (
                cq.Workplane("XY")
                .circle(rear_collar_radius)
                .extrude(rear_collar_height * 0.5, both=True)
                .translate((0.0, 0.0, -thickness * 0.24))
            )
            shape = shape.union(rear_collar)

        if hub_style == "capped":
            front_cap = (
                cq.Workplane("XY")
                .circle(hub_radius * 0.82)
                .extrude(max(thickness * 0.18, 1.0e-4))
                .translate((0.0, 0.0, hub_body_height * 0.5))
            )
            shape = shape.union(front_cap)
        elif hub_style in {"domed", "spinner"}:
            front_cap_height = thickness * (0.34 if hub_style == "domed" else 0.52)
            front_top_radius = hub_radius * (0.40 if hub_style == "domed" else 0.05)
            front_cap = (
                cq.Workplane("XY")
                .workplane(offset=hub_body_height * 0.5)
                .circle(hub_radius * 0.92)
                .workplane(offset=front_cap_height)
                .circle(max(front_top_radius, 1.0e-4))
                .loft(combine=True, ruled=False)
            )
            shape = shape.union(front_cap)

        if hub.bore_diameter is not None:
            bore_diameter = float(hub.bore_diameter)
            if bore_diameter <= 0.0:
                raise ValueError("hub.bore_diameter must be positive")
            bore_radius = bore_diameter * 0.5
            bore_limit = min(
                hub_radius, rear_collar_radius if rear_collar_height > 0.0 else hub_radius
            )
            if bore_radius >= bore_limit * 0.92:
                raise ValueError("hub.bore_diameter is too large for the hub")
            bore = (
                cq.Workplane("XY")
                .circle(bore_radius)
                .extrude(
                    max(thickness * 1.8, hub_body_height + rear_collar_height + shroud_depth),
                    both=True,
                )
            )
            shape = shape.cut(bore)

        root_radius = hub_radius * 0.82
        if shroud is not None:
            assert ring_inner_radius is not None
            tip_bridge = min(shroud_thickness * 0.18, max(thickness * 0.05, 5.0e-4))
            tip_radius = ring_inner_radius + tip_bridge
        else:
            tip_radius = outer_radius - tip_clearance
        if tip_radius <= root_radius + max(thickness * 0.22, 1.0e-4):
            raise ValueError("blade.tip_clearance leaves no usable blade span")

        blade_span = tip_radius - root_radius
        station_fracs = (0.00, 0.18, 0.42, 0.70, 1.00)
        stations = [root_radius + blade_span * frac for frac in station_fracs]
        section_chords = [
            lerp(root_chord, tip_chord, frac) * chord_scale(frac) for frac in station_fracs
        ]
        root_pitch_deg = blade_pitch_deg * 1.16
        section_pitches = [
            lerp(root_pitch_deg, tip_pitch_deg, frac**0.82) for frac in station_fracs
        ]
        root_section_t = max(thickness * 0.18, root_chord * 0.080)
        tip_section_t = max(thickness * 0.08, tip_chord * 0.048)
        thickness_shape_scale = {
            "straight": 1.00,
            "scimitar": 0.94,
            "broad": 1.08,
            "narrow": 0.88,
        }[blade_shape]
        section_thicknesses = [
            lerp(root_section_t, tip_section_t, frac**0.78) * thickness_shape_scale
            for frac in station_fracs
        ]
        sweep_amount = blade_span * sin(blade_sweep_deg * pi / 180.0) * 0.34
        section_sweeps = [sweep_amount * sweep_factor(frac) for frac in station_fracs]

        blade_wp = None
        previous_station = 0.0
        for station, chord, section_t, pitch_deg, sweep_y, span_t in zip(
            stations,
            section_chords,
            section_thicknesses,
            section_pitches,
            section_sweeps,
            station_fracs,
        ):
            section = blade_section_points(chord, section_t, pitch_deg, sweep_y, span_t)
            if blade_wp is None:
                blade_wp = cq.Workplane("YZ").workplane(offset=station).polyline(section).close()
            else:
                blade_wp = (
                    blade_wp.workplane(offset=station - previous_station).polyline(section).close()
                )
            previous_station = station
        assert blade_wp is not None
        blade_solid = blade_wp.loft(combine=True, ruled=False)

        angle_step = 360.0 / float(blade_count)
        for blade_index in range(blade_count):
            shape = shape.union(
                blade_solid.rotate(
                    (0.0, 0.0, 0.0),
                    (0.0, 0.0, 1.0),
                    angle_step * float(blade_index),
                )
            )

        if shroud is not None:
            assert ring_outer_radius is not None
            assert ring_inner_radius is not None
            tip_ring = (
                cq.Workplane("XY")
                .circle(ring_outer_radius)
                .circle(ring_inner_radius)
                .extrude(shroud_depth * 0.5, both=True)
            )
            shape = shape.union(tip_ring)
            if shroud_lip_depth > 1.0e-9:
                front_lip = (
                    cq.Workplane("XY")
                    .workplane(offset=shroud_depth * 0.5)
                    .circle(ring_outer_radius)
                    .circle(ring_inner_radius)
                    .extrude(shroud_lip_depth)
                )
                shape = shape.union(front_lip)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class BlowerWheelGeometry(MeshGeometry):
    """
    Build a squirrel-cage blower wheel around a central drum.
    """

    def __init__(
        self,
        outer_radius: float,
        inner_radius: float,
        width: float,
        blade_count: int,
        *,
        blade_thickness: float,
        blade_sweep_deg: float = 35.0,
        backplate: bool = True,
        shroud: bool = True,
        center: bool = True,
    ):
        super().__init__()
        outer_radius = float(outer_radius)
        inner_radius = float(inner_radius)
        width = float(width)
        blade_count = int(blade_count)
        blade_thickness = float(blade_thickness)
        blade_sweep_deg = float(blade_sweep_deg)

        if outer_radius <= 0.0 or inner_radius <= 0.0 or width <= 0.0:
            raise ValueError("outer_radius, inner_radius, and width must be positive")
        if inner_radius >= outer_radius:
            raise ValueError("inner_radius must be less than outer_radius")
        if blade_count < 2:
            raise ValueError("blade_count must be at least 2")
        if blade_thickness <= 0.0:
            raise ValueError("blade_thickness must be positive")
        if abs(blade_sweep_deg) >= 85.0:
            raise ValueError("abs(blade_sweep_deg) must be < 85")

        radial_span = outer_radius - inner_radius
        if blade_thickness >= radial_span * 0.9:
            raise ValueError("blade_thickness is too large for the blower annulus")

        cq = require_cadquery(feature="BlowerWheelGeometry")
        drum_wall = min(max(blade_thickness * 1.8, radial_span * 0.10), inner_radius * 0.55)
        if drum_wall <= 1e-6 or inner_radius - drum_wall <= 1e-6:
            raise ValueError("inner_radius is too small for the blower drum wall")
        drum = (
            cq.Workplane("XY")
            .circle(inner_radius)
            .circle(inner_radius - drum_wall)
            .extrude(width * 0.5, both=True)
        )

        shape = drum
        side_plate_thickness = min(max(blade_thickness * 1.1, width * 0.06), width * 0.16)
        side_plate_inner_radius = max(inner_radius - drum_wall * 0.40, 1.0e-4)
        if backplate:
            rear_plate = (
                cq.Workplane("XY")
                .circle(outer_radius)
                .circle(side_plate_inner_radius)
                .extrude(side_plate_thickness, both=False)
                .translate((0.0, 0.0, -width * 0.5))
            )
            shape = shape.union(rear_plate)
        if shroud:
            front_plate = (
                cq.Workplane("XY")
                .circle(outer_radius)
                .circle(side_plate_inner_radius)
                .extrude(side_plate_thickness, both=False)
                .translate((0.0, 0.0, width * 0.5 - side_plate_thickness))
            )
            shape = shape.union(front_plate)

        sweep_rad = blade_sweep_deg * pi / 180.0
        inner_attach_radius = max(inner_radius - drum_wall * 0.08, 1.0e-4)
        outer_attach_radius = outer_radius - blade_thickness * 0.35
        rear_clear = side_plate_thickness * 0.95 if backplate else blade_thickness * 0.50
        front_clear = side_plate_thickness * 0.95 if shroud else blade_thickness * 0.50
        blade_length = width - rear_clear - front_clear
        if blade_length <= blade_thickness * 1.5:
            raise ValueError("width is too small for the blower blade depth")
        blade_center_z = (rear_clear - front_clear) * 0.5

        def annulus_point(radius: float, angle_rad: float) -> tuple[float, float]:
            return (radius * cos(angle_rad), radius * sin(angle_rad))

        def thicken_centerline(
            centerline: list[tuple[float, float]],
            strip_thickness: float,
        ) -> list[tuple[float, float]]:
            half_t = strip_thickness * 0.5
            positive: list[tuple[float, float]] = []
            negative: list[tuple[float, float]] = []
            count = len(centerline)
            for index, point in enumerate(centerline):
                if index == 0:
                    tangent = (
                        centerline[1][0] - point[0],
                        centerline[1][1] - point[1],
                    )
                elif index == count - 1:
                    tangent = (
                        point[0] - centerline[index - 1][0],
                        point[1] - centerline[index - 1][1],
                    )
                else:
                    tangent = (
                        centerline[index + 1][0] - centerline[index - 1][0],
                        centerline[index + 1][1] - centerline[index - 1][1],
                    )
                tangent_norm = sqrt(tangent[0] * tangent[0] + tangent[1] * tangent[1])
                if tangent_norm <= _EPS:
                    normal = (0.0, 1.0)
                else:
                    normal = (-tangent[1] / tangent_norm, tangent[0] / tangent_norm)
                positive.append((point[0] + normal[0] * half_t, point[1] + normal[1] * half_t))
                negative.append((point[0] - normal[0] * half_t, point[1] - normal[1] * half_t))
            return positive + list(reversed(negative))

        def annular_sector_polygon(
            inner_r: float,
            outer_r: float,
            start_angle: float,
            end_angle: float,
            *,
            segments: int = 8,
        ) -> list[tuple[float, float]]:
            outer_points = [
                annulus_point(
                    outer_r,
                    start_angle + (end_angle - start_angle) * (index / float(segments)),
                )
                for index in range(segments + 1)
            ]
            inner_points = [
                annulus_point(
                    inner_r,
                    end_angle - (end_angle - start_angle) * (index / float(segments)),
                )
                for index in range(segments + 1)
            ]
            return outer_points + inner_points

        angle_step = 2.0 * pi / float(blade_count)
        drum_window_inner_radius = max(inner_radius - drum_wall - 1.0e-4, 1.0e-4)
        drum_window_outer_radius = inner_radius + 1.0e-4
        drum_window_span = angle_step * 0.34
        drum_window_length = width - 2.0 * max(side_plate_thickness * 1.15, blade_thickness * 0.8)
        if drum_window_length > blade_thickness:
            for window_index in range(blade_count):
                passage_center = window_index * angle_step + angle_step * 0.5 - sweep_rad * 0.18
                window_profile = annular_sector_polygon(
                    drum_window_inner_radius,
                    drum_window_outer_radius,
                    passage_center - drum_window_span * 0.5,
                    passage_center + drum_window_span * 0.5,
                )
                drum_window = (
                    cq.Workplane("XY")
                    .polyline(window_profile)
                    .close()
                    .extrude(drum_window_length * 0.5, both=True)
                )
                shape = shape.cut(drum_window)

        for blade_index in range(blade_count):
            base_angle = blade_index * angle_step
            centerline = [
                annulus_point(inner_attach_radius, base_angle - sweep_rad * 0.18),
                annulus_point(
                    inner_attach_radius + radial_span * 0.34, base_angle + sweep_rad * 0.10
                ),
                annulus_point(
                    inner_attach_radius + radial_span * 0.68, base_angle + sweep_rad * 0.42
                ),
                annulus_point(outer_attach_radius, base_angle + sweep_rad * 0.72),
            ]
            blade_profile = thicken_centerline(centerline, blade_thickness)
            blade = (
                cq.Workplane("XY")
                .polyline(blade_profile)
                .close()
                .extrude(blade_length * 0.5, both=True)
                .translate((0.0, 0.0, blade_center_z))
            )
            shape = shape.union(blade)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class KnobGeometry(MeshGeometry):
    """
    Build a flexible rotary knob aligned to local Z.
    """

    def __init__(
        self,
        diameter: float,
        height: float,
        *,
        body_style: Literal[
            "cylindrical",
            "tapered",
            "domed",
            "mushroom",
            "skirted",
            "hourglass",
        ] = "cylindrical",
        top_diameter: Optional[float] = None,
        base_diameter: Optional[float] = None,
        crown_radius: float = 0.0,
        edge_radius: float = 0.0,
        side_draft_deg: float = 0.0,
        skirt: Optional[KnobSkirt] = None,
        grip: Optional[KnobGrip] = None,
        indicator: Optional[KnobIndicator] = None,
        top_feature: Optional[KnobTopFeature] = None,
        bore: Optional[KnobBore] = None,
        body_reliefs: Sequence[KnobRelief] = (),
        center: bool = True,
    ):
        super().__init__()
        diameter = float(diameter)
        height = float(height)
        crown_radius = max(0.0, float(crown_radius))
        edge_radius = max(0.0, float(edge_radius))
        side_draft_deg = float(side_draft_deg)
        if diameter <= 0.0 or height <= 0.0:
            raise ValueError("diameter and height must be positive")
        if abs(side_draft_deg) >= 45.0:
            raise ValueError("abs(side_draft_deg) must be < 45")

        base_diameter = float(base_diameter) if base_diameter is not None else diameter
        if base_diameter <= 0.0:
            raise ValueError("base_diameter must be positive")
        top_diameter = float(top_diameter) if top_diameter is not None else diameter
        if top_diameter <= 0.0:
            raise ValueError("top_diameter must be positive")

        skirt = skirt
        grip = grip or KnobGrip()
        indicator = indicator or KnobIndicator()
        top_feature = top_feature or KnobTopFeature()
        bore = bore or KnobBore(style="none")
        if skirt is not None and (skirt.diameter <= 0.0 or skirt.height <= 0.0):
            raise ValueError("KnobSkirt diameter and height must be positive")
        if grip.depth < 0.0:
            raise ValueError("KnobGrip.depth must be non-negative")
        if indicator.depth < 0.0:
            raise ValueError("KnobIndicator.depth must be non-negative")
        if top_feature.depth < 0.0 or top_feature.height < 0.0:
            raise ValueError("KnobTopFeature depth/height must be non-negative")
        if bore.diameter is not None and bore.diameter <= 0.0:
            raise ValueError("KnobBore.diameter must be positive when provided")
        for relief in body_reliefs:
            if relief.depth < 0.0:
                raise ValueError("KnobRelief.depth must be non-negative")

        cq = require_cadquery(feature="KnobGeometry")

        body_height = height
        body_bottom = -height * 0.5
        max_radius = max(base_diameter, top_diameter) * 0.5
        if skirt is not None:
            max_radius = max(max_radius, skirt.diameter * 0.5)

        def body_radius_at(t: float) -> float:
            if body_style == "cylindrical":
                return max(base_diameter, top_diameter) * 0.5
            if body_style == "tapered":
                return (base_diameter * (1.0 - t) + top_diameter * t) * 0.5
            if body_style == "domed":
                if t < 0.72:
                    return (base_diameter * 0.5) * (
                        1.0 - min(max(side_draft_deg / 50.0, -0.2), 0.2) * t
                    )
                u = (t - 0.72) / 0.28
                return max(
                    0.001,
                    top_diameter * 0.5 + (base_diameter * 0.5 - top_diameter * 0.5) * (1.0 - u * u),
                )
            if body_style == "mushroom":
                stem_radius = min(base_diameter, top_diameter, diameter) * 0.28
                cap_radius = max(base_diameter, top_diameter, diameter) * 0.5
                if t < 0.42:
                    return stem_radius
                if t < 0.62:
                    u = (t - 0.42) / 0.20
                    return stem_radius + (cap_radius - stem_radius) * u
                if t < 0.85:
                    return cap_radius
                u = (t - 0.85) / 0.15
                return max(cap_radius * (1.0 - 0.20 * u * u), stem_radius)
            if body_style == "skirted":
                skirt_radius = max(base_diameter * 0.55, diameter * 0.52)
                crown_radius_local = top_diameter * 0.5
                if t < 0.40:
                    return skirt_radius
                if t < 0.56:
                    u = (t - 0.40) / 0.16
                    return skirt_radius + (crown_radius_local - skirt_radius) * u
                return crown_radius_local
            if body_style == "hourglass":
                waist_radius = min(base_diameter, top_diameter, diameter) * 0.32
                if t < 0.5:
                    u = t / 0.5
                    return base_diameter * 0.5 + (waist_radius - base_diameter * 0.5) * u
                u = (t - 0.5) / 0.5
                return waist_radius + (top_diameter * 0.5 - waist_radius) * u
            raise ValueError(f"Unsupported body_style {body_style!r}")

        section_offsets = [
            0.0,
            body_height * 0.18,
            body_height * 0.42,
            body_height * 0.72,
            body_height,
        ]
        radii_and_offsets = [
            (max(0.001, body_radius_at(offset / body_height)), body_bottom + offset)
            for offset in section_offsets
        ]
        shape = _loft_between_radii_z(cq, radii_and_offsets)

        if skirt is not None:
            skirt_radius = skirt.diameter * 0.5
            skirt_bottom = body_bottom - skirt.height
            skirt_shape = _loft_between_radii_z(
                cq,
                [
                    (max(0.001, skirt_radius * (1.0 + skirt.flare)), skirt_bottom),
                    (max(0.001, skirt_radius), body_bottom),
                ],
            )
            shape = shape.union(skirt_shape)

        if edge_radius > 0.0:
            try:
                shape = shape.edges("|Z").fillet(min(edge_radius, max_radius * 0.35, height * 0.18))
            except Exception:
                pass
        if crown_radius > 0.0:
            try:
                shape = (
                    shape.faces(">Z")
                    .edges()
                    .fillet(min(crown_radius, max_radius * 0.25, height * 0.16))
                )
            except Exception:
                pass

        if grip.style != "none" and grip.depth > 1e-6:
            grip_count = grip.count or (28 if grip.style in {"knurled", "diamond_knurl"} else 18)
            if grip_count < 2:
                raise ValueError("KnobGrip.count must be at least 2")
            grip_width = (
                float(grip.width)
                if grip.width is not None
                else (
                    max_radius * 0.18
                    if grip.style in {"fluted", "scalloped"}
                    else max_radius * 0.10
                )
            )
            if grip_width <= 0.0:
                raise ValueError("KnobGrip.width must be positive when provided")

            cutters: list[object] = []
            if grip.style in {"fluted", "scalloped", "ribbed"}:
                cutter_radius = grip_width * (0.55 if grip.style != "ribbed" else 0.38)
                radial_center = max_radius + cutter_radius - grip.depth
                for index in range(grip_count):
                    cutter = (
                        cq.Workplane("XY")
                        .circle(cutter_radius)
                        .extrude(
                            height + (skirt.height if skirt is not None else 0.0) + 0.01, both=True
                        )
                        .translate((radial_center, 0.0, body_bottom + height * 0.5))
                        .rotate((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 360.0 * index / float(grip_count))
                    )
                    cutters.append(cutter)
            else:
                tangential = max(grip_width, max_radius * 0.06)
                radial = max(grip.depth * 1.8, max_radius * 0.06)
                box_height = height * 1.25
                helix_angle = grip.helix_angle_deg if abs(grip.helix_angle_deg) > 1e-6 else 24.0
                for index in range(grip_count):
                    base_angle = 360.0 * index / float(grip_count)
                    for tilt_sign in (-1.0, 1.0) if grip.style == "diamond_knurl" else (1.0,):
                        cutter = (
                            cq.Workplane("XY")
                            .box(radial, tangential, box_height)
                            .translate(
                                (max_radius - grip.depth * 0.5, 0.0, body_bottom + height * 0.5)
                            )
                            .rotate(
                                (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), helix_angle * float(tilt_sign)
                            )
                            .rotate((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), base_angle)
                        )
                        cutters.append(cutter)
            shape = _cut_with_pattern(shape, cutters)

        if indicator.style != "none":
            indicator_length = indicator.length or max(diameter * 0.34, 0.003)
            indicator_width = indicator.width or max(diameter * 0.06, 0.0015)
            indicator_depth = max(indicator.depth, max(height * 0.03, 0.0008))
            top_z = body_bottom + height
            if indicator.style in {"line", "notch"}:
                feature = (
                    cq.Workplane("XY")
                    .box(indicator_length, indicator_width, indicator_depth)
                    .translate((indicator_length * 0.18, 0.0, top_z + indicator_depth * 0.5))
                )
            elif indicator.style == "wedge":
                profile = [
                    (-indicator_width * 0.5, 0.0),
                    (indicator_width * 0.5, 0.0),
                    (0.0, indicator_length),
                ]
                feature = (
                    cq.Workplane("XY")
                    .polyline(profile)
                    .close()
                    .extrude(indicator_depth)
                    .translate((0.0, 0.0, top_z))
                )
            else:
                dot_radius = indicator_width * 0.5
                feature = (
                    cq.Workplane("XY")
                    .circle(dot_radius)
                    .extrude(indicator_depth)
                    .translate((indicator_length * 0.22, 0.0, top_z))
                )
            feature = feature.rotate((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), indicator.angle_deg)
            if indicator.mode == "raised" and indicator.style != "notch":
                shape = shape.union(feature)
            else:
                shape = shape.cut(feature.translate((0.0, 0.0, -indicator_depth * 0.5)))

        if top_feature.style != "none":
            feature_diameter = top_feature.diameter or diameter * 0.55
            feature_radius = feature_diameter * 0.5
            top_z = body_bottom + height
            if feature_radius <= 0.0:
                raise ValueError("KnobTopFeature.diameter must be positive when provided")
            if top_feature.style == "flush_disk":
                feature = (
                    cq.Workplane("XY")
                    .circle(feature_radius)
                    .extrude(max(top_feature.height, height * 0.06))
                    .translate((0.0, 0.0, top_z))
                )
                shape = shape.union(feature)
            elif top_feature.style == "top_insert":
                feature = (
                    cq.Workplane("XY")
                    .circle(feature_radius)
                    .extrude(max(top_feature.height, height * 0.04))
                    .translate((0.0, 0.0, top_z + height * 0.01))
                )
                shape = shape.union(feature)
            else:
                feature = (
                    cq.Workplane("XY")
                    .circle(feature_radius)
                    .extrude(max(top_feature.depth, height * 0.08))
                    .translate((0.0, 0.0, top_z - max(top_feature.depth, height * 0.08)))
                )
                shape = shape.cut(feature)

        if bore.style != "none":
            bore_diameter = bore.diameter or diameter * 0.34
            if bore_diameter <= 0.0 or bore_diameter >= max_radius * 2.0:
                raise ValueError("KnobBore diameter must fit inside the knob body")
            bore_depth = (
                height + (skirt.height if skirt is not None else 0.0) + 0.01
                if bore.through
                else max(height * 0.7, diameter * 0.22)
            )
            if bore.style == "round":
                bore_cut = cq.Workplane("XY").circle(bore_diameter * 0.5).extrude(bore_depth)
            elif bore.style == "hex":
                bore_cut = cq.Workplane("XY").polygon(6, bore_diameter).extrude(bore_depth)
            elif bore.style in {"d_shaft", "double_d"}:
                flat_depth = (
                    float(bore.flat_depth) if bore.flat_depth is not None else bore_diameter * 0.16
                )
                cut_r = bore_diameter * 0.5
                flat_x = cut_r - flat_depth
                circle_points = [
                    (cut_r * cos(theta), cut_r * sin(theta))
                    for theta in np.linspace(0.0, 2.0 * pi, 48, endpoint=False)
                ]
                if bore.style == "d_shaft":
                    profile_points = [(min(point[0], flat_x), point[1]) for point in circle_points]
                else:
                    profile_points = [
                        (max(min(point[0], flat_x), -flat_x), point[1]) for point in circle_points
                    ]
                bore_cut = cq.Workplane("XY").polyline(profile_points).close().extrude(bore_depth)
            else:
                spline_count = bore.spline_count or 8
                if spline_count < 3:
                    raise ValueError("KnobBore.spline_count must be at least 3")
                spline_depth = max(bore.spline_depth, bore_diameter * 0.06)
                outer_r = bore_diameter * 0.5
                inner_r = max(outer_r - spline_depth, outer_r * 0.72)
                points = []
                for index in range(spline_count * 2):
                    theta = pi * index / float(spline_count)
                    radius = outer_r if index % 2 == 0 else inner_r
                    points.append((radius * cos(theta), radius * sin(theta)))
                bore_cut = cq.Workplane("XY").polyline(points).close().extrude(bore_depth)
            bore_cut = bore_cut.translate(
                (0.0, 0.0, body_bottom - (skirt.height if skirt is not None else 0.0))
            )
            shape = shape.cut(bore_cut)

        for relief in body_reliefs:
            relief_depth = max(relief.depth, diameter * 0.04)
            relief_width = relief.width or diameter * 0.22
            relief_height = relief.height or height * 0.18
            if relief.style == "side_window":
                cutter = (
                    cq.Workplane("XY")
                    .box(relief_depth * 2.2, relief_width, relief_height)
                    .translate((max_radius - relief_depth * 0.55, 0.0, body_bottom + height * 0.55))
                    .rotate((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), relief.angle_deg)
                )
                shape = shape.cut(cutter)
            elif relief.style == "top_recess":
                cutter = (
                    cq.Workplane("XY")
                    .circle(relief_width * 0.5)
                    .extrude(relief_depth)
                    .translate((0.0, 0.0, body_bottom + height - relief_depth))
                )
                shape = shape.cut(cutter)
            else:
                cutter = (
                    cq.Workplane("XY")
                    .box(relief_width, relief_width * 0.24, relief_depth)
                    .translate((0.0, 0.0, body_bottom + height - relief_depth * 0.5))
                    .rotate((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), relief.angle_deg)
                )
                shape = shape.cut(cutter)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class BezelGeometry(MeshGeometry):
    """
    Build a framed opening with optional recess, visor, flange, and rear mounts.
    """

    def __init__(
        self,
        opening_size: Sequence[float],
        outer_size: Sequence[float],
        depth: float,
        *,
        opening_shape: Literal[
            "rect", "rounded_rect", "circle", "ellipse", "superellipse"
        ] = "rounded_rect",
        outer_shape: Literal[
            "rect", "rounded_rect", "circle", "ellipse", "superellipse"
        ] = "rounded_rect",
        opening_corner_radius: float = 0.0,
        outer_corner_radius: float = 0.0,
        wall: Union[float, tuple[float, float, float, float], None] = None,
        face: Optional[BezelFace] = None,
        recess: Optional[BezelRecess] = None,
        visor: Optional[BezelVisor] = None,
        flange: Optional[BezelFlange] = None,
        mounts: Optional[BezelMounts] = None,
        cutouts: Sequence[BezelCutout] = (),
        edge_features: Sequence[BezelEdgeFeature] = (),
        center: bool = True,
    ):
        super().__init__()
        opening_w = float(opening_size[0])
        opening_h = float(opening_size[1])
        outer_w = float(outer_size[0])
        outer_h = float(outer_size[1])
        depth = float(depth)
        opening_corner_radius = max(0.0, float(opening_corner_radius))
        outer_corner_radius = max(0.0, float(outer_corner_radius))
        face = face or BezelFace()
        visor = visor or BezelVisor()
        flange = flange or BezelFlange()
        mounts = mounts or BezelMounts()

        if min(opening_w, opening_h, outer_w, outer_h, depth) <= 0.0:
            raise ValueError("opening_size, outer_size, and depth must be positive")
        if opening_w >= outer_w or opening_h >= outer_h:
            raise ValueError("opening_size must be smaller than outer_size on both axes")
        if recess is not None and (recess.depth <= 0.0 or recess.inset < 0.0):
            raise ValueError("BezelRecess depth must be positive and inset must be non-negative")

        cq = require_cadquery(feature="BezelGeometry")
        outer_points = _shape_profile_points_2d(
            outer_shape,
            (outer_w, outer_h),
            corner_radius=outer_corner_radius,
        )
        opening_points = _shape_profile_points_2d(
            opening_shape,
            (opening_w, opening_h),
            corner_radius=opening_corner_radius,
        )
        shape = _cq_ring_solid(cq, outer_points, opening_points, depth, center=True)

        if face.style in {"rounded", "radiused_step"} and face.fillet > 1e-6:
            try:
                shape = shape.edges("|Z").fillet(
                    min(face.fillet, depth * 0.25, min(outer_w, outer_h) * 0.1)
                )
            except Exception:
                pass
        if face.style == "chamfered" and face.chamfer > 1e-6:
            try:
                shape = shape.edges("|Z").chamfer(
                    min(face.chamfer, depth * 0.25, min(outer_w, outer_h) * 0.1)
                )
            except Exception:
                pass

        derived_wall = (
            (outer_w - opening_w) * 0.5,
            (outer_w - opening_w) * 0.5,
            (outer_h - opening_h) * 0.5,
            (outer_h - opening_h) * 0.5,
        )
        if face.front_lip > 1e-6 or face.style == "radiused_step":
            lip_thickness = max(face.front_lip, depth * 0.08, 0.0015)
            if wall is not None:
                lip_size = _shape_size_from_wall(opening_size, wall)
            else:
                lip_size = (
                    min(
                        opening_w + max(face.front_lip * 2.0, derived_wall[0] * 1.05),
                        outer_w - 0.001,
                    ),
                    min(
                        opening_h + max(face.front_lip * 2.0, derived_wall[2] * 1.05),
                        outer_h - 0.001,
                    ),
                )
            if lip_size[0] < outer_w and lip_size[1] < outer_h:
                lip_outer = _shape_profile_points_2d(
                    opening_shape if outer_shape != "circle" else outer_shape,
                    lip_size,
                    corner_radius=min(
                        opening_corner_radius + face.front_lip,
                        lip_size[0] * 0.25,
                        lip_size[1] * 0.25,
                    ),
                )
                lip = _cq_ring_solid(
                    cq, lip_outer, opening_points, lip_thickness, center=True
                ).translate((0.0, 0.0, depth * 0.5))
                shape = shape.union(lip)

        if recess is not None:
            requested_recess_size = (opening_w + recess.inset * 2.0, opening_h + recess.inset * 2.0)
            if wall is None and (
                requested_recess_size[0] >= outer_w or requested_recess_size[1] >= outer_h
            ):
                raise ValueError("recess wall leaves no outer frame material")
            recess_size = (
                _shape_size_from_wall(opening_size, wall)
                if wall is not None
                else (
                    min(requested_recess_size[0], outer_w - 0.001),
                    min(requested_recess_size[1], outer_h - 0.001),
                )
            )
            if recess_size[0] >= outer_w or recess_size[1] >= outer_h:
                raise ValueError("recess wall leaves no outer frame material")
            recess_points = _shape_profile_points_2d(
                opening_shape if outer_shape != "circle" else outer_shape,
                recess_size,
                corner_radius=min(
                    opening_corner_radius + recess.inset,
                    recess_size[0] * 0.25,
                    recess_size[1] * 0.25,
                ),
            )
            recess_cut = _cq_ring_solid(
                cq, recess_points, opening_points, recess.depth, center=True
            ).translate((0.0, 0.0, depth * 0.5 - recess.depth * 0.5))
            shape = shape.cut(recess_cut)

        if visor.thickness > 1e-6 and (visor.top_extension > 1e-6 or visor.side_extension > 1e-6):
            top_visor = (
                cq.Workplane("XY")
                .box(
                    outer_w + visor.side_extension * 2.0,
                    max(visor.top_extension, visor.thickness),
                    visor.thickness,
                )
                .translate((0.0, outer_h * 0.5 + visor.top_extension * 0.5, depth * 0.5))
            )
            shape = shape.union(top_visor)
            if visor.side_extension > 1e-6:
                cheek_y = max(visor.top_extension, outer_h * 0.5) * 0.5
                cheek = cq.Workplane("XY").box(
                    visor.side_extension,
                    max(visor.top_extension, outer_h * 0.45),
                    visor.thickness,
                )
                shape = shape.union(
                    cheek.translate(
                        (outer_w * 0.5 + visor.side_extension * 0.5, cheek_y, depth * 0.5)
                    )
                )
                shape = shape.union(
                    cheek.translate(
                        (-(outer_w * 0.5 + visor.side_extension * 0.5), cheek_y, depth * 0.5)
                    )
                )

        if flange.width > 1e-6 and flange.thickness > 1e-6:
            flange_outer = _shape_profile_points_2d(
                outer_shape,
                (outer_w + flange.width * 2.0, outer_h + flange.width * 2.0),
                corner_radius=outer_corner_radius + flange.width,
            )
            flange_shape = _cq_ring_solid(
                cq, flange_outer, outer_points, flange.thickness, center=True
            ).translate((0.0, 0.0, -depth * 0.5 - flange.offset))
            shape = shape.union(flange_shape)

        if mounts.style == "bosses" and mounts.hole_count > 0:
            boss_radius = (
                max(float(mounts.boss_diameter) * 0.5, 0.0015)
                if mounts.boss_diameter is not None
                else max(min(outer_w, outer_h) * 0.05, 0.003)
            )
            hole_radius = (
                max(float(mounts.hole_diameter) * 0.5, 0.0008)
                if mounts.hole_diameter is not None
                else boss_radius * 0.38
            )
            boss_thickness = max(depth * 0.18, boss_radius * 0.8)
            margin_x = outer_w * 0.5 - boss_radius - max(mounts.setback, 0.001)
            margin_y = outer_h * 0.5 - boss_radius - max(mounts.setback, 0.001)
            boss_points = [
                (-margin_x, -margin_y),
                (margin_x, -margin_y),
                (margin_x, margin_y),
                (-margin_x, margin_y),
            ][: mounts.hole_count]
            for bx, by in boss_points:
                boss = (
                    cq.Workplane("XY")
                    .circle(boss_radius)
                    .extrude(boss_thickness)
                    .translate((bx, by, -depth * 0.5 - boss_thickness))
                )
                hole = (
                    cq.Workplane("XY")
                    .circle(hole_radius)
                    .extrude(boss_thickness + depth + 0.01)
                    .translate((bx, by, -depth * 0.5 - boss_thickness))
                )
                shape = shape.union(boss).cut(hole)
        elif mounts.style == "tabs" and mounts.hole_count > 0:
            tab_width = max(outer_w * 0.16, 0.008)
            tab_depth = max(depth * 0.14, 0.002)
            hole_radius = (
                max(float(mounts.hole_diameter) * 0.5, 0.0008)
                if mounts.hole_diameter is not None
                else tab_width * 0.14
            )
            tab_positions = _centered_pattern_positions(
                mounts.hole_count, outer_w / max(mounts.hole_count, 1)
            )
            for px in tab_positions:
                tab = (
                    cq.Workplane("XY")
                    .box(tab_width, tab_width * 0.6, tab_depth)
                    .translate(
                        (px, -(outer_h * 0.5 + tab_width * 0.3), -depth * 0.5 - tab_depth * 0.5)
                    )
                )
                hole = (
                    cq.Workplane("XY")
                    .circle(hole_radius)
                    .extrude(tab_depth + depth + 0.01)
                    .translate((px, -(outer_h * 0.5 + tab_width * 0.3), -depth * 0.5 - tab_depth))
                )
                shape = shape.union(tab).cut(hole)
        elif (
            mounts.style == "rear_flange"
            and mounts.hole_count > 0
            and mounts.hole_diameter is not None
        ):
            flange_width = max(max(mounts.setback, 0.003), min(outer_w, outer_h) * 0.06)
            rear_flange_outer = _shape_profile_points_2d(
                outer_shape,
                (outer_w + flange_width * 2.0, outer_h + flange_width * 2.0),
                corner_radius=outer_corner_radius + flange_width,
            )
            rear_flange = _cq_ring_solid(
                cq, rear_flange_outer, outer_points, max(depth * 0.12, 0.002), center=True
            ).translate((0.0, 0.0, -depth * 0.5 - max(depth * 0.12, 0.002)))
            shape = shape.union(rear_flange)

        for cutout in cutouts:
            if cutout.width <= 0.0 or cutout.depth <= 0.0:
                raise ValueError("BezelCutout width and depth must be positive")
            cut_height = cutout.width
            cut_depth = cutout.depth
            if cutout.edge in {"top", "bottom"}:
                cutter = cq.Workplane("XY").box(
                    cutout.width, cut_depth, depth + visor.thickness + 0.02
                )
                y = (
                    outer_h * 0.5 - cut_depth * 0.5
                    if cutout.edge == "top"
                    else -outer_h * 0.5 + cut_depth * 0.5
                )
                cutter = cutter.translate((cutout.offset, y, 0.0))
            else:
                cutter = cq.Workplane("XY").box(
                    cut_depth, cut_height, depth + visor.thickness + 0.02
                )
                x = (
                    outer_w * 0.5 - cut_depth * 0.5
                    if cutout.edge == "right"
                    else -outer_w * 0.5 + cut_depth * 0.5
                )
                cutter = cutter.translate((x, cutout.offset, 0.0))
            shape = shape.cut(cutter)

        for feature in edge_features:
            if feature.size <= 0.0:
                continue
            extent = (
                feature.extent
                if feature.extent > 0.0
                else (outer_w if feature.edge in {"top", "bottom"} else outer_h)
            )
            if feature.style == "notch":
                if feature.edge in {"top", "bottom"}:
                    cutter = cq.Workplane("XY").box(
                        extent, feature.size, depth + visor.thickness + 0.02
                    )
                    y = (
                        outer_h * 0.5 - feature.size * 0.5
                        if feature.edge == "top"
                        else -outer_h * 0.5 + feature.size * 0.5
                    )
                    cutter = cutter.translate((feature.offset, y, 0.0))
                else:
                    cutter = cq.Workplane("XY").box(
                        feature.size, extent, depth + visor.thickness + 0.02
                    )
                    x = (
                        outer_w * 0.5 - feature.size * 0.5
                        if feature.edge == "right"
                        else -outer_w * 0.5 + feature.size * 0.5
                    )
                    cutter = cutter.translate((x, feature.offset, 0.0))
                shape = shape.cut(cutter)
                continue
            if feature.edge in {"top", "bottom"}:
                solid = cq.Workplane("XY").box(extent, feature.size, max(depth * 0.10, 0.0015))
                y = (
                    outer_h * 0.5 + feature.size * 0.5
                    if feature.edge == "top"
                    else -(outer_h * 0.5 + feature.size * 0.5)
                )
                solid = solid.translate((feature.offset, y, depth * 0.5))
            else:
                solid = cq.Workplane("XY").box(feature.size, extent, max(depth * 0.10, 0.0015))
                x = (
                    outer_w * 0.5 + feature.size * 0.5
                    if feature.edge == "right"
                    else -(outer_w * 0.5 + feature.size * 0.5)
                )
                solid = solid.translate((x, feature.offset, depth * 0.5))
            shape = (
                shape.union(solid)
                if feature.style == "bead"
                else shape.cut(solid.translate((0.0, 0.0, -max(depth * 0.04, 0.0008))))
            )

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class WheelGeometry(MeshGeometry):
    """
    Build a wheel/rim/hub visual aligned to local X.
    """

    def __init__(
        self,
        radius: float,
        width: float,
        *,
        rim: Optional[WheelRim] = None,
        hub: Optional[WheelHub] = None,
        face: Optional[WheelFace] = None,
        spokes: Optional[WheelSpokes] = None,
        bore: Optional[WheelBore] = None,
        flange: Optional[WheelFlange] = None,
        center: bool = True,
    ):
        super().__init__()
        radius = float(radius)
        width = float(width)
        if radius <= 0.0 or width <= 0.0:
            raise ValueError("radius and width must be positive")

        rim = rim or WheelRim()
        hub = hub or WheelHub(radius=radius * 0.18, width=width * 0.55)
        face = face or WheelFace()
        spokes = spokes or WheelSpokes(style="disc")
        bore = bore or WheelBore(style="round", diameter=max(radius * 0.18, 0.004))

        rim_outer = float(rim.outer_radius) if rim.outer_radius is not None else radius
        rim_inner = float(rim.inner_radius) if rim.inner_radius is not None else radius * 0.68
        if rim_inner <= 0.0 or rim_inner >= rim_outer:
            raise ValueError("WheelRim.inner_radius must be positive and less than outer_radius")
        if hub.radius <= 0.0 or hub.width <= 0.0 or hub.radius >= rim_inner:
            raise ValueError("WheelHub dimensions must be positive and fit inside the rim")
        if bore.diameter <= 0.0 or bore.diameter >= hub.radius * 2.0:
            raise ValueError("WheelBore.diameter must fit inside the hub")

        cq = require_cadquery(feature="WheelGeometry")
        shape = _cq_annulus_x(cq, rim_outer, rim_inner, width)
        if rim.flange_height > 1e-6 and rim.flange_thickness > 1e-6:
            flange_inner = max(rim_outer - rim.flange_height, rim_inner + 1.0e-4)
            lip = _cq_annulus_x(cq, rim_outer, flange_inner, rim.flange_thickness)
            shape = shape.union(lip.translate((width * 0.5 - rim.flange_thickness * 0.5, 0.0, 0.0)))
            shape = shape.union(
                lip.translate((-(width * 0.5 - rim.flange_thickness * 0.5), 0.0, 0.0))
            )
        if rim.bead_seat_depth > 1e-6:
            seat = _cq_annulus_x(
                cq,
                rim_outer,
                max(rim_outer - rim.bead_seat_depth, rim_inner + 1.0e-4),
                max(width * 0.22, 0.004),
            )
            shape = shape.cut(seat)

        hub_cyl = cq.Workplane("YZ").circle(hub.radius).extrude(hub.width * 0.5, both=True)
        shape = shape.union(hub_cyl)
        if hub.cap_style == "domed":
            front_cap = (
                _loft_between_radii_z(
                    cq,
                    [
                        (hub.radius, 0.0),
                        (hub.radius * 0.82, hub.width * 0.12),
                        (hub.radius * 0.30, hub.width * 0.28),
                    ],
                )
                .rotate((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), 90.0)
                .translate((hub.width * 0.5, 0.0, 0.0))
            )
            shape = shape.union(front_cap)
        elif hub.cap_style == "protruding":
            cap = cq.Workplane("YZ").circle(hub.radius * 0.82).extrude(max(width * 0.12, 0.003))
            shape = shape.union(cap.translate((hub.width * 0.5, 0.0, 0.0)))
        elif hub.cap_style == "recessed":
            pocket = cq.Workplane("YZ").circle(hub.radius * 0.55).extrude(max(width * 0.10, 0.002))
            shape = shape.cut(
                pocket.translate((hub.width * 0.5 - max(width * 0.10, 0.002), 0.0, 0.0))
            )

        disc_thickness = max(spokes.thickness, width * 0.08, 0.002)
        face_outer_radius = min(
            rim_outer - max(rim.flange_height * 0.25, radius * 0.02),
            rim_inner + (rim_outer - rim_inner) * 0.28 + face.window_depth,
        )
        face_outer_radius = max(face_outer_radius, hub.radius * 1.6)
        front_inset = _clamp(
            face.front_inset + max(face.dish_depth, 0.0), 0.0, width * 0.5 - disc_thickness * 0.5
        )
        rear_inset = _clamp(face.rear_inset, 0.0, width * 0.5 - disc_thickness * 0.5)
        disc_inner_radius = max(hub.radius * 0.78, hub.radius - max(disc_thickness * 0.35, 0.0012))
        front_disc = _cq_annulus_x(
            cq, face_outer_radius, disc_inner_radius, disc_thickness
        ).translate((width * 0.5 - front_inset - disc_thickness * 0.5, 0.0, 0.0))
        rear_disc = _cq_annulus_x(
            cq, face_outer_radius, disc_inner_radius, disc_thickness
        ).translate((-(width * 0.5 - rear_inset - disc_thickness * 0.5), 0.0, 0.0))
        shape = shape.union(front_disc).union(rear_disc)

        spoke_style = spokes.style
        if spoke_style not in {"none", "disc"}:
            spoke_count = spokes.count or (6 if spoke_style in {"straight", "solid_slots"} else 5)
            if spoke_count < 2:
                raise ValueError("WheelSpokes.count must be at least 2")
            window_width = max(
                spokes.window_radius
                if spokes.window_radius > 0.0
                else (rim_outer - hub.radius) * 0.09,
                0.003,
            )
            slot_length = max((face_outer_radius - hub.radius) * 0.75, 0.010)
            cut_width = width + 0.02
            cutters: list[object] = []

            def radial_slot(
                angle_deg: float, center_radius: float, length: float, width_local: float
            ):
                profile = _rounded_slot_profile(length, width_local)
                slot = (
                    cq.Workplane("YZ")
                    .polyline([(point[1], point[0] + center_radius) for point in profile])
                    .close()
                    .extrude(cut_width * 0.5, both=True)
                    .rotate((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), angle_deg)
                )
                return slot

            if spoke_style in {"straight", "solid_slots"}:
                for index in range(spoke_count):
                    cutters.append(
                        radial_slot(
                            360.0 * index / float(spoke_count),
                            (hub.radius + face_outer_radius) * 0.5,
                            slot_length,
                            window_width * (1.5 if spoke_style == "solid_slots" else 1.0),
                        )
                    )
            elif spoke_style == "split_y":
                for index in range(spoke_count):
                    base = 360.0 * index / float(spoke_count)
                    cutters.append(
                        radial_slot(
                            base - 10.0,
                            hub.radius + (face_outer_radius - hub.radius) * 0.44,
                            slot_length * 0.55,
                            window_width * 0.85,
                        )
                    )
                    cutters.append(
                        radial_slot(
                            base + 10.0,
                            hub.radius + (face_outer_radius - hub.radius) * 0.64,
                            slot_length * 0.55,
                            window_width * 0.85,
                        )
                    )
            else:
                rows = (
                    hub.radius + (face_outer_radius - hub.radius) * 0.36,
                    hub.radius + (face_outer_radius - hub.radius) * 0.68,
                )
                for row_index, center_radius in enumerate(rows):
                    count = spoke_count * (2 if row_index == 1 else 1)
                    for index in range(count):
                        cutters.append(
                            radial_slot(
                                360.0 * index / float(count)
                                + (180.0 / float(count) if row_index == 1 else 0.0),
                                center_radius,
                                slot_length * (0.30 if row_index == 0 else 0.24),
                                window_width * 0.72,
                            )
                        )
            shape = _cut_with_pattern(shape, cutters)

        if hub.bolt_pattern is not None:
            pattern = hub.bolt_pattern
            if pattern.count < 2 or pattern.circle_diameter <= 0.0 or pattern.hole_diameter <= 0.0:
                raise ValueError(
                    "BoltPattern count, circle_diameter, and hole_diameter must be positive"
                )
            bolt_r = pattern.circle_diameter * 0.5
            if bolt_r + pattern.hole_diameter * 0.5 >= hub.radius:
                raise ValueError("BoltPattern holes must fit inside the hub")
            for index in range(pattern.count):
                angle = 2.0 * pi * index / float(pattern.count)
                hole = (
                    cq.Workplane("YZ")
                    .circle(pattern.hole_diameter * 0.5)
                    .extrude(width + 0.04, both=True)
                    .translate((0.0, bolt_r * cos(angle), bolt_r * sin(angle)))
                )
                shape = shape.cut(hole)

        if bore.style == "round":
            bore_cut = (
                cq.Workplane("YZ").circle(bore.diameter * 0.5).extrude(width + 0.04, both=True)
            )
        elif bore.style == "hex":
            bore_cut = cq.Workplane("YZ").polygon(6, bore.diameter).extrude(width + 0.04, both=True)
        else:
            key_width = bore.key_width or bore.diameter * 0.32
            bore_cut = (
                cq.Workplane("YZ").circle(bore.diameter * 0.5).extrude(width + 0.04, both=True)
            )
            key = cq.Workplane("YZ").box(width + 0.04, key_width, bore.diameter * 0.5)
            bore_cut = bore_cut.union(key.translate((0.0, bore.diameter * 0.25, 0.0)))
        shape = shape.cut(bore_cut)

        if flange is not None:
            if flange.radius <= 0.0 or flange.thickness <= 0.0:
                raise ValueError("WheelFlange radius and thickness must be positive")
            ring_inner = max(flange.radius - flange.thickness, hub.radius * 1.05)
            ring = _cq_annulus_x(cq, flange.radius, ring_inner, flange.thickness * 0.6)
            bridge_len = max(flange.offset + flange.thickness * 0.6, flange.thickness * 0.8)
            bridge_radial = max(flange.radius - rim_outer + flange.thickness * 0.35, 0.006)
            bridge_thickness = max(flange.thickness * 0.55, 0.0015)
            strut = cq.Workplane("XY").box(bridge_len, bridge_radial, bridge_thickness)
            x_offsets: list[float] = []
            if flange.side in {"front", "both"}:
                x_offsets.append(width * 0.5 + flange.offset)
            if flange.side in {"rear", "both"}:
                x_offsets.append(-(width * 0.5 + flange.offset))
            for x_offset in x_offsets:
                ring_shape = ring.translate((x_offset, 0.0, 0.0))
                shape = shape.union(ring_shape)
                axial_mid = (
                    (width * 0.5 + x_offset) * 0.5
                    if x_offset >= 0.0
                    else (-(width * 0.5) + x_offset) * 0.5
                )
                radial_mid = (rim_outer + ring_inner) * 0.5
                for angle_deg in (0.0, 90.0, 180.0, 270.0):
                    shape = shape.union(
                        strut.translate((axial_mid, radial_mid, 0.0)).rotate(
                            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), angle_deg
                        )
                    )

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_axis0(geom, 0)
        _adopt_mesh_geometry(self, geom)


class TireGeometry(MeshGeometry):
    """
    Build a tire aligned to local X.
    """

    def __init__(
        self,
        outer_radius: float,
        width: float,
        *,
        inner_radius: Optional[float] = None,
        carcass: Optional[TireCarcass] = None,
        tread: Optional[TireTread] = None,
        grooves: Sequence[TireGroove] = (),
        sidewall: Optional[TireSidewall] = None,
        shoulder: Optional[TireShoulder] = None,
        center: bool = True,
    ):
        super().__init__()
        outer_radius = float(outer_radius)
        width = float(width)
        inner_radius = float(inner_radius) if inner_radius is not None else outer_radius * 0.58
        carcass = carcass or TireCarcass()
        tread = tread or TireTread()
        sidewall = sidewall or TireSidewall()
        shoulder = shoulder or TireShoulder()

        if outer_radius <= 0.0 or width <= 0.0 or inner_radius <= 0.0:
            raise ValueError("outer_radius, width, and inner_radius must be positive")
        if inner_radius >= outer_radius:
            raise ValueError("inner_radius must be less than outer_radius")
        if tread.depth < 0.0:
            raise ValueError("TireTread.depth must be non-negative")
        for groove in grooves:
            if groove.width < 0.0 or groove.depth < 0.0:
                raise ValueError("TireGroove width/depth must be non-negative")

        cq = require_cadquery(feature="TireGeometry")
        half_w = width * 0.5
        belt_half = half_w * _clamp(carcass.belt_width_ratio, 0.12, 0.96)
        shoulder_w = shoulder.width if shoulder.width > 1e-6 else width * 0.11
        side_bulge = max(sidewall.bulge, carcass.sidewall_bulge, 0.0)
        inner_crown = inner_radius * 0.82
        if sidewall.style == "square":
            outer_side = outer_radius
            shoulder_radius = max(
                outer_radius - max(shoulder.radius, tread.depth * 0.5, outer_radius * 0.01),
                inner_radius + 1.0e-4,
            )
        elif sidewall.style == "flat":
            outer_side = max(outer_radius - width * 0.08, inner_radius + 1.0e-4)
            shoulder_radius = outer_radius
        elif sidewall.style == "bulged":
            outer_side = min(outer_radius + side_bulge * width, outer_radius + width * 0.12)
            shoulder_radius = outer_radius
        else:
            outer_side = max(outer_radius - width * 0.04, inner_radius + 1.0e-4)
            shoulder_radius = outer_radius

        profile = [
            (-half_w, inner_radius),
            (-half_w * 0.92, inner_radius),
            (
                -half_w * 0.78,
                max(inner_radius + (outer_side - inner_radius) * 0.28, inner_radius + 1.0e-4),
            ),
            (-(belt_half + shoulder_w), outer_side),
            (-belt_half, shoulder_radius),
            (0.0, outer_radius),
            (belt_half, shoulder_radius),
            (belt_half + shoulder_w, outer_side),
            (
                half_w * 0.78,
                max(inner_radius + (outer_side - inner_radius) * 0.28, inner_radius + 1.0e-4),
            ),
            (half_w * 0.92, inner_radius),
            (half_w, inner_radius),
            (half_w * 0.55, inner_crown),
            (0.0, inner_crown),
            (-half_w * 0.55, inner_crown),
            (-half_w, inner_radius),
        ]
        shape = (
            cq.Workplane("XY")
            .polyline(profile)
            .close()
            .revolve(360.0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        )

        for groove in grooves:
            if groove.width <= 1e-6 or groove.depth <= 1e-6:
                continue
            cutter = (
                cq.Workplane("XY")
                .moveTo(groove.center_offset - groove.width * 0.5, outer_radius - groove.depth)
                .lineTo(groove.center_offset + groove.width * 0.5, outer_radius - groove.depth)
                .lineTo(
                    groove.center_offset + groove.width * 0.5, outer_radius + groove.depth * 1.6
                )
                .lineTo(
                    groove.center_offset - groove.width * 0.5, outer_radius + groove.depth * 1.6
                )
                .close()
                .revolve(360.0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
            )
            shape = shape.cut(cutter)

        tread_style = tread.style
        tread_depth = tread.depth
        if tread_style == "circumferential" and tread_depth > 1e-6:
            groove_count = tread.count or 3
            band_positions = _centered_pattern_positions(
                groove_count, max(tread.pitch or (width * 0.20), width * 0.14)
            )
            for pos in band_positions:
                cutter = (
                    cq.Workplane("XY")
                    .moveTo(pos - width * 0.03, outer_radius - tread_depth)
                    .lineTo(pos + width * 0.03, outer_radius - tread_depth)
                    .lineTo(pos + width * 0.03, outer_radius + tread_depth * 1.4)
                    .lineTo(pos - width * 0.03, outer_radius + tread_depth * 1.4)
                    .close()
                    .revolve(360.0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
                )
                shape = shape.cut(cutter)
        elif tread_style == "rib" and tread_depth > 1e-6:
            rib_count = tread.count or 3
            rib_positions = _centered_pattern_positions(
                rib_count, max(tread.pitch or (width * 0.20), width * 0.14)
            )
            for pos in rib_positions:
                rib = (
                    cq.Workplane("XY")
                    .moveTo(pos - width * 0.04, outer_radius)
                    .lineTo(pos + width * 0.04, outer_radius)
                    .lineTo(pos + width * 0.04, outer_radius + tread_depth)
                    .lineTo(pos - width * 0.04, outer_radius + tread_depth)
                    .close()
                    .revolve(360.0, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
                )
                shape = shape.union(rib)
        elif tread_style in {"block", "lug", "chevron"} and tread_depth > 1e-6:
            circ_count = tread.count or (
                12
                if tread_style == "lug"
                else max(
                    14,
                    int(
                        (2.0 * pi * outer_radius) / max(tread.pitch or (width * 0.45), width * 0.24)
                    ),
                )
            )
            axial_rows = (
                [-width * 0.22, width * 0.22]
                if tread_style == "lug"
                else (
                    [-width * 0.22, 0.0, width * 0.22]
                    if tread_style == "block"
                    else [-width * 0.18, width * 0.18]
                )
            )
            tangential = (2.0 * pi * outer_radius / float(circ_count)) * _clamp(
                tread.land_ratio, 0.18, 0.85
            )
            axial_width = width * (0.14 if tread_style == "lug" else 0.12)
            for row_index, row_x in enumerate(axial_rows):
                for index in range(circ_count):
                    angle_deg = 360.0 * index / float(circ_count) + (
                        180.0 / float(circ_count) if row_index % 2 == 1 else 0.0
                    )
                    if tread_style == "chevron":
                        for sign in (-1.0, 1.0):
                            lug = (
                                cq.Workplane("XY")
                                .box(axial_width, tread_depth * 1.35, tangential * 0.48)
                                .translate(
                                    (
                                        row_x + sign * axial_width * 0.38,
                                        outer_radius + tread_depth * 0.16,
                                        0.0,
                                    )
                                )
                                .rotate(
                                    (0.0, 0.0, 0.0),
                                    (0.0, 1.0, 0.0),
                                    tread.angle_deg * sign
                                    if abs(tread.angle_deg) > 1e-6
                                    else 24.0 * sign,
                                )
                                .rotate((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), angle_deg)
                            )
                            shape = shape.union(lug)
                    else:
                        lug = (
                            cq.Workplane("XY")
                            .box(
                                axial_width,
                                tread_depth * 1.35,
                                tangential * (0.55 if tread_style == "lug" else 0.42),
                            )
                            .translate((row_x, outer_radius + tread_depth * 0.16, 0.0))
                            .rotate((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), angle_deg)
                        )
                        shape = shape.union(lug)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_axis0(geom, 0)
        _adopt_mesh_geometry(self, geom)


class BarrelHingeGeometry(MeshGeometry):
    """
    Build an exposed barrel hinge with two leaves around a local Z pin axis.
    """

    def __init__(
        self,
        length: float,
        *,
        leaf_width_a: float,
        leaf_width_b: Optional[float] = None,
        leaf_thickness: float,
        pin_diameter: float,
        knuckle_outer_diameter: Optional[float] = None,
        knuckle_count: int = 5,
        clearance: float = 0.0005,
        open_angle_deg: float = 180.0,
        holes_a: Optional[HingeHolePattern] = None,
        holes_b: Optional[HingeHolePattern] = None,
        pin: Optional[HingePinStyle] = None,
        center: bool = True,
    ):
        super().__init__()
        length = float(length)
        leaf_width_a = float(leaf_width_a)
        leaf_width_b = float(leaf_width_b) if leaf_width_b is not None else leaf_width_a
        leaf_thickness = float(leaf_thickness)
        pin_diameter = float(pin_diameter)
        knuckle_outer_diameter = (
            float(knuckle_outer_diameter)
            if knuckle_outer_diameter is not None
            else pin_diameter * 1.75
        )
        clearance = float(clearance)
        open_angle_deg = float(open_angle_deg)
        holes_a = holes_a or HingeHolePattern()
        holes_b = holes_b or HingeHolePattern()
        pin = pin or HingePinStyle()

        if (
            min(
                length,
                leaf_width_a,
                leaf_width_b,
                leaf_thickness,
                pin_diameter,
                knuckle_outer_diameter,
            )
            <= 0.0
        ):
            raise ValueError(
                "length, leaf widths, thickness, pin_diameter, and knuckle size must be positive"
            )
        if knuckle_count < 3:
            raise ValueError("knuckle_count must be at least 3")
        if pin_diameter >= knuckle_outer_diameter:
            raise ValueError("pin_diameter must be less than knuckle_outer_diameter")
        segment_length = (length - clearance * float(knuckle_count - 1)) / float(knuckle_count)
        if segment_length <= 0.0:
            raise ValueError("clearance/knuckle_count leave no knuckle length")

        cq = require_cadquery(feature="BarrelHingeGeometry")
        leaf_overlap = min(leaf_thickness * 0.75, knuckle_outer_diameter * 0.12)
        leaf_a = (
            cq.Workplane("XY")
            .box(leaf_width_a, leaf_thickness, length)
            .translate(
                (-(knuckle_outer_diameter * 0.5 + leaf_width_a * 0.5 - leaf_overlap), 0.0, 0.0)
            )
        )
        leaf_b = (
            cq.Workplane("XY")
            .box(leaf_width_b, leaf_thickness, length)
            .translate(
                ((knuckle_outer_diameter * 0.5 + leaf_width_b * 0.5 - leaf_overlap), 0.0, 0.0)
            )
        )
        leaf_b = leaf_b.rotate((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 180.0 - open_angle_deg)
        shape = leaf_a.union(leaf_b)

        z_start = -length * 0.5
        for index in range(knuckle_count):
            center_z = z_start + segment_length * 0.5 + index * (segment_length + clearance)
            knuckle = (
                cq.Workplane("XY")
                .circle(knuckle_outer_diameter * 0.5)
                .extrude(segment_length)
                .translate((0.0, 0.0, center_z - segment_length * 0.5))
            )
            shape = shape.union(knuckle)

        pin_len = length + pin.exposed_end * 2.0
        pin_bottom = -length * 0.5 - pin.exposed_end
        pin_shape = (
            cq.Workplane("XY")
            .circle(pin_diameter * 0.5)
            .extrude(pin_len)
            .translate((0.0, 0.0, pin_bottom))
        )
        if pin.head_style != "plain" and pin.head_height > 1e-6:
            head_d = pin.head_diameter or pin_diameter * 1.6
            head = cq.Workplane("XY").circle(head_d * 0.5).extrude(pin.head_height)
            pin_shape = pin_shape.union(head.translate((0.0, 0.0, pin_bottom - pin.head_height)))
            if pin.head_style != "peened":
                pin_shape = pin_shape.union(head.translate((0.0, 0.0, pin_bottom + pin_len)))
        shape = shape.union(pin_shape)

        def _apply_holes(base_shape, pattern: HingeHolePattern, side: float):
            if pattern.style == "none" or pattern.count <= 0:
                return base_shape
            if pattern.diameter is None and pattern.slot_size is None:
                raise ValueError("HingeHolePattern requires diameter or slot_size")
            count = pattern.count
            z_positions = _centered_pattern_positions(
                count,
                pattern.pitch
                if pattern.pitch is not None
                else (length - pattern.edge_margin * 2.0) / max(count - 1, 1),
            )
            x_center = side * (
                knuckle_outer_diameter * 0.5 + (leaf_width_a if side < 0.0 else leaf_width_b) * 0.5
            )
            for z_pos in z_positions:
                if pattern.style == "slotted":
                    if pattern.slot_size is None:
                        raise ValueError("Slotted hinge holes require slot_size")
                    slot_profile = _rounded_slot_profile(pattern.slot_size[0], pattern.slot_size[1])
                    cutter = (
                        cq.Workplane("XZ")
                        .polyline(
                            [(x_center + point[0], z_pos + point[1]) for point in slot_profile]
                        )
                        .close()
                        .extrude(leaf_thickness + 0.01, both=True)
                    )
                else:
                    hole_r = (pattern.diameter or 0.0) * 0.5
                    cutter = (
                        cq.Workplane("XZ")
                        .circle(hole_r)
                        .extrude(leaf_thickness + 0.01, both=True)
                        .translate((x_center, 0.0, z_pos))
                    )
                base_shape = base_shape.cut(cutter)
            return base_shape

        shape = _apply_holes(shape, holes_a, -1.0)
        shape = _apply_holes(shape, holes_b, 1.0)

        geom = _mesh_geometry_from_cadquery_model(shape)
        if not center:
            geom = _mesh_geometry_shifted_to_z0(geom)
        _adopt_mesh_geometry(self, geom)


class PianoHingeGeometry(MeshGeometry):
    """
    Build a continuous piano hinge strip around a local Z pin axis.
    """

    def __init__(
        self,
        length: float,
        *,
        leaf_width_a: float,
        leaf_width_b: Optional[float] = None,
        leaf_thickness: float,
        pin_diameter: float,
        knuckle_pitch: float,
        clearance: float = 0.0005,
        open_angle_deg: float = 180.0,
        holes_a: Optional[HingeHolePattern] = None,
        holes_b: Optional[HingeHolePattern] = None,
        pin: Optional[HingePinStyle] = None,
        center: bool = True,
    ):
        knuckle_pitch = float(knuckle_pitch)
        if knuckle_pitch <= 0.0:
            raise ValueError("knuckle_pitch must be positive")
        knuckle_count = max(3, int(length / knuckle_pitch))
        if knuckle_count % 2 == 0:
            knuckle_count += 1
        knuckle_outer_diameter = pin_diameter * 1.55
        base = BarrelHingeGeometry(
            length,
            leaf_width_a=leaf_width_a,
            leaf_width_b=leaf_width_b,
            leaf_thickness=leaf_thickness,
            pin_diameter=pin_diameter,
            knuckle_outer_diameter=knuckle_outer_diameter,
            knuckle_count=knuckle_count,
            clearance=clearance,
            open_angle_deg=open_angle_deg,
            holes_a=holes_a,
            holes_b=holes_b,
            pin=pin,
            center=center,
        )
        _adopt_mesh_geometry(self, base)


class SweepGeometry(MeshGeometry):
    def __init__(
        self,
        profile: Iterable[Tuple[float, float]],
        path: Iterable[Tuple[float, float, float]],
        *,
        cap: bool = False,
        closed: bool = True,
    ):
        super().__init__()
        points = _ensure_ccw(_profile_points_2d(profile))
        if not closed:
            cap = False

        path_points = [(float(x), float(y), float(z)) for (x, y, z) in path]
        if len(path_points) < 2:
            raise ValueError("Sweep requires at least two path points")

        profiles = [[(x + px, y + py, pz) for (x, y) in points] for (px, py, pz) in path_points]
        self.merge(LoftGeometry(profiles, cap=cap, closed=closed))


def _dedupe_path_points(path: List[Vec3]) -> List[Vec3]:
    if not path:
        return []
    out = [path[0]]
    for p in path[1:]:
        if _v_norm(_v_sub(p, out[-1])) > _EPS:
            out.append(p)
    return out


def _compute_path_tangents(path: List[Vec3]) -> List[Vec3]:
    n = len(path)
    if n < 2:
        raise ValueError("Pipe path requires at least two distinct points")
    tangents: List[Vec3] = []
    for i in range(n):
        if i == 0:
            d = _v_sub(path[1], path[0])
        elif i == n - 1:
            d = _v_sub(path[-1], path[-2])
        else:
            d = _v_sub(path[i + 1], path[i - 1])
        tangents.append(_v_normalize(d))
    return tangents


def _initial_frame(tangent: Vec3, up_hint: Vec3) -> Tuple[Vec3, Vec3]:
    up = _v_normalize(up_hint)
    if abs(_v_dot(up, tangent)) > 0.95:
        up = (0.0, 1.0, 0.0) if abs(tangent[1]) < 0.95 else (1.0, 0.0, 0.0)
    n = _v_cross(up, tangent)
    if _v_norm(n) <= _EPS:
        n = _v_cross((0.0, 0.0, 1.0), tangent)
    n = _v_normalize(n)
    b = _v_normalize(_v_cross(tangent, n))
    return (n, b)


@dataclass
class _WireCorner:
    incoming_end: Vec3
    outgoing_start: Vec3
    bridge: List[Vec3]


def _append_distinct_path_point(points: List[Vec3], point: Vec3, *, tol: float = _EPS) -> None:
    p = (float(point[0]), float(point[1]), float(point[2]))
    if not points or _v_norm(_v_sub(points[-1], p)) > tol:
        points.append(p)


def _preprocess_wire_polyline_points(
    points: Iterable[Vec3],
    *,
    min_segment_length: float,
    closed_path: bool,
) -> List[Vec3]:
    raw = [(float(x), float(y), float(z)) for (x, y, z) in points]
    if len(raw) < 2:
        raise ValueError("WirePolylineGeometry requires at least two input points")

    tol = max(float(min_segment_length), _EPS)
    out: List[Vec3] = [raw[0]]
    for point in raw[1:]:
        if _v_norm(_v_sub(point, out[-1])) >= tol:
            out.append(point)

    if len(out) < 2:
        raise ValueError("Too few distinct points after dedupe")

    if closed_path:
        if _v_norm(_v_sub(out[0], out[-1])) <= tol:
            out[-1] = out[0]
        else:
            out.append(out[0])
        # Closed loops need at least three distinct vertices.
        if len(out) < 4:
            raise ValueError("Closed path requires at least three distinct points")

    return out


def _wire_corner_from_three_points(
    prev_point: Vec3,
    corner_point: Vec3,
    next_point: Vec3,
    *,
    corner_mode: str,
    corner_radius: float,
    corner_segments: int,
) -> _WireCorner:
    incoming = _v_sub(corner_point, prev_point)
    outgoing = _v_sub(next_point, corner_point)
    len_in = _v_norm(incoming)
    len_out = _v_norm(outgoing)

    if len_in <= _EPS or len_out <= _EPS:
        if corner_mode == "fillet" and corner_radius > 0.0:
            raise ValueError("Impossible fillet: corner has zero-length segment")
        return _WireCorner(corner_point, corner_point, [corner_point])

    u = _v_scale(incoming, 1.0 / len_in)
    v = _v_scale(outgoing, 1.0 / len_out)
    theta = acos(_clamp(_v_dot(_v_scale(u, -1.0), v), -1.0, 1.0))

    # Straight-through and U-turn corners fall back to miter behavior.
    if theta <= 1e-6 or abs(pi - theta) <= 1e-6:
        return _WireCorner(corner_point, corner_point, [corner_point])
    if corner_mode == "miter" or corner_radius <= 0.0:
        return _WireCorner(corner_point, corner_point, [corner_point])

    tan_half = tan(theta * 0.5)
    if abs(tan_half) <= _EPS:
        return _WireCorner(corner_point, corner_point, [corner_point])

    target_trim = corner_radius * tan_half
    if not isfinite(target_trim):
        target_trim = float("inf")
    trim = min(target_trim, 0.49 * min(len_in, len_out))
    if trim <= _EPS:
        return _WireCorner(corner_point, corner_point, [corner_point])

    a = _v_sub(corner_point, _v_scale(u, trim))
    b = _v_add(corner_point, _v_scale(v, trim))

    if corner_mode == "bevel":
        return _WireCorner(a, b, [a, b])

    radius_eff = trim / tan_half
    if radius_eff <= _EPS:
        return _WireCorner(corner_point, corner_point, [corner_point])

    bisector = _v_add(_v_scale(u, -1.0), v)
    if _v_norm(bisector) <= _EPS:
        return _WireCorner(corner_point, corner_point, [corner_point])
    bisector = _v_normalize(bisector)

    sin_half = sin(theta * 0.5)
    if abs(sin_half) <= _EPS:
        return _WireCorner(corner_point, corner_point, [corner_point])
    center_dist = radius_eff / sin_half
    center = _v_add(corner_point, _v_scale(bisector, center_dist))

    axis = _v_cross(u, v)
    if _v_norm(axis) <= _EPS:
        return _WireCorner(corner_point, corner_point, [corner_point])
    axis = _v_normalize(axis)

    ra = _v_sub(a, center)
    rb = _v_sub(b, center)
    if _v_norm(ra) <= _EPS or _v_norm(rb) <= _EPS:
        return _WireCorner(corner_point, corner_point, [corner_point])
    ra_u = _v_normalize(ra)
    rb_u = _v_normalize(rb)

    arc_angle = acos(_clamp(_v_dot(ra_u, rb_u), -1.0, 1.0))
    if _v_dot(axis, _v_cross(ra_u, rb_u)) < 0.0:
        arc_angle = -arc_angle
    if abs(arc_angle) <= _EPS:
        return _WireCorner(corner_point, corner_point, [corner_point])

    arc_points = sample_arc_3d(
        start_point=a,
        center=center,
        normal=axis,
        angle=arc_angle,
        segments=max(2, int(corner_segments)),
    )
    arc_points[0] = a
    arc_points[-1] = b
    return _WireCorner(a, b, arc_points)


def _build_wire_centerline(
    points: List[Vec3],
    *,
    closed_path: bool,
    corner_mode: str,
    corner_radius: float,
    corner_segments: int,
) -> List[Vec3]:
    if not closed_path:
        if len(points) < 2:
            raise ValueError("Wire path requires at least two points")
        if len(points) == 2:
            return list(points)

        out: List[Vec3] = []
        _append_distinct_path_point(out, points[0])
        for i in range(1, len(points) - 1):
            corner = _wire_corner_from_three_points(
                points[i - 1],
                points[i],
                points[i + 1],
                corner_mode=corner_mode,
                corner_radius=corner_radius,
                corner_segments=corner_segments,
            )
            _append_distinct_path_point(out, corner.incoming_end)
            for point in corner.bridge[1:]:
                _append_distinct_path_point(out, point)
        _append_distinct_path_point(out, points[-1])
        return out

    ring = points[:-1]
    if len(ring) < 3:
        raise ValueError("Closed path requires at least three distinct points")

    corners: List[_WireCorner] = []
    n = len(ring)
    for i in range(n):
        corners.append(
            _wire_corner_from_three_points(
                ring[(i - 1) % n],
                ring[i],
                ring[(i + 1) % n],
                corner_mode=corner_mode,
                corner_radius=corner_radius,
                corner_segments=corner_segments,
            )
        )

    out: List[Vec3] = []
    _append_distinct_path_point(out, corners[0].outgoing_start)
    for i in range(n):
        j = (i + 1) % n
        corner = corners[j]
        _append_distinct_path_point(out, corner.incoming_end)
        for point in corner.bridge[1:]:
            _append_distinct_path_point(out, point)
    if _v_norm(_v_sub(out[0], out[-1])) > _EPS:
        out.append(out[0])
    else:
        out[-1] = out[0]
    return out


def _wire_circle_profile(radius: float, radial_segments: int) -> List[Vec2]:
    return [
        (
            float(radius) * cos(2.0 * pi * i / radial_segments),
            float(radius) * sin(2.0 * pi * i / radial_segments),
        )
        for i in range(radial_segments)
    ]


def _rpy_from_z_axis(direction: Vec3) -> Vec3:
    d = _v_normalize(direction)
    yaw = atan2(d[1], d[0])
    pitch = atan2(sqrt(d[0] * d[0] + d[1] * d[1]), d[2])
    return (0.0, pitch, yaw)


class PipeGeometry(MeshGeometry):
    """
    Sweep a 2D profile along a 3D path using transported local frames.

    Unlike `SweepGeometry`, profile orientation follows the path tangent,
    which is important for wire-like and tube-like parts.
    """

    def __init__(
        self,
        profile: Iterable[Tuple[float, float]],
        path: Iterable[Tuple[float, float, float]],
        *,
        cap: bool = False,
        closed: bool = True,
        path_closed: bool = False,
        up_hint: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    ):
        super().__init__()
        raw_points = _profile_points_2d(profile)
        points = _ensure_ccw(raw_points) if closed else raw_points
        if not closed:
            cap = False
        path_points = [(float(x), float(y), float(z)) for (x, y, z) in path]
        path_points = _dedupe_path_points(path_points)
        if len(path_points) < 2:
            raise ValueError("Pipe requires at least two distinct path points")
        if path_closed:
            if _v_norm(_v_sub(path_points[0], path_points[-1])) > _EPS:
                path_points.append(path_points[0])
            cap = False

        tangents = _compute_path_tangents(path_points)
        n0, b0 = _initial_frame(
            tangents[0], (float(up_hint[0]), float(up_hint[1]), float(up_hint[2]))
        )
        normals: List[Vec3] = [n0]
        binormals: List[Vec3] = [b0]
        for i in range(1, len(path_points)):
            t = tangents[i]
            prev_n = normals[-1]
            prev_b = binormals[-1]
            # Parallel-transport-ish update: keep normal close to previous frame
            # while orthogonalizing against the new tangent.
            n = _v_sub(prev_n, _v_scale(t, _v_dot(prev_n, t)))
            if _v_norm(n) <= _EPS:
                n = _v_cross(prev_b, t)
            if _v_norm(n) <= _EPS:
                fallback = (0.0, 1.0, 0.0) if abs(t[1]) < 0.95 else (1.0, 0.0, 0.0)
                n = _v_cross(fallback, t)
            n = _v_normalize(n)
            b = _v_normalize(_v_cross(t, n))
            normals.append(n)
            binormals.append(b)
        if path_closed:
            normals[-1] = normals[0]
            binormals[-1] = binormals[0]

        profiles: List[List[Vec3]] = []
        for i, p in enumerate(path_points):
            n = normals[i]
            b = binormals[i]
            ring: List[Vec3] = []
            for x, y in points:
                ring.append(
                    (
                        p[0] + x * n[0] + y * b[0],
                        p[1] + x * n[1] + y * b[1],
                        p[2] + x * n[2] + y * b[2],
                    )
                )
            profiles.append(ring)
        ring_count = len(points)
        if ring_count < 2:
            raise ValueError("Pipe profile must contain at least 2 points")

        ring_indices: List[List[int]] = []
        for ring in profiles:
            idxs: List[int] = []
            for x, y, z in ring:
                idxs.append(self.add_vertex(x, y, z))
            ring_indices.append(idxs)

        seg_count = ring_count if closed else (ring_count - 1)
        for i in range(len(ring_indices) - 1):
            r0 = ring_indices[i]
            r1 = ring_indices[i + 1]
            for j in range(seg_count):
                j2 = (j + 1) % ring_count
                a = r0[j]
                b = r0[j2]
                c = r1[j2]
                d = r1[j]
                self.add_face(a, b, c)
                self.add_face(a, c, d)

        if cap and closed and ring_count >= 3:
            first = profiles[0]
            last = profiles[-1]
            c0 = (
                sum(v[0] for v in first) / ring_count,
                sum(v[1] for v in first) / ring_count,
                sum(v[2] for v in first) / ring_count,
            )
            c1 = (
                sum(v[0] for v in last) / ring_count,
                sum(v[1] for v in last) / ring_count,
                sum(v[2] for v in last) / ring_count,
            )
            i0 = self.add_vertex(*c0)
            i1 = self.add_vertex(*c1)
            r0 = ring_indices[0]
            r1 = ring_indices[-1]
            for j in range(ring_count):
                j2 = (j + 1) % ring_count
                self.add_face(i0, r0[j2], r0[j])
                self.add_face(i1, r1[j], r1[j2])


class ArcPipeGeometry(MeshGeometry):
    """
    Advanced compatibility helper: profile swept over a circular 3D arc.

    Prefer `sample_arc_3d(...)` + `PipeGeometry(...)` or the higher-level wire
    helpers for new code.
    """

    def __init__(
        self,
        profile: Iterable[Tuple[float, float]],
        *,
        start_point: Vec3,
        center: Vec3,
        normal: Vec3,
        angle: float,
        arc_segments: int = 20,
        cap: bool = False,
        closed: bool = True,
        up_hint: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    ):
        super().__init__()
        path = sample_arc_3d(
            start_point=start_point,
            center=center,
            normal=normal,
            angle=angle,
            segments=arc_segments,
        )
        self.merge(PipeGeometry(profile, path, cap=cap, closed=closed, up_hint=up_hint))


class WirePolylineGeometry(MeshGeometry):
    """
    Compatibility class-form wire primitive built from centerline points.

    Prefer `wire_from_points(...)` for new code. This class remains available
    when the explicit class form is useful.
    """

    def __init__(
        self,
        points: Iterable[Tuple[float, float, float]],
        *,
        radius: float,
        radial_segments: int = 16,
        closed_path: bool = False,
        cap_ends: bool = False,
        corner_mode: str = "fillet",
        corner_radius: float = 0.0,
        corner_segments: int = 8,
        up_hint: Tuple[float, float, float] = (0.0, 0.0, 1.0),
        min_segment_length: float = 1e-6,
    ):
        super().__init__()
        radius = float(radius)
        radial_segments = int(radial_segments)
        closed_path = bool(closed_path)
        corner_mode = str(corner_mode).strip().lower()
        corner_radius = float(corner_radius)
        corner_segments = int(corner_segments)
        up_hint_v = (float(up_hint[0]), float(up_hint[1]), float(up_hint[2]))
        min_segment_length = float(min_segment_length)

        if radius <= 0.0:
            raise ValueError("radius must be > 0")
        if radial_segments < 6:
            raise ValueError("radial_segments must be >= 6")
        if corner_mode not in {"fillet", "miter", "bevel"}:
            raise ValueError("corner_mode must be one of: fillet, miter, bevel")
        if corner_radius < 0.0:
            raise ValueError("corner_radius must be >= 0")
        if corner_mode == "fillet" and corner_radius > 0.0 and corner_segments < 2:
            raise ValueError("corner_segments must be >= 2 when fillets are active")
        if _v_norm(up_hint_v) <= _EPS:
            raise ValueError("up_hint must be non-zero")
        if min_segment_length <= 0.0:
            raise ValueError("min_segment_length must be > 0")

        preprocessed = _preprocess_wire_polyline_points(
            points,
            min_segment_length=min_segment_length,
            closed_path=closed_path,
        )
        centerline = _build_wire_centerline(
            preprocessed,
            closed_path=closed_path,
            corner_mode=corner_mode,
            corner_radius=corner_radius,
            corner_segments=corner_segments,
        )
        centerline = _dedupe_path_points(centerline)
        if len(centerline) < 2:
            raise ValueError("Too few distinct points after corner preprocessing")

        profile = _wire_circle_profile(radius, radial_segments)
        self.merge(
            PipeGeometry(
                profile,
                centerline,
                cap=bool(cap_ends and not closed_path),
                closed=True,
                path_closed=closed_path,
                up_hint=up_hint_v,
            )
        )


def wire_from_points(
    points: Iterable[Tuple[float, float, float]],
    *,
    radius: float,
    radial_segments: int = 16,
    closed_path: bool = False,
    cap_ends: bool = False,
    corner_mode: str = "fillet",
    corner_radius: float = 0.0,
    corner_segments: int = 8,
    up_hint: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    min_segment_length: float = 1e-6,
) -> MeshGeometry:
    """Build one tube/wire mesh from a centerline path and radius."""
    return WirePolylineGeometry(
        points=points,
        radius=radius,
        radial_segments=radial_segments,
        closed_path=closed_path,
        cap_ends=cap_ends,
        corner_mode=corner_mode,
        corner_radius=corner_radius,
        corner_segments=corner_segments,
        up_hint=up_hint,
        min_segment_length=min_segment_length,
    )


def _sample_supported_spline_path(
    points: Iterable[Vec3],
    *,
    spline: str,
    samples_per_segment: int,
    closed_spline: bool,
    alpha: float,
    min_segment_length: float,
) -> List[Vec3]:
    spline_key = str(spline or "catmull_rom").strip().lower().replace("-", "_")
    if spline_key in {"catmullrom", "catmull_rom"}:
        sampled = sample_catmull_rom_spline_3d(
            list(points),
            samples_per_segment=int(samples_per_segment),
            closed=bool(closed_spline),
            alpha=float(alpha),
        )
    elif spline_key in {"bezier", "cubic_bezier", "cubicbezier"}:
        sampled = sample_cubic_bezier_spline_3d(
            list(points),
            samples_per_segment=int(samples_per_segment),
        )
        if bool(closed_spline) and _v_norm(_v_sub(sampled[0], sampled[-1])) > max(
            float(min_segment_length), _EPS
        ):
            raise ValueError(
                "closed_spline=True with spline='bezier' requires the sampled "
                "Bezier chain to end where it starts"
            )
    else:
        raise ValueError("spline must be one of: 'catmull_rom', 'bezier'")

    return _preprocess_wire_polyline_points(
        sampled,
        min_segment_length=float(min_segment_length),
        closed_path=bool(closed_spline),
    )


def tube_from_spline_points(
    points: Iterable[Vec3],
    *,
    radius: float,
    samples_per_segment: int = 12,
    closed_spline: bool = False,
    spline: str = "catmull_rom",
    alpha: float = 0.5,
    radial_segments: int = 16,
    cap_ends: bool = True,
    up_hint: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    min_segment_length: float = 1e-6,
) -> MeshGeometry:
    """
    Fit a spline through points, then build a circular tube along that path.

    This is the default "click points, fit a nice handle/tube" helper.
    Supported spline families: ``catmull_rom`` and chained cubic ``bezier``.
    """
    centerline = _sample_supported_spline_path(
        points,
        spline=spline,
        samples_per_segment=samples_per_segment,
        closed_spline=closed_spline,
        alpha=alpha,
        min_segment_length=min_segment_length,
    )
    return wire_from_points(
        centerline,
        radius=float(radius),
        radial_segments=int(radial_segments),
        closed_path=bool(closed_spline),
        cap_ends=bool(cap_ends),
        corner_mode="miter",
        up_hint=up_hint,
        min_segment_length=min_segment_length,
    )


def sweep_profile_along_spline(
    points: Iterable[Vec3],
    *,
    profile: Iterable[Vec2],
    samples_per_segment: int = 12,
    closed_spline: bool = False,
    spline: str = "catmull_rom",
    alpha: float = 0.5,
    cap_profile: bool = True,
    up_hint: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    min_segment_length: float = 1e-6,
) -> MeshGeometry:
    """
    Fit a spline through points, then sweep a 2D profile along the sampled path.

    The profile is treated as a closed outline. Use `tube_from_spline_points(...)`
    for the common circular-tube case. Supported spline families:
    ``catmull_rom`` and chained cubic ``bezier``.
    """
    centerline = _sample_supported_spline_path(
        points,
        spline=spline,
        samples_per_segment=samples_per_segment,
        closed_spline=closed_spline,
        alpha=alpha,
        min_segment_length=min_segment_length,
    )
    return PipeGeometry(
        profile=profile,
        path=centerline,
        cap=bool(cap_profile and not closed_spline),
        closed=True,
        path_closed=bool(closed_spline),
        up_hint=up_hint,
    )


def _vec3_quant_key(point: Vec3, *, tol: float) -> Tuple[int, int, int]:
    scale = 1.0 / max(float(tol), _EPS)
    return (
        int(round(point[0] * scale)),
        int(round(point[1] * scale)),
        int(round(point[2] * scale)),
    )


def _coerce_tube_network_paths(paths: Iterable[Iterable[Vec3]]) -> List[List[Vec3]]:
    out: List[List[Vec3]] = []
    for path in paths:
        pts = [(float(x), float(y), float(z)) for (x, y, z) in path]
        if len(pts) < 2:
            raise ValueError(
                "tube_network_from_paths requires each path to contain at least two points"
            )
        out.append(pts)
    if not out:
        raise ValueError("tube_network_from_paths requires at least one path")
    return out


def _is_closed_network_path(path: Sequence[Vec3], *, tol: float) -> bool:
    return len(path) >= 3 and _v_norm(_v_sub(path[0], path[-1])) <= max(float(tol), _EPS)


def _collect_shared_network_nodes(paths: Sequence[Sequence[Vec3]], *, tol: float) -> List[Vec3]:
    counts: dict[Tuple[int, int, int], int] = {}
    canonical: dict[Tuple[int, int, int], Vec3] = {}
    for path in paths:
        seen: set[Tuple[int, int, int]] = set()
        for point in path:
            key = _vec3_quant_key(point, tol=tol)
            canonical.setdefault(key, (float(point[0]), float(point[1]), float(point[2])))
            seen.add(key)
        for key in seen:
            counts[key] = counts.get(key, 0) + 1
    return [canonical[key] for key, count in counts.items() if count > 1]


def _segment_cylinder_geometry(
    start: Vec3,
    end: Vec3,
    *,
    radius: float,
    radial_segments: int,
) -> Optional[MeshGeometry]:
    segment = _v_sub(end, start)
    length = _v_norm(segment)
    if length <= _EPS:
        return None
    mid = _v_lerp(start, end, 0.5)
    _roll, pitch, yaw = _rpy_from_z_axis(segment)
    return (
        CylinderGeometry(
            radius=float(radius),
            height=length,
            radial_segments=max(6, int(radial_segments)),
            closed=True,
        )
        .rotate_y(pitch)
        .rotate_z(yaw)
        .translate(*mid)
    )


def _tube_network_visual_mesh_from_paths(
    path_list: Sequence[Sequence[Vec3]],
    *,
    radius: float,
    radial_segments: int,
    cap_ends: bool,
    corner_mode: str,
    corner_radius: float,
    corner_segments: int,
    up_hint: Tuple[float, float, float],
    min_segment_length: float,
    shared_node_radius: float,
) -> MeshGeometry:
    out = MeshGeometry()
    for path in path_list:
        closed_path = _is_closed_network_path(path, tol=min_segment_length)
        out.merge(
            wire_from_points(
                path,
                radius=radius,
                radial_segments=radial_segments,
                closed_path=closed_path,
                cap_ends=cap_ends,
                corner_mode=corner_mode,
                corner_radius=corner_radius,
                corner_segments=corner_segments,
                up_hint=up_hint,
                min_segment_length=min_segment_length,
            )
        )

    if shared_node_radius > 0.0:
        width_segments = max(12, int(radial_segments))
        height_segments = max(8, int(radial_segments) // 2)
        for point in _collect_shared_network_nodes(path_list, tol=min_segment_length):
            out.merge(
                SphereGeometry(
                    radius=shared_node_radius,
                    width_segments=width_segments,
                    height_segments=height_segments,
                ).translate(*point)
            )
    return out


def tube_network_from_paths(
    paths: Iterable[Iterable[Vec3]],
    *,
    radius: float,
    radial_segments: int = 16,
    cap_ends: bool = True,
    corner_mode: str = "fillet",
    corner_radius: float = 0.0,
    corner_segments: int = 8,
    up_hint: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    min_segment_length: float = 1e-6,
    shared_node_radius: Optional[float] = None,
) -> MeshGeometry:
    """
    Build a tubular frame/network from multiple centerline paths.

    This helper aims to return a watertight solid by boolean-unioning closed
    segment cylinders and optional node spheres. If the boolean backend is not
    available, it falls back to the older merge-based visual mesh construction.
    """
    radius = float(radius)
    node_radius = radius if shared_node_radius is None else float(shared_node_radius)
    tol = max(float(min_segment_length), _EPS)
    path_list = _coerce_tube_network_paths(paths)

    if radius <= 0.0:
        raise ValueError("radius must be > 0")
    if node_radius < 0.0:
        raise ValueError("shared_node_radius must be >= 0")

    solids: List[MeshGeometry] = []
    for path in path_list:
        closed_path = _is_closed_network_path(path, tol=tol)
        preprocessed = _preprocess_wire_polyline_points(
            path,
            min_segment_length=min_segment_length,
            closed_path=closed_path,
        )
        centerline = _build_wire_centerline(
            preprocessed,
            closed_path=closed_path,
            corner_mode=corner_mode,
            corner_radius=corner_radius,
            corner_segments=corner_segments,
        )
        centerline = _dedupe_path_points(centerline)
        for i in range(len(centerline) - 1):
            segment_geom = _segment_cylinder_geometry(
                centerline[i],
                centerline[i + 1],
                radius=radius,
                radial_segments=radial_segments,
            )
            if segment_geom is not None:
                solids.append(segment_geom)

    if node_radius > 0.0 and cap_ends:
        width_segments = max(12, int(radial_segments))
        height_segments = max(8, int(radial_segments) // 2)
        node_keys: set[Tuple[int, int, int]] = set()
        for path in path_list:
            for point in path:
                node_keys.add(_vec3_quant_key(point, tol=tol))
        canonical = {
            _vec3_quant_key(point, tol=tol): (float(point[0]), float(point[1]), float(point[2]))
            for path in path_list
            for point in path
        }
        for key in sorted(node_keys):
            solids.append(
                SphereGeometry(
                    radius=node_radius,
                    width_segments=width_segments,
                    height_segments=height_segments,
                ).translate(*canonical[key])
            )

    if not solids:
        raise ValueError("tube_network_from_paths produced no solid segments")

    try:
        out = _boolean_union_many(solids)
    except Exception as exc:
        if not _is_expected_boolean_fallback_error(exc):
            raise
        logger.warning(
            "tube_network_from_paths falling back to visual mesh after boolean union failure: %s: %s",
            type(exc).__name__,
            exc,
        )
        out = _tube_network_visual_mesh_from_paths(
            path_list,
            radius=radius,
            radial_segments=radial_segments,
            cap_ends=cap_ends,
            corner_mode=corner_mode,
            corner_radius=corner_radius,
            corner_segments=corner_segments,
            up_hint=up_hint,
            min_segment_length=min_segment_length,
            shared_node_radius=node_radius if cap_ends else 0.0,
        )
    return out


def cut_opening_on_face(
    shell_geometry: MeshGeometry,
    *,
    face: str,
    opening_profile: Iterable[Tuple[float, float]],
    depth: float,
    offset: Tuple[float, float] = (0.0, 0.0),
    taper: float = 0.0,
) -> MeshGeometry:
    """
    Add an opening "throat" on a mesh AABB face.

    This helper does not perform boolean subtraction. It creates the internal
    side walls for a recessed opening and merges them into ``shell_geometry``.
    It works best when the target face is already open (shell-like models).
    """

    if not isinstance(shell_geometry, MeshGeometry):
        raise TypeError("shell_geometry must be MeshGeometry")
    if not shell_geometry.vertices:
        raise ValueError("shell_geometry has no vertices")

    d = float(depth)
    if d <= 0:
        raise ValueError("depth must be positive")

    f = (face or "").strip().lower()
    if len(f) != 2 or f[0] not in "+-" or f[1] not in "xyz":
        raise ValueError("face must be one of: '+x', '-x', '+y', '-y', '+z', '-z'")

    points = _ensure_ccw(_profile_points_2d(opening_profile))
    ox = float(offset[0])
    oy = float(offset[1])
    taper = float(taper)
    if abs(taper) >= 0.95:
        raise ValueError("abs(taper) must be < 0.95")

    center = _polygon_centroid(points)
    scale = 1.0 - taper
    inner_points = [
        (center[0] + (x - center[0]) * scale, center[1] + (y - center[1]) * scale)
        for (x, y) in points
    ]

    xs = [v[0] for v in shell_geometry.vertices]
    ys = [v[1] for v in shell_geometry.vertices]
    zs = [v[2] for v in shell_geometry.vertices]
    bounds = {
        "x": (min(xs), max(xs)),
        "y": (min(ys), max(ys)),
        "z": (min(zs), max(zs)),
    }

    axis = f[1]
    sign = 1.0 if f[0] == "+" else -1.0
    face_plane = bounds[axis][1] if sign > 0 else bounds[axis][0]

    def map_uv(u: float, v: float, depth_local: float) -> Vec3:
        inward = -sign * depth_local
        if axis == "x":
            return (face_plane + inward, u + ox, v + oy)
        if axis == "y":
            return (u + ox, face_plane + inward, v + oy)
        return (u + ox, v + oy, face_plane + inward)

    p0 = [map_uv(u, v, 0.0) for (u, v) in points]
    p1 = [map_uv(u, v, d) for (u, v) in inner_points]
    shell_geometry.merge(LoftGeometry([p0, p1], cap=False, closed=True))
    return shell_geometry


def _manifold_from_geometry(geometry: MeshGeometry, *, name: str = "geometry"):
    if not isinstance(geometry, MeshGeometry):
        raise TypeError(f"{name} must be MeshGeometry")
    manifold_source = getattr(geometry, "_manifold_source", None)
    if manifold_source is not None:
        return manifold_source

    verts = np.asarray(geometry.vertices, dtype=np.float32)
    faces = np.asarray(geometry.faces, dtype=np.uint32)
    if verts.size == 0 or faces.size == 0:
        return _m3d.Manifold()
    if verts.ndim != 2 or verts.shape[1] != 3:
        raise ValueError(f"{name} vertices must have shape (N, 3)")
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError(f"{name} faces must have shape (M, 3)")

    mesh = _m3d.Mesh(verts, faces)
    manifold = _m3d.Manifold(mesh)
    status = manifold.status()
    if status != _m3d.Error.NoError:
        raise ValueError(f"{name} is not a valid manifold solid for boolean ops (status={status})")
    return manifold


def _quantize_scalar(value: float, *, step: float) -> int:
    return int(round(float(value) / float(step)))


def _canonical_plane(
    normal: Vec3, offset: float, *, step: float
) -> Tuple[Tuple[int, int, int, int], Vec3, float]:
    n = _v_normalize(normal)
    if n[2] < -_EPS or (
        abs(n[2]) <= _EPS and (n[1] < -_EPS or (abs(n[1]) <= _EPS and n[0] < -_EPS))
    ):
        n = (-n[0], -n[1], -n[2])
        offset = -offset
    key = (
        _quantize_scalar(n[0], step=step),
        _quantize_scalar(n[1], step=step),
        _quantize_scalar(n[2], step=step),
        _quantize_scalar(offset, step=step),
    )
    return key, n, float(offset)


def _plane_basis(normal: Vec3) -> Tuple[Vec3, Vec3]:
    reference = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.8 else (0.0, 1.0, 0.0)
    u_axis = _v_normalize(_v_cross(reference, normal))
    v_axis = _v_cross(normal, u_axis)
    return u_axis, v_axis


def _project_point_to_plane(point: Vec3, origin: Vec3, u_axis: Vec3, v_axis: Vec3) -> Vec2:
    delta = _v_sub(point, origin)
    return (_v_dot(delta, u_axis), _v_dot(delta, v_axis))


def _lift_point_from_plane(point: Vec2, origin: Vec3, u_axis: Vec3, v_axis: Vec3) -> Vec3:
    return _v_add(origin, _v_add(_v_scale(u_axis, point[0]), _v_scale(v_axis, point[1])))


def _point_inside_manifold(manifold, point: Vec3, *, probe_size: float) -> bool:
    probe = _m3d.Manifold.cube((probe_size, probe_size, probe_size), center=True).translate(point)
    return not (manifold ^ probe).is_empty()


def _geometry_from_manifold(manifold) -> MeshGeometry:
    if manifold is None or manifold.is_empty():
        return MeshGeometry()

    out_mesh = manifold.to_mesh()
    vp = np.asarray(out_mesh.vert_properties, dtype=np.float64)
    tri = np.asarray(out_mesh.tri_verts, dtype=np.int64)
    if vp.size == 0 or tri.size == 0:
        return MeshGeometry()

    plane_step = max(_OBJ_QUANT_STEP, float(manifold.get_tolerance()) * 4.0)
    grouped_triangles: dict[Tuple[int, int, int, int], List[Tuple[Vec3, Vec3, Vec3]]] = {}
    grouped_normals: dict[Tuple[int, int, int, int], Vec3] = {}
    grouped_offsets: dict[Tuple[int, int, int, int], float] = {}

    for face in tri:
        points = tuple((float(vp[idx][0]), float(vp[idx][1]), float(vp[idx][2])) for idx in face)
        normal = _v_cross(_v_sub(points[1], points[0]), _v_sub(points[2], points[0]))
        if _v_norm(normal) <= _EPS:
            continue
        plane_offset = _v_dot(_v_normalize(normal), points[0])
        key, plane_normal, canonical_offset = _canonical_plane(
            normal, plane_offset, step=plane_step
        )
        grouped_triangles.setdefault(key, []).append(points)
        grouped_normals.setdefault(key, plane_normal)
        grouped_offsets.setdefault(key, canonical_offset)

    if not grouped_triangles:
        return MeshGeometry()

    bounds = manifold.bounding_box()
    bbox_diag = sqrt(
        (float(bounds[3]) - float(bounds[0])) ** 2
        + (float(bounds[4]) - float(bounds[1])) ** 2
        + (float(bounds[5]) - float(bounds[2])) ** 2
    )
    sample_offset = max(
        float(manifold.get_tolerance()) * 12.0, bbox_diag * 2.0e-4, _OBJ_QUANT_STEP * 32.0
    )
    probe_size = max(sample_offset * 0.1, _OBJ_QUANT_STEP * 8.0)

    output_vertices: List[Vec3] = []
    output_faces: List[Face] = []
    vertex_index: dict[Tuple[int, int, int], int] = {}

    def add_output_vertex(point: Vec3) -> int:
        key = (
            _quantize_scalar(point[0], step=_OBJ_QUANT_STEP),
            _quantize_scalar(point[1], step=_OBJ_QUANT_STEP),
            _quantize_scalar(point[2], step=_OBJ_QUANT_STEP),
        )
        idx = vertex_index.get(key)
        if idx is not None:
            return idx
        idx = len(output_vertices)
        vertex_index[key] = idx
        output_vertices.append(point)
        return idx

    for key, triangles in grouped_triangles.items():
        plane_normal = grouped_normals[key]
        plane_origin = _v_scale(plane_normal, grouped_offsets[key])
        u_axis, v_axis = _plane_basis(plane_normal)

        projected_triangles: List[List[Vec2]] = []
        for triangle in triangles:
            projected = [
                _project_point_to_plane(point, plane_origin, u_axis, v_axis) for point in triangle
            ]
            if _polygon_area(projected) < 0.0:
                projected = [projected[0], projected[2], projected[1]]
            projected_triangles.append(projected)

        cross_section = _m3d.CrossSection(projected_triangles, _m3d.FillRule.Positive)
        cross_section = cross_section.simplify(plane_step * 0.25)

        for piece in cross_section.decompose():
            contours = [
                [(float(point[0]), float(point[1])) for point in contour]
                for contour in piece.to_polygons()
                if len(contour) >= 3
            ]
            if not contours:
                continue

            outer = max(
                (contour for contour in contours if _polygon_area(contour) > 0.0),
                key=lambda contour: abs(_polygon_area(contour)),
                default=None,
            )
            if outer is None:
                continue

            holes = [
                contour
                for contour in contours
                if contour is not outer and _polygon_area(contour) < 0.0
            ]
            flat_ring, piece_triangles = _triangulate_polygon_with_holes(outer, holes)
            if not piece_triangles:
                continue

            sample_face = piece_triangles[0]
            sample_points = [
                _lift_point_from_plane(flat_ring[idx], plane_origin, u_axis, v_axis)
                for idx in sample_face
            ]
            sample_centroid = (
                (sample_points[0][0] + sample_points[1][0] + sample_points[2][0]) / 3.0,
                (sample_points[0][1] + sample_points[1][1] + sample_points[2][1]) / 3.0,
                (sample_points[0][2] + sample_points[1][2] + sample_points[2][2]) / 3.0,
            )
            plus_sample = _v_add(sample_centroid, _v_scale(plane_normal, sample_offset))
            minus_sample = _v_add(sample_centroid, _v_scale(plane_normal, -sample_offset))
            inside_plus = _point_inside_manifold(manifold, plus_sample, probe_size=probe_size)
            inside_minus = _point_inside_manifold(manifold, minus_sample, probe_size=probe_size)
            if inside_plus == inside_minus:
                continue

            reverse = inside_plus and not inside_minus
            output_indices = [
                add_output_vertex(_lift_point_from_plane(point, plane_origin, u_axis, v_axis))
                for point in flat_ring
            ]
            for a, b, c in piece_triangles:
                if reverse:
                    output_faces.append((output_indices[a], output_indices[c], output_indices[b]))
                else:
                    output_faces.append((output_indices[a], output_indices[b], output_indices[c]))

    geometry = MeshGeometry(vertices=output_vertices, faces=output_faces)
    _set_manifold_provenance(geometry, manifold)
    return geometry


def _is_expected_boolean_fallback_error(exc: BaseException) -> bool:
    if isinstance(exc, (ValueError, RuntimeError)):
        return True
    module_name = type(exc).__module__.lower()
    return module_name.startswith("manifold")


def boolean_union(a: MeshGeometry, b: MeshGeometry) -> MeshGeometry:
    """
    Compute a solid boolean union of two meshes.

    Both inputs must be manifold solids. This is an MVP wrapper for clean geometry.
    """
    ma = _manifold_from_geometry(a, name="a")
    mb = _manifold_from_geometry(b, name="b")
    return _geometry_from_manifold(ma + mb)


def _boolean_union_many(geometries: Sequence[MeshGeometry]) -> MeshGeometry:
    combined = _m3d.Manifold()
    for idx, geometry in enumerate(geometries):
        combined = combined + _manifold_from_geometry(geometry, name=f"geometry[{idx}]")
    return _geometry_from_manifold(combined)


def boolean_difference(a: MeshGeometry, b: MeshGeometry) -> MeshGeometry:
    """
    Compute a solid boolean difference: ``a - b``.

    Both inputs must be manifold solids. This is an MVP wrapper for clean geometry.
    """
    ma = _manifold_from_geometry(a, name="a")
    mb = _manifold_from_geometry(b, name="b")
    return _geometry_from_manifold(ma - mb)


def boolean_intersection(a: MeshGeometry, b: MeshGeometry) -> MeshGeometry:
    """
    Compute a solid boolean intersection of two meshes.

    Both inputs must be manifold solids. This is an MVP wrapper for clean geometry.
    """
    ma = _manifold_from_geometry(a, name="a")
    mb = _manifold_from_geometry(b, name="b")
    return _geometry_from_manifold(ma ^ mb)


def mesh_from_geometry(
    geometry: MeshGeometry,
    name: Union[str, os.PathLike[str]],
) -> Mesh:
    name_s = os.fspath(name)
    if _looks_like_legacy_mesh_filename(name_s):
        geometry.save_obj(name_s)
        resolved_path = Path(name_s).resolve()
        return Mesh(
            filename=_export_friendly_mesh_filename(name_s),
            name=resolved_path.stem,
            source_geometry=_primitive_source_geometry(geometry),
            source_transform=_primitive_source_transform(geometry),
            materialized_path=resolved_path.as_posix(),
        )

    session = get_active_asset_session(create_if_missing=True)
    if session is None:
        raise RuntimeError("Failed to create a managed asset session")
    info = session.register_mesh_text(name_s, geometry.to_obj())
    return Mesh(
        filename=info.ref,
        name=info.logical_name,
        source_geometry=_primitive_source_geometry(geometry),
        source_transform=_primitive_source_transform(geometry),
        materialized_path=info.path.as_posix(),
    )


def _looks_like_legacy_mesh_filename(value: str) -> bool:
    if not value:
        return False
    if value.startswith(("assets/meshes/", "meshes/")):
        return True
    try:
        path = Path(value)
    except Exception:
        return False
    if path.is_absolute():
        return True
    return len(path.parts) > 1


def _export_friendly_mesh_filename(filename: str) -> str:
    """
    Convert a disk path into a portable export filename when possible.

    Prefer canonical `assets/meshes/...` paths when the file lives under that subtree.
    Fall back to legacy `meshes/...` relative paths only when the file was actually written there.
    Otherwise, return the input unchanged.
    """

    if not isinstance(filename, str) or not filename:
        return filename

    normalized = filename.replace("\\", "/")
    if normalized.startswith("assets/meshes/"):
        return normalized
    if normalized.startswith("meshes/"):
        return normalized

    try:
        path = Path(filename)
    except Exception:
        return filename

    parts = list(path.parts)
    asset_meshes_indices = [
        i for i in range(len(parts) - 1) if parts[i] == "assets" and parts[i + 1] == "meshes"
    ]
    if asset_meshes_indices:
        i = asset_meshes_indices[-1]
        return Path(*parts[i:]).as_posix()

    meshes_indices = [i for i, p in enumerate(parts) if p == "meshes"]
    if not meshes_indices:
        return filename

    i = meshes_indices[-1]
    rel = Path(*parts[i:]).as_posix()
    return rel
