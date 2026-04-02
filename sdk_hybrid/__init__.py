from .v0 import (
    AllowedOverlap,
    ArticulatedObject,
    Articulation,
    ArticulationType,
    Box,
    CadQueryMeshExport,
    Cylinder,
    Inertia,
    Inertial,
    Material,
    Mesh,
    MotionLimits,
    MotionProperties,
    Origin,
    Part,
    SDKError,
    Sphere,
    SurfaceFrame,
    SurfaceWrapMapping,
    TestContext,
    TestFailure,
    TestReport,
    ValidationError,
    Visual,
    align_centers,
    cadquery_local_aabb,
    export_cadquery_components,
    export_cadquery_mesh,
    mesh_components_from_cadquery,
    mesh_from_cadquery,
    mesh_from_input,
    part_local_aabb,
    place_on_face,
    place_on_face_uv,
    place_on_surface,
    proud_for_flush_mount,
    surface_frame,
    tessellate_cadquery,
    wrap_mesh_onto_surface,
    wrap_profile_onto_surface,
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

_HIDDEN_COMPAT_EXPORTS = {"AssetContext", "save_cadquery_obj"}

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
    "ArticulatedObject",
    "AllowedOverlap",
    "Part",
    "Articulation",
    "ArticulationType",
    "Origin",
    "Visual",
    "Material",
    "MotionLimits",
    "MotionProperties",
    "Inertial",
    "Inertia",
    "Box",
    "Cylinder",
    "Sphere",
    "Mesh",
    "CadQueryMeshExport",
    "cadquery_local_aabb",
    "export_cadquery_components",
    "export_cadquery_mesh",
    "mesh_components_from_cadquery",
    "mesh_from_input",
    "tessellate_cadquery",
    "mesh_from_cadquery",
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
]


def __getattr__(name: str):
    if name in _GEAR_EXPORTS or name in _HIDDEN_COMPAT_EXPORTS:
        from . import v0 as _v0

        value = getattr(_v0, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
