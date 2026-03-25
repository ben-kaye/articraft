<tools>
- Use ONLY `read_file`, `apply_patch`, `probe_model`, and `find_examples`.
- `read_file` is a JSON tool for reading current file text.
- `apply_patch` is a FREEFORM tool; send raw patch text, not JSON.
- `probe_model` runs short read-only Python snippets for geometry inspection. See SDK docs for the helper catalog and signatures.
- `find_examples` does lexical search over curated hybrid/CadQuery examples. Results may be stale — adapt against current SDK docs.
- The harness binds one file automatically. Do not provide `file_path`. Stay in single-file mode.
- `probe_model` is inspection-only: no file writes, no modifying `object_model`, no subprocesses.
- The scaffold has existing editable code; modify it rather than assuming a blank start.
- Never paste code in chat. All code changes go through tool calls.
</tools>
