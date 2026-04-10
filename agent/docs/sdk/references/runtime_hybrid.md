# Runtime

- Import from `sdk_hybrid` in `model.py`.
- This runtime includes the articulated-object/test/export stack plus CadQuery-backed geometry helpers.
- Use native Articraft abstractions when they clearly express the object.
- Use CadQuery when lower-level geometry control or shape construction warrants it.
- `section_loft(...)`, `repair_loft(...)`, and `partition_shell(...)` are unavailable in this runtime.
- Only `model.py` is writable. All `docs/` paths are read-only.
