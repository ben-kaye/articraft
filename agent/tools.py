"""Flat tool registry. The agent works on a single model.py inside a workspace dir.

Each tool: an OpenAI function schema + a run(ws, **args) -> str. No class hierarchy.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .compiler import CompileResult, compile_model
from .feedback import failure_signature, repeated_failure_note


@dataclass
class Workspace:
    model_path: Path
    repo_root: Path
    docs: dict[str, Path] = field(default_factory=dict)  # name -> path, read-only SDK docs
    find_examples: Callable[[str, int], str] | None = None  # query, k -> formatted examples
    last_compile: CompileResult | None = None  # structured signal from the latest compile call
    last_compile_sha: str | None = None  # sha256 of model.py at last_compile, for cache hits
    prev_fail_sig: str | None = None  # failure fingerprint of the previous compile (streak detect)
    fail_streak: int = 0  # consecutive compiles hitting the same failure signature


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[..., str]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _read_file(ws: Workspace, path: str = "model.py") -> str:
    if path in ("", "model.py"):
        if not ws.model_path.exists():
            return "(model.py is empty)"
        return ws.model_path.read_text(encoding="utf-8")
    doc = ws.docs.get(path) or ws.docs.get(Path(path).name)
    if doc is None:
        return f"ERROR: unknown path {path!r}. Readable: model.py, " + ", ".join(sorted(ws.docs))
    return doc.read_text(encoding="utf-8")


def _write_file(ws: Workspace, content: str) -> str:
    ws.model_path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to model.py."


def _str_replace(ws: Workspace, old: str, new: str) -> str:
    text = ws.model_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return "ERROR: `old` string not found in model.py. Read the file and retry."
    if count > 1:
        return f"ERROR: `old` string is not unique ({count} matches). Add more context."
    ws.model_path.write_text(text.replace(old, new), encoding="utf-8")
    return "Replaced."


class _PatchError(ValueError):
    pass


def _apply_v4a(text: str, patch: str) -> str:
    """Apply an OpenAI V4A patch to a single file's text. ponytail: scoped to our one
    model.py — no multi-file / add / delete / move, no @@-anchor scoping. Each hunk's
    context+removed block must be contiguous in the file (the V4A guarantee); we locate it
    by exact match, falling back to a per-line right-strip if trailing whitespace drifted."""
    hunks: list[list[str]] = []
    cur: list[str] = []
    for ln in patch.splitlines():
        s = ln.strip()
        if s in ("*** Begin Patch", "*** End Patch") or ln.startswith("*** "):
            continue  # sentinels + `*** Update File:` header (single file, ignored)
        if ln.startswith("@@"):  # section anchor — only a hunk separator for us
            if cur:
                hunks.append(cur)
                cur = []
            continue
        cur.append(ln)
    if cur:
        hunks.append(cur)

    for hunk in hunks:
        old, new = [], []
        for ln in hunk:
            tag, rest = (ln[0], ln[1:]) if ln else (" ", "")
            if tag == "-":
                old.append(rest)
            elif tag == "+":
                new.append(rest)
            else:  # ' ' context, or an unprefixed line treated as context
                old.append(rest if tag == " " else ln)
                new.append(rest if tag == " " else ln)
        if not old:
            raise _PatchError("hunk has no context or removed lines; cannot locate it")
        search, repl = "\n".join(old), "\n".join(new)
        if search in text:
            text = text.replace(search, repl, 1)
            continue
        # fallback: tolerate trailing-whitespace drift per line
        loose = "\n".join(s.rstrip() for s in old)
        lines = text.split("\n")
        for i in range(len(lines) - len(old) + 1):
            if "\n".join(s.rstrip() for s in lines[i : i + len(old)]) == loose:
                text = "\n".join(lines[:i] + repl.split("\n") + lines[i + len(old) :])
                break
        else:
            raise _PatchError(f"could not locate hunk context:\n{search[:300]}")
    return text


def _apply_patch(ws: Workspace, input: str) -> str:
    if not ws.model_path.exists():
        return "ERROR: model.py is empty; use write_file to create it first."
    try:
        new_text = _apply_v4a(ws.model_path.read_text(encoding="utf-8"), input)
    except _PatchError as exc:
        return f"ERROR: {exc}. Read model.py and retry."
    ws.model_path.write_text(new_text, encoding="utf-8")
    return "Applied patch."


def _compile(ws: Workspace) -> str:
    sha = hashlib.sha256(ws.model_path.read_bytes()).hexdigest()
    if ws.last_compile is not None and sha == ws.last_compile_sha:
        return (
            "WARNING: model.py is unchanged since the last compile, so this recompile is "
            "redundant and the result is identical. Edit the file to make progress before "
            "compiling again. Cached result:\n" + ws.last_compile.feedback
        )
    ws.last_compile = compile_model(ws.model_path, repo_root=ws.repo_root)
    ws.last_compile_sha = sha
    fb = ws.last_compile.feedback
    # Streak escalation (articraft's dedupe_key/consecutive-failure nudge): track the same blocking
    # signature across real compiles and append a stronger hint as it repeats. The cached path above
    # returns early, so an unchanged recompile never bumps the streak.
    sig = failure_signature(ws.last_compile)
    ws.fail_streak = ws.fail_streak + 1 if sig is not None and sig == ws.prev_fail_sig else int(sig is not None)
    ws.prev_fail_sig = sig
    if note := repeated_failure_note(ws.fail_streak):
        fb += "\n\n" + note
    return fb


def _probe(ws: Workspace, code: str, timeout_ms: int = 60_000) -> str:
    """Run an inspection snippet against object_model in an isolated subprocess."""
    if not ws.model_path.exists():
        return "ERROR: model.py is empty; write it before probing."
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "agent._probe_worker", str(ws.model_path)],
            cwd=str(ws.repo_root),
            input=code,
            capture_output=True,
            text=True,
            timeout=max(timeout_ms, 100) / 1000.0,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: probe timed out after {timeout_ms} ms."
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "ERROR: probe subprocess crashed:\n" + (proc.stderr or "")[-1000:]
    if data.get("ok"):
        out = f"result: {json.dumps(data['result'])}"
        return out + f"\nstdout:\n{data['stdout']}" if data.get("stdout") else out
    msg = f"ERROR: {data.get('error', 'probe failed')}"
    return msg + "\n" + data["traceback"][-1500:] if data.get("traceback") else msg


def _find_examples(ws: Workspace, query: str, k: int = 3) -> str:
    if ws.find_examples is None:
        return "ERROR: example search is unavailable in this run."
    return ws.find_examples(query, k)


_STRING = {"type": "string"}

REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "read_file",
            "Read a file. Omit `path` (or path='model.py') for the current model.py; "
            "pass an SDK doc name to read additional reference docs.",
            {
                "type": "object",
                "properties": {
                    "path": {
                        **_STRING,
                        "description": "model.py (default) or an SDK doc name from the system prompt.",
                    }
                },
            },
            _read_file,
        ),
        Tool(
            "write_file",
            "Overwrite model.py with the given content.",
            {
                "type": "object",
                "properties": {"content": _STRING},
                "required": ["content"],
            },
            _write_file,
        ),
        Tool(
            "str_replace",
            "Replace a unique occurrence of `old` with `new` in model.py.",
            {
                "type": "object",
                "properties": {"old": _STRING, "new": _STRING},
                "required": ["old", "new"],
            },
            _str_replace,
        ),
        Tool(
            "apply_patch",
            "Edit model.py with a V4A patch (OpenAI apply_patch format). `input` is:\n"
            "*** Begin Patch\n*** Update File: model.py\n@@ <optional context header>\n"
            " unchanged line\n-removed line\n+added line\n*** End Patch\n"
            "Each hunk's context + removed lines must match the file contiguously. Prefer this "
            "over str_replace for multi-line edits.",
            {
                "type": "object",
                "properties": {"input": {**_STRING, "description": "the V4A patch text"}},
                "required": ["input"],
            },
            _apply_patch,
        ),
        Tool(
            "compile_model",
            "Compile model.py to URDF and run its tests; returns the result.",
            {"type": "object", "properties": {}},
            _compile,
        ),
        Tool(
            "probe_model",
            "Inspection only: run a short Python snippet against the current model.py to measure "
            "geometry (placements, clearances, containment, overlap, poses). The snippet gets "
            "`object_model`, `ctx` (a TestContext), and `Origin`; it must call `emit(value)` exactly "
            "once with a JSON-serializable value. Does not mutate model.py. Use it when a geometry "
            "issue is ambiguous before editing.",
            {
                "type": "object",
                "properties": {
                    "code": {
                        **_STRING,
                        "description": "Python snippet; call emit(value) exactly once.",
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": "execution timeout (default 60000)",
                    },
                },
                "required": ["code"],
            },
            _probe,
        ),
        Tool(
            "find_examples",
            "Probe the record store for past models matching a query; returns their "
            "prompt + model.py source as reference. Use it before writing to crib SDK usage.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        **_STRING,
                        "description": "free-text search, e.g. 'cabinet drawer hinge'",
                    },
                    "k": {"type": "integer", "description": "max examples (default 3)"},
                },
                "required": ["query"],
            },
            _find_examples,
        ),
    ]
}


def schemas(ws: Workspace | None = None, model: str = "") -> list[dict]:
    return [t.schema() for t in REGISTRY.values()]


def dispatch(name: str, ws: Workspace, args: dict) -> str:
    tool = REGISTRY.get(name)
    if tool is None:
        return f"ERROR: unknown tool {name!r}."
    try:
        return tool.run(ws, **args)
    except TypeError as exc:
        return f"ERROR: bad arguments for {name}: {exc}"


def _selfcheck() -> None:
    src = "def foo():\n    x = 1\n    return x\n"
    patch = (
        "*** Begin Patch\n*** Update File: model.py\n@@ def foo():\n"
        "     x = 1\n-    return x\n+    return x + 1\n*** End Patch"
    )
    assert _apply_v4a(src, patch) == "def foo():\n    x = 1\n    return x + 1\n"
    # trailing-whitespace drift still locates
    assert _apply_v4a("a \nb\n", "*** Begin Patch\n a\n-b\n+c\n*** End Patch") == "a\nc\n"
    # missing context is reported, not silently misplaced
    try:
        _apply_v4a(src, "*** Begin Patch\n-nope\n+x\n*** End Patch")
    except _PatchError:
        pass
    else:
        raise AssertionError("expected _PatchError for unlocatable hunk")
    print("ok")


if __name__ == "__main__":
    _selfcheck()
