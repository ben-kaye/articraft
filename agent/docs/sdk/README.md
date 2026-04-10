---
name: articraft-sdk
description: Canonical Articraft SDK docs router for artifact generation. Read the runtime and quickstart references first, then load only the topic docs you need.
always_load: true
default_reads:
  - references/runtime.md
  - references/quickstart.md
  - references/probe-tooling.md
  - references/testing.md
writable_paths:
  - model.py
read_only_roots:
  - docs/
---

# Articraft SDK Docs

You are working in a virtual authoring workspace.

- `model.py` is the current editable artifact script.
- `docs/sdk/README.md` is this always-loaded router document.
- `docs/sdk/references/...` contains detailed read-only SDK references.

Only `model.py` is writable. Treat everything under `docs/` as read-only guidance.

## Read Order

1. Read `references/runtime.md` for the active import surface and runtime-specific capability notes.
2. Read `references/quickstart.md` before substantial edits if you have not loaded it yet.
3. Read `references/probe-tooling.md` and `references/testing.md` when validating or debugging.
4. Load only the additional topic docs needed for the current object.

## Working Style

- Read exact file text with `read_file(path=...)`.
- Use `path="model.py"` for the editable artifact.
- Use `path="docs/..."` for SDK guidance and references.
- Prefer Articraft-native abstractions when they clearly express the object.
- Use lower-level CadQuery-style construction only when the runtime supports it and the geometry warrants it.
- Mixing higher-level Articraft structure with lower-level geometry helpers is allowed when it yields a clearer, more realistic artifact.

## Topic Map

- Runtime/import surface: `references/runtime.md`
- Choosing abstraction level: `references/native-vs-cadquery.md`
- Quickstart and workflow: `references/quickstart.md`
- Errors and failure modes: `references/errors.md`
- Core types and authoring primitives: `references/core-types.md`
- Object structure and articulations: `references/articulated-object.md`
- Placement and transforms: `references/placement.md`
- Probe helpers and inspection workflow: `references/probe-tooling.md`
- Validation and tests: `references/testing.md`
- Native geometry topics: `references/geometry/...`
- CadQuery topics: `references/cadquery/...`

Read only what you need. The detailed docs are mounted under virtual `docs/` paths even if the
real repository stores them elsewhere.
