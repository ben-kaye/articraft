"""Runs a generated model.py in isolation and emits a JSON result on stdout.

Invoked as a subprocess by compiler.py so a CAD-kernel segfault or runaway script can't take
down the agent. Usage: python -m agent._compile_worker <model_path> <urdf_out_path>
"""

from __future__ import annotations

import json
import runpy
import sys
import traceback


def main(model_path: str, urdf_out: str) -> None:
    from sdk._core.v0._urdf_export import compile_object_to_urdf_xml
    from sdk._core.v0.assets import activate_asset_session, asset_session_for_script

    result: dict = {"ok": False, "urdf_written": False, "error": None, "report": None}
    try:
        session = asset_session_for_script(model_path)
        with activate_asset_session(session):
            g = runpy.run_path(model_path)
            object_model = g.get("object_model")
            if object_model is None:
                raise ValueError("script must define a top-level `object_model`")
            urdf_xml = compile_object_to_urdf_xml(object_model)
            with open(urdf_out, "w", encoding="utf-8") as f:
                f.write(urdf_xml)
            # Geometry built. Flag it so the viewer can render even if run_tests() below raises.
            result["urdf_written"] = True

            run_tests = g.get("run_tests")
            if callable(run_tests):
                report = run_tests()
                result["report"] = {
                    "passed": bool(getattr(report, "passed", True)),
                    "checks_run": getattr(report, "checks_run", 0),
                    "failures": [
                        {"name": fa.name, "details": fa.details}
                        for fa in getattr(report, "failures", ())
                    ],
                    "warnings": list(getattr(report, "warnings", ())),
                    "allowances": list(getattr(report, "allowances", ())),
                    "allowed_isolated_parts": list(getattr(report, "allowed_isolated_parts", ())),
                }
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001 — report everything back to the agent
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()

    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
