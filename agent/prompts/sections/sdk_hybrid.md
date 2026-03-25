<modeling>
GEOMETRY
- Import from `sdk_hybrid`, not `sdk`. Keep `build_object_model()` and `run_tests()` as top-level entry points.
- Use simple primitives when they match the form cleanly. Use CadQuery/hybrid geometry when visible shells, cavities, or curves need more shape freedom.
- Choose the simplest representation that faithfully captures each visible form. Use primitives when they match; use CadQuery/hybrid geometry when the real shape demands it.
- Model openings, cavities, and hollow structure explicitly. Never cap a visible opening with a solid placeholder.
- If the object is layered or nested, model each layer with clear visual separation.
- Hidden supports and internal structure can use simple primitives.
- Use realistic materials and restrained real-world colors.
- Author visual geometry only; do not author collision geometry in `sdk_hybrid`.
- `section_loft(...)`, `repair_loft(...)`, and `partition_shell(...)` are unavailable in `sdk_hybrid`.
- Preserve correct joint axes, origins, limits, and articulation behavior.
- For `REVOLUTE`/`PRISMATIC`: set `MotionLimits` with effort, velocity, lower, upper. For `CONTINUOUS`: effort and velocity only.

TESTING
- Use `sdk_hybrid.TestContext`, keep the scaffolded baseline check stack, return `ctx.report()`.
- Use the object-first pattern: resolve Part, Articulation, and named Visual objects once, then pass them to `ctx.expect_*` and `ctx.allow_*` helpers. See SDK docs for exact signatures.
- Prefer many small exact checks (`expect_contact`, `expect_gap`, `expect_overlap`, `expect_within`) over broad `warn_if_*` heuristics.
- Every part must be tested for: presence, connection to neighbors, correct placement. Every articulation must be tested at rest and operating poses. For continuous joints, use explicit sampled angles.
- When a `warn_if_*` sensor fires, investigate with `probe_model` before changing geometry or relaxing thresholds.
- When support or floating status is ambiguous, probe first, then encode the real invariant in tests.
- See SDK docs for deprecated helpers and current recommendations.
</modeling>
