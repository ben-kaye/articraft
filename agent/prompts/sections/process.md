<process>
PHASE 1 — PLAN
- Read the bound scaffold with the provider's read tool.
- Read the injected SDK docs for helper signatures and constraints.
- Think through the full part tree: list every part, how each connects to its parent, what articulates, what the dominant silhouette is, and what realistic proportions should be.
- Use `find_examples` for unfamiliar modeling or testing patterns. Treat returned code as inspiration only — adapt against current SDK docs, do not copy verbatim.

PHASE 2 — SCAFFOLD
- Build the part tree with rough placeholder geometry and all articulations.
- Get this skeleton to compile clean with every part attached and every joint correctly oriented.
- Write initial tests: assert each part exists, key parts are connected (not floating), and articulations move on correct axes.

PHASE 3 — BUILD INCREMENTALLY
- Implement geometry one part or subassembly at a time. Do NOT write all geometry in one giant edit.
- The harness automatically compiles and runs tests after every successful edit. You will receive `<compile_signals>` feedback — you do not need to request compilation separately.
- Fix issues from compile feedback before moving to the next part.
- Write tests as you build: assert placement, contact with neighbors, and proportions for each new part.
- When a test fails or geometry looks wrong, use `probe_model` to diagnose before editing blindly.
- Use `probe_model` for geometry inspection and debugging; use `run_tests()` for persistent regression checks that survive across turns.
- Probe in the object-first style: resolve `part(...)`, `joint(...)`, `visual(...)` locals once, then pass them into probe reports.
- Work in this order: dominant silhouette → major openings/cavities → nested layers → secondary detail → articulation refinement.

PHASE 4 — VERIFY AND REFINE
- Explicitly check the three hard requirements:
  - Floating parts: use `find_floating_parts(...)`, `mount_report(...)`, `nearest_neighbors(...)`.
  - Overlaps: use `overlap_report(...)`, `pair_report(...)`, `find_clearance_risks(...)`.
  - Proportions: use `summary(...)`, `dims(...)`, `projection(...)`, `layout_report(...)`.
- Test articulation at multiple poses: `pose(...)`, `sample_poses(...)`.
- If geometry reads as placeholder despite passing tests, rewrite it from intent — do not preserve passing placeholders.

REPAIR RULES
- When you receive `<compile_signals>`, read `<summary>` first to understand the overall status.
- Treat `<failures>` as blocking, `<warnings>` as design evidence, `<notes>` as context.
- Classify before patching: local bug, wrong representation, wrong composition, or wrong proportions.
- If the same failure persists across 2 repair turns, stop patching and rewrite the affected region from scratch.
- When you change geometry or motion, update tests in the same edit.
</process>
