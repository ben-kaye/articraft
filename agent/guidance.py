"""Proactive, pre-compile nudges: cheap AST checks on model.py that pre-empt a failure the
compile loop would otherwise surface a turn later.

This is the non-provider-specific half of `../articraft`'s GuidanceInjector — its two
`maybe_inject_code_contract_guidance` scans (exact-geometry contract + baseline-QC reintroduction),
which the truth runs for every provider including OpenAI. The codex/openai-only injectors
(JSON-retry, compile-repair, api-error) are deliberately omitted; their intent lives in the
static system prompt and the compile feedback instead.

Each finding fires once per run (dedup via the caller's `seen` set) so the cached prompt prefix
isn't churned with a repeated nudge every turn.
"""

from __future__ import annotations

import ast

# Baseline QC that `compile_model` already owns; re-adding it in run_tests() is redundant noise.
_BASELINE_QC = frozenset(
    {
        "check_model_valid",
        "check_mesh_assets_ready",
        "fail_if_isolated_parts",
        "warn_if_part_contains_disconnected_geometry_islands",
        "fail_if_parts_overlap_in_current_pose",
    }
)
# kwargs that name an exact visual; a name with no matching `visual(name=...)` is a stale contract.
_EXACT_ELEM_KWARGS = frozenset(
    {"elem_a", "elem_b", "positive_elem", "negative_elem", "inner_elem", "outer_elem"}
)


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip() or None
    return None


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


class _Scan(ast.NodeVisitor):
    def __init__(self) -> None:
        self.visual_names: set[str] = set()
        self.exact_names: set[str] = set()
        self.baseline_calls: set[str] = set()
        self._fns: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fns.append(node.name)
        self.generic_visit(node)
        self._fns.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        in_tests = bool(self._fns) and self._fns[-1] == "run_tests"
        for kw in node.keywords:
            if kw.arg == "name" and name == "visual":
                if (v := _const_str(kw.value)) is not None:
                    self.visual_names.add(v)
            if in_tests and kw.arg in _EXACT_ELEM_KWARGS:
                if (v := _const_str(kw.value)) is not None:
                    self.exact_names.add(v)
        if in_tests and name in _BASELINE_QC and not node.args and not node.keywords:
            self.baseline_calls.add(name)
        self.generic_visit(node)


def guidance_messages(model_src: str, seen: set[str]) -> list[str]:
    """Return new (unseen) proactive nudges for the current model.py; records fired ones in `seen`."""
    try:
        tree = ast.parse(model_src)
    except SyntaxError:
        return []  # a syntax error is the compiler's job to report, not ours
    scan = _Scan()
    scan.visit(tree)
    out: list[str] = []

    missing = sorted(scan.exact_names - scan.visual_names)
    if missing:
        sig = "exact:" + ",".join(missing)
        if sig not in seen:
            seen.add(sig)
            joined = ", ".join(repr(n) for n in missing)
            out.append(
                "<exact_geometry_contract>\n"
                f"run_tests() references exact visual name(s) not defined in model.py: {joined}.\n"
                "Restore the named visual(s) or update/remove the dependent exact checks in the "
                "same edit before the next compile.\n"
                "</exact_geometry_contract>"
            )

    if scan.baseline_calls:
        sig = "baseline:" + ",".join(sorted(scan.baseline_calls))
        if sig not in seen:
            seen.add(sig)
            joined = ", ".join(f"`{n}`" for n in sorted(scan.baseline_calls))
            out.append(
                "<baseline_qc>\n"
                f"run_tests() re-runs baseline QC that `compile_model` already owns: {joined}.\n"
                "Drop these; keep run_tests() for prompt-specific exact checks, pose checks, and "
                "explicit allowances only.\n"
                "</baseline_qc>"
            )
    return out


def _demo() -> None:
    seen: set[str] = set()
    src = (
        "def build_object_model():\n"
        "    p = Part('a')\n"
        "    p.visual(Box((1, 1, 1)), name='leaf')\n"
        "    return p\n"
        "def run_tests():\n"
        "    ctx = TestContext(object_model)\n"
        "    ctx.check_model_valid()\n"
        "    ctx.expect_contact(a, b, elem_a='leaf', elem_b='ghost')\n"
        "    return ctx.report()\n"
    )
    msgs = guidance_messages(src, seen)
    blob = "\n".join(msgs)
    assert "exact_geometry_contract" in blob and "'ghost'" in blob, blob
    assert "'leaf'" not in blob, blob  # 'leaf' has a matching visual(), so it is not flagged
    assert "baseline_qc" in blob and "check_model_valid" in blob, blob
    assert guidance_messages(src, seen) == []  # fires once per finding

    # a visual(name=...) outside run_tests satisfies the contract; an exact name with no visual does not
    assert guidance_messages("def run_tests():\n    ctx.expect_gap(a, b, positive_elem='x')\n", set())
    # syntactically broken source yields nothing (compiler reports it)
    assert guidance_messages("def (:", set()) == []
    print("ok")


if __name__ == "__main__":
    _demo()
