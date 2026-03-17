from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from agent.compiler import persist_compile_success_artifacts, update_manifest
from agent.runner import compile_urdf


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        outputs_root = root / "outputs"
        run_dir = outputs_root / "sample_run"
        viewer_dir = outputs_root / "viewer"
        run_dir.mkdir(parents=True)
        viewer_dir.mkdir(parents=True)

        urdf_path = run_dir / "sample_run.urdf"
        sig = persist_compile_success_artifacts(
            urdf_xml="<robot name='sample'/>",
            urdf_out=urdf_path,
            outputs_root=outputs_root,
        )

        assert sig is not None
        assert urdf_path.read_text(encoding="utf-8") == "<robot name='sample'/>"

        manifest = json.loads((outputs_root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest == {
            "generated": [
                {
                    "name": "sample_run",
                    "path": "sample_run/sample_run.urdf",
                }
            ]
        }

        duplicate_sig = persist_compile_success_artifacts(
            urdf_xml="<robot name='sample'/>",
            urdf_out=urdf_path,
            outputs_root=outputs_root,
            previous_sig=sig,
        )
        assert duplicate_sig == sig

        extra_urdf = outputs_root / "second" / "second.urdf"
        extra_urdf.parent.mkdir(parents=True)
        extra_urdf.write_text("<robot name='second'/>", encoding="utf-8")
        (viewer_dir / "ignored.urdf").write_text("<robot name='viewer'/>", encoding="utf-8")
        update_manifest(outputs_root)

        manifest = json.loads((outputs_root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest == {
            "generated": [
                {
                    "name": "sample_run",
                    "path": "sample_run/sample_run.urdf",
                },
                {
                    "name": "second",
                    "path": "second/second.urdf",
                },
            ]
        }

        assert callable(compile_urdf)


if __name__ == "__main__":
    main()
