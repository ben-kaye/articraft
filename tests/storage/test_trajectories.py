from __future__ import annotations

from pathlib import Path

from storage.repo import StorageRepo
from storage.trajectories import (
    canonicalize_record_trace_dir,
    trace_system_prompt_paths,
)


def test_canonicalize_record_trace_dir_removes_all_provider_system_prompt_files(
    tmp_path: Path,
) -> None:
    repo = StorageRepo(tmp_path)
    repo.ensure_layout()
    trace_dir = repo.layout.record_revision_traces_dir("rec_prompt_001", "rev_000001")
    trace_dir.mkdir(parents=True)
    (trace_dir / "trajectory.jsonl").write_text("{}\n", encoding="utf-8")
    prompt_names = [
        "designer_system_prompt.txt",
        "designer_system_prompt_anthropic.txt",
        "designer_system_prompt_codex_cli.txt",
        "designer_system_prompt_deepseek.txt",
        "designer_system_prompt_gemini.txt",
        "designer_system_prompt_openai.txt",
        "designer_system_prompt_openrouter.txt",
    ]
    for name in prompt_names:
        (trace_dir / name).write_text("system\n", encoding="utf-8")

    assert sorted(path.name for path in trace_system_prompt_paths(trace_dir)) == sorted(
        prompt_names
    )

    canonicalize_record_trace_dir(repo, "rec_prompt_001", revision_id="rev_000001")

    assert all(not (trace_dir / name).exists() for name in prompt_names)
    assert (trace_dir / "trajectory.jsonl.zst").exists()
