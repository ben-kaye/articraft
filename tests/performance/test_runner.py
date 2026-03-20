from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from performance.runner import _build_output_path, _sanitize_label


def test_sanitize_label_normalizes_to_filename_safe_slug() -> None:
    assert _sanitize_label("Before Rust Prototype") == "before-rust-prototype"
    assert _sanitize_label("   ") == "run"


def test_build_output_path_uses_date_commit_and_label() -> None:
    output_path = _build_output_path(
        output_dir=Path("performance/results"),
        created_at=datetime(2026, 3, 20, 13, 45, 0, tzinfo=timezone.utc),
        git_meta={"short_commit": "abc12345"},
        label="baseline run",
    )
    assert output_path == Path(
        "performance/results/2026-03-20/20260320T134500Z_abc12345_baseline-run.json"
    )
