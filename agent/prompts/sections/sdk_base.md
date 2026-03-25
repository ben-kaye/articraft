<modeling>
GEOMETRY
- Keep `build_object_model()` and `run_tests()` as top-level entry points.
- Choose the SDK tool that best achieves a realistic result. Use primitives for truly boxy, cylindrical, planar, or otherwise simple forms; use lofts, sweeps, booleans, wires, or meshes when the real shape calls for them.
- Model openings, cavities, and hollow structure explicitly. Never cap a visible opening with a solid placeholder.
- If the object is layered or nested, model each layer with clear visual separation.
- Hidden supports and internal structure can use simple primitives.
- For mounted child parts whose position is defined by a parent surface, prefer placement helpers over hand-tuned `Origin(...)` coordinates.
- Use `place_on_surface(...)` by default for rigid mounts onto housings, shells, panels, pedals, feet, knobs, buttons, pads, brackets, and similar surface-mounted parts.
- Use `place_on_face(...)` or `place_on_face_uv(...)` only when the parent is truly box-like and the semantic reference is a specific face.
- Use `proud_for_flush_mount(...)` when a centered child should sit flush instead of half-embedded.
- Use realistic materials and restrained real-world colors.
- Author visual geometry only; do not author collision geometry in `sdk`.
- Preserve correct joint axes, origins, limits, and articulation behavior.

TESTING
- Use `sdk.TestContext`, keep the scaffolded baseline check stack, return `ctx.report()`.
- Use the object-first pattern: resolve Part, Articulation, and named Visual objects once, then pass them to `ctx.expect_*` and `ctx.allow_*` helpers. See SDK docs for exact signatures.
- Prefer many small exact checks (`expect_contact`, `expect_gap`, `expect_overlap`, `expect_within`) over broad `warn_if_*` heuristics.
- `fail_if_parts_overlap_*` and `ctx.allow_overlap(...)` mean real 3D interpenetration; `expect_overlap(...)` is a separate projected footprint check. If parts are nested but should remain clear, use `expect_within(...)`, `expect_gap(...)`, `expect_contact(...)`, and/or `expect_overlap(...)` instead of `allow_overlap(...)`.
- Every part must be tested for: presence, connection to neighbors, correct placement. Every articulation must be tested at rest and operating poses.
- When a `warn_if_*` sensor fires, investigate with `probe_model` before changing geometry or relaxing thresholds.
- When support or floating status is ambiguous, probe first, then encode the real invariant in tests.
- See SDK docs for deprecated helpers and current recommendations.
</modeling>
