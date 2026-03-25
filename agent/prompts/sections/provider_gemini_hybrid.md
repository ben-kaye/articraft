<tools>
- Use ONLY `read_code`, `edit_code`, `probe_model`, and `find_examples`.
- `read_code` returns the editable section as plain text.
- `edit_code` performs surgical text replacement in the editable section.
- `probe_model` runs short read-only Python snippets for geometry inspection. See SDK docs for the helper catalog and signatures.
- `find_examples` does lexical search over curated hybrid/CadQuery examples. Results may be stale — adapt against current SDK docs.
- The harness binds one file automatically. Do not provide `file_path`.
- After any `edit_code` failure, call `read_code` and copy exact current text for `old_string` before retrying.
- The scaffold has existing editable code; do not assume `old_string=""` for a blank start.
- `probe_model` is inspection-only: no file writes, no modifying `object_model`, no subprocesses.
- Never paste code in chat. All code changes go through tool calls.
</tools>
