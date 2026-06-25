"""Run an inspection snippet against a model.py's object_model, emit a JSON result.

Invoked as a subprocess by tools._probe so a runaway/segfaulting snippet can't take down the
agent. The snippet gets `object_model`, `ctx` (a TestContext), `Origin`, and `emit(value)` —
which it must call exactly once with a JSON-serializable value. Inspection only; no sandbox
beyond process isolation + timeout (same trust model as compile).

Usage: python -m agent._probe_worker <model_path>  (snippet on stdin)
"""

from __future__ import annotations

import io
import json
import runpy
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout


def _jsonable(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if hasattr(v, "xyz") and hasattr(v, "rpy"):  # Origin-like
        return {"xyz": [float(x) for x in v.xyz], "rpy": [float(x) for x in v.rpy]}
    return str(v)


def main(model_path: str) -> None:
    import sdk
    from sdk._core.v0.assets import activate_asset_session, asset_session_for_script

    code = sys.stdin.read()
    out, err = io.StringIO(), io.StringIO()
    emitted = {"count": 0, "value": None}

    def emit(value):
        emitted["count"] += 1
        if emitted["count"] > 1:
            raise RuntimeError("emit(value) must be called exactly once")
        emitted["value"] = value

    result: dict = {"ok": False}
    try:
        with activate_asset_session(asset_session_for_script(model_path)):
            g = runpy.run_path(model_path)
            object_model = g.get("object_model")
            if object_model is None:
                raise ValueError("script must define a top-level `object_model`")
            ctx = sdk.TestContext(object_model)
            ns = {"object_model": object_model, "ctx": ctx, "Origin": sdk.Origin, "emit": emit}
            with redirect_stdout(out), redirect_stderr(err):
                exec(compile(code, "<probe>", "exec"), ns, ns)
            if emitted["count"] == 0:
                raise RuntimeError("emit(value) was not called")
            value = _jsonable(emitted["value"])
            json.dumps(value)  # ensure serializable
            result = {"ok": True, "result": value}
    except Exception as exc:  # noqa: BLE001 — report everything back to the agent
        result = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
    stdout_text = out.getvalue().strip()
    if stdout_text:
        result["stdout"] = stdout_text[-2000:]
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1])
