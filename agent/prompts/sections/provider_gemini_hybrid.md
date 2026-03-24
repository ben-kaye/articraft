<tool_contract>
- Use ONLY `read_code`, `edit_code`, `probe_model`, and `find_examples`.
- `read_code` returns the exact editable section as plain text.
- `edit_code` performs surgical replacements inside the editable section.
- `probe_model` runs short Python snippets against the current bound model for geometry diagnosis.
- `find_examples` is lexical search over curated hybrid/CadQuery examples; use short concrete queries. Returned examples may include stale or deprecated SDK code, so treat them as inspiration/reference only and adapt against the current injected SDK docs instead of copying them verbatim.
- Do NOT provide `file_path`; the harness binds this run to one target file automatically.
- Use `probe_model` when placements, clearances, containment, or pose behavior are uncertain.
- Use `find_examples` before inventing an unfamiliar hybrid or CadQuery pattern.
- Begin with `read_code`, then replace the smallest unique snippet that solves the issue.
- After any `edit_code` failure, call `read_code` again and copy the exact current text for `old_string` before retrying.
- If the editable section is empty, initialize it with `edit_code` using `old_string=""` and a full initial implementation.
- Never paste Python code in chat; code changes must happen in tool calls. When finished, reply briefly and without code.
</tool_contract>
