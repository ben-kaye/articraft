<tools>
- Use ONLY `read_file`, `read_code`, `edit_code`, `compile_model`, `probe_model`, and `find_examples`.
- `read_file` reads exact virtual workspace file text. Use `path="model.py"` for the full artifact file and `path="docs/..."` for read-only SDK docs.
- `read_code` returns the editable section as plain text.
- `edit_code` performs surgical text replacement in the editable section.
- `compile_model` runs full compile + QC on the current file and returns structured `<compile_signals>` feedback.
- `probe_model` runs short read-only Python snippets for geometry inspection. See SDK docs for the helper catalog and signatures.
- `find_examples` does lexical search over curated examples for the active SDK. Use it proactively when you need modeling, placement, or testing patterns that are similar to the current object, especially before improvising unfamiliar mechanisms or shape constructions. Results may be stale — adapt against current SDK docs. Entries marked `[weakly relevant]` are inspiration-only and should not be over-trusted.
- Read exact current code with `read_code` before editing.
- Use `read_file(path="docs/...")` when you need exact SDK reference text beyond the preloaded router doc.
- Prefer small exact `edit_code` replacements over broad rewrites.
- If `edit_code` fails because `old_string` did not match, call `read_code` again and retry with a smaller exact snippet.
- Build one coherent part or subassembly at a time, then `compile_model` before moving on.
- Treat `compile_model` as the full validation pass. Read `<summary>` first, then fix blocking failures before adding more geometry.
- Treat tool outputs as authoritative over your first guess. If `compile_model`, `probe_model`, or examples disagree with your plan, update it instead of doing speculative self-correction.
- When a failure or warning is unclear, inspect with `probe_model` before patching blindly.
- The scaffold has existing editable code; do not assume `old_string=""` for a blank start.
- `probe_model` is inspection-only: no file writes, no modifying `object_model`, no subprocesses.
- Never paste code in chat. All code changes go through tool calls.
</tools>
