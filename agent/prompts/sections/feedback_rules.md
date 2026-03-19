<feedback_strategy>
- The harness may send a `<compile_signals>` block after compile/test failures, or after a passing compile that still has warnings/notes worth acting on.
- Read `<summary>` first to identify the primary issue for the current artifact.
- Treat `<failures>` as blocking issues to fix first.
- Treat `<warnings>` as non-blocking design, QC, or hygiene signals.
- Treat `<notes>` as context such as allowances or policy details, not as the main task.
- Use `<response_rules>` as the authoritative reaction guidance for that compile attempt.
</feedback_strategy>
