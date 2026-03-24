<tool_contract>
- Use ONLY `read_file`, `apply_patch`, `probe_model`, and `find_examples`.
- `read_file` is a JSON tool for reading the exact current text.
- `apply_patch` is a FREEFORM tool; send raw patch text only, not JSON.
- `probe_model` runs short Python snippets against the current bound model for geometry diagnosis.
- `find_examples` is lexical search over curated hybrid/CadQuery examples; use short concrete queries. Returned examples may include stale or deprecated SDK code, so treat them as inspiration/reference only and adapt against the current injected SDK docs instead of copying them verbatim.
- Do NOT provide `file_path`; the harness binds this run to one target file automatically.
- Use `probe_model` when placements, clearances, containment, or pose behavior are uncertain.
- Use `find_examples` before inventing an unfamiliar hybrid or CadQuery pattern.
- Begin with `read_file`, then patch the smallest viable region.
- After any failed patch or syntax issue, call `read_file` again before retrying.
- If the editable section is empty, initialize it with `build_object_model()` and `run_tests()`.
- Stay in single-file mode: do not add, delete, or move files.
- Never paste Python code in chat; code changes must happen in tool calls. When finished, reply briefly and without code.
</tool_contract>
