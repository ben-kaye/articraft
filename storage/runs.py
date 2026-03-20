from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storage.models import RunRecord
from storage.repo import StorageRepo


@dataclass(slots=True)
class RunStore:
    repo: StorageRepo

    def ensure_run_dirs(self, run_id: str) -> Path:
        run_dir = self.repo.layout.run_dir(run_id)
        self.repo.layout.run_staging_dir(run_id).mkdir(parents=True, exist_ok=True)
        self.repo.layout.run_failures_dir(run_id).mkdir(parents=True, exist_ok=True)
        self.repo.layout.run_state_dir(run_id).mkdir(parents=True, exist_ok=True)
        return run_dir

    def write_run(self, run: RunRecord) -> Path:
        self.ensure_run_dirs(run.run_id)
        path = self.repo.layout.run_metadata_path(run.run_id)
        self.repo.write_json(path, run.to_dict())
        return path

    def append_result(self, run_id: str, result: dict[str, Any]) -> Path:
        self.ensure_run_dirs(run_id)
        path = self.repo.layout.run_results_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        return path

    def read_results(self, run_id: str) -> list[dict[str, Any]]:
        path = self.repo.layout.run_results_path(run_id)
        if not path.exists():
            return []

        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                payload = line.strip()
                if not payload:
                    continue
                row = json.loads(payload)
                if isinstance(row, dict):
                    rows.append(row)
        return rows

    def write_results(self, run_id: str, results: list[dict[str, Any]]) -> Path:
        self.ensure_run_dirs(run_id)
        path = self.repo.layout.run_results_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in results:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return path

    def upsert_result(self, run_id: str, result: dict[str, Any], *, key: str) -> Path:
        key_value = result.get(key)
        if not isinstance(key_value, str) or not key_value.strip():
            raise ValueError(f"Result is missing non-empty key field {key!r}")

        rows = self.read_results(run_id)
        updated = False
        for index, row in enumerate(rows):
            if row.get(key) == key_value:
                rows[index] = result
                updated = True
                break
        if not updated:
            rows.append(result)
        return self.write_results(run_id, rows)
