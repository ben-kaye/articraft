from __future__ import annotations

import sys
from types import SimpleNamespace

from scripts import materialize_record


def test_materialize_record_prints_elapsed_time(monkeypatch, tmp_path, capsys) -> None:
    record_dir = tmp_path / "rec_test_0001"
    record_dir.mkdir()
    (record_dir / "model.py").write_text("object_model = None\n", encoding="utf-8")

    calls: list[tuple[str, bool, bool, str]] = []

    class FakeViewerStore:
        def __init__(self, repo_root):
            self.repo_root = repo_root

        def materialize_record_assets(
            self,
            record_id: str,
            *,
            force: bool,
            validate: bool,
            ignore_geom_qc: bool,
            target: str,
        ):
            calls.append((record_id, force, ignore_geom_qc, target))
            return SimpleNamespace(warnings=[])

    perf_counter_values = iter((10.0, 12.5))

    monkeypatch.setattr(materialize_record, "ViewerStore", FakeViewerStore)
    monkeypatch.setattr(materialize_record.time, "perf_counter", lambda: next(perf_counter_values))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "materialize_record.py",
            "--repo-root",
            str(tmp_path),
            "--target",
            "visual",
            str(record_dir),
        ],
    )

    exit_code = materialize_record.main()

    assert exit_code == 0
    assert calls == [("rec_test_0001", True, True, "visual")]
    output = capsys.readouterr().out
    assert "Compiled visuals for" in output
    assert "Warnings: 0" in output
    assert "Elapsed: 2.50s" in output
