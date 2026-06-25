"""Batch run state: run.json + an append-only results.jsonl (deduped by key on read)."""

from __future__ import annotations

import json

from .models import Run, RunResult
from .records import now_iso
from .repo import Repo


class RunStore:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.layout = repo.layout

    def create(self, run_id: str, *, total: int, spec_path: str | None = None) -> Run:
        run = Run(run_id=run_id, created_at=now_iso(), total=total, spec_path=spec_path)
        self.repo.write_json(self.layout.run_json(run_id), run.model_dump())
        self.layout.run_results(run_id).touch()
        return run

    def load(self, run_id: str) -> Run:
        return Run.model_validate(self.repo.read_json(self.layout.run_json(run_id)))

    def set_status(self, run_id: str, status: str) -> None:
        run = self.load(run_id).model_copy(update={"status": status})
        self.repo.write_json(self.layout.run_json(run_id), run.model_dump())

    def append_result(self, run_id: str, result: RunResult) -> None:
        with self.layout.run_results(run_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(result.model_dump()) + "\n")

    def results(self, run_id: str) -> dict[str, RunResult]:
        """Latest result per key (last write wins)."""
        path = self.layout.run_results(run_id)
        out: dict[str, RunResult] = {}
        if not path.exists():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = RunResult.model_validate_json(line)
                out[r.key] = r
        return out
