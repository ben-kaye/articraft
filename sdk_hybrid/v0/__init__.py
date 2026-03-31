from .articulated_object import ArticulatedObject
from .assets import mesh_from_input
from .cadquery import (
    CadQueryMeshExport,
    cadquery_local_aabb,
    export_cadquery_components,
    export_cadquery_mesh,
    mesh_components_from_cadquery,
    mesh_from_cadquery,
    tessellate_cadquery,
)
from .errors import SDKError, ValidationError
from .placement import (
    SurfaceFrame,
    SurfaceWrapMapping,
    align_centers,
    part_local_aabb,
    place_on_face,
    place_on_face_uv,
    place_on_surface,
    proud_for_flush_mount,
    surface_frame,
    wrap_mesh_onto_surface,
    wrap_profile_onto_surface,
)
from .testing import TestContext, TestFailure, TestReport
from .types import (
    Articulation,
    ArticulationType,
    Box,
    Cylinder,
    Inertia,
    Inertial,
    Material,
    Mesh,
    MotionLimits,
    MotionProperties,
    Origin,
    Part,
    Sphere,
    Visual,
)

_GEAR_EXPORTS = {
    "GearBase",
    "SpurGear",
    "HerringboneGear",
    "RingGear",
    "HerringboneRingGear",
    "PlanetaryGearset",
    "HerringbonePlanetaryGearset",
    "BevelGear",
    "BevelGearPair",
    "RackGear",
    "HerringboneRackGear",
    "Worm",
    "CrossedHelicalGear",
    "CrossedGearPair",
    "HyperbolicGear",
    "HyperbolicGearPair",
    "gear",
    "addGear",
}

Link = Part
Joint = Articulation
JointType = ArticulationType
Limit = MotionLimits
Dynamics = MotionProperties

__all__ = [
    "SDKError",
    "ValidationError",
    "Link",
    "Joint",
    "JointType",
    "Limit",
    "Dynamics",
    "CadQueryMeshExport",
    "cadquery_local_aabb",
    "export_cadquery_components",
    "export_cadquery_mesh",
    "mesh_components_from_cadquery",
    "mesh_from_input",
    "tessellate_cadquery",
    "mesh_from_cadquery",
    "ArticulatedObject",
    "TestContext",
    "TestFailure",
    "TestReport",
    "SurfaceFrame",
    "SurfaceWrapMapping",
    "align_centers",
    "part_local_aabb",
    "place_on_face",
    "place_on_face_uv",
    "place_on_surface",
    "proud_for_flush_mount",
    "surface_frame",
    "wrap_profile_onto_surface",
    "wrap_mesh_onto_surface",
    "GearBase",
    "SpurGear",
    "HerringboneGear",
    "RingGear",
    "HerringboneRingGear",
    "PlanetaryGearset",
    "HerringbonePlanetaryGearset",
    "BevelGear",
    "BevelGearPair",
    "RackGear",
    "HerringboneRackGear",
    "Worm",
    "CrossedHelicalGear",
    "CrossedGearPair",
    "HyperbolicGear",
    "HyperbolicGearPair",
    "gear",
    "addGear",
    "Box",
    "Cylinder",
    "MotionProperties",
    "Inertia",
    "Inertial",
    "Articulation",
    "ArticulationType",
    "MotionLimits",
    "Material",
    "Mesh",
    "Origin",
    "Part",
    "Sphere",
    "Visual",
]


def __getattr__(name: str):
    if name in _GEAR_EXPORTS:
        from . import gears as _gears

        value = getattr(_gears, name)
        globals()[name] = value
        return value
    if name == "AssetContext":
        from .assets import AssetContext

        globals()[name] = AssetContext
        return AssetContext
    if name == "save_cadquery_obj":
        from .cadquery import save_cadquery_obj

        globals()[name] = save_cadquery_obj
        return save_cadquery_obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
