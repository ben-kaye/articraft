<modeling>
GEOMETRY
- Keep `build_object_model()` and `run_tests()` as top-level entry points.
- Choose the simplest representation that faithfully captures each visible form. Use primitives when they match; use lofts, sweeps, or booleans when the real shape demands it.
- Model openings, cavities, and hollow structure explicitly. Never cap a visible opening with a solid placeholder.
- If the object is layered or nested, model each layer with clear visual separation.
- Hidden supports and internal structure can use simple primitives.
- Use realistic materials and restrained real-world colors.
- Author visual geometry only; do not author collision geometry in `sdk`.
- Preserve correct joint axes, origins, limits, and articulation behavior.

TESTING
- Use `sdk.TestContext`, keep the scaffolded hard gates, return `ctx.report()`.
- Use the object-first pattern: resolve Part, Articulation, and named Visual objects once, then pass them to `ctx.expect_*` and `ctx.allow_*` helpers. See SDK docs for exact signatures.
- Prefer many small exact checks (`expect_contact`, `expect_gap`, `expect_overlap`, `expect_within`) over broad `warn_if_*` heuristics.
- Every part must be tested for: presence, connection to neighbors, correct placement. Every articulation must be tested at rest and operating poses.
- When a `warn_if_*` sensor fires, investigate with `probe_model` before changing geometry or relaxing thresholds.
- When support or floating status is ambiguous, probe first, then encode the real invariant in tests.
- See SDK docs for deprecated helpers and current recommendations.
</modeling>
