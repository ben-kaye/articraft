# Runtime

- Import from `sdk` in `model.py`.
- This runtime includes both the Articraft-native geometry/tooling surface and the CadQuery-backed geometry helpers.
- Prefer native Articraft abstractions first, then use CadQuery when lower-level shape construction or construction history is the clearer fit.
- `section_loft(...)`, `repair_loft(...)`, and `partition_shell(...)` remain available alongside the CadQuery path.
- Only `model.py` is writable. All `docs/` paths are read-only.
