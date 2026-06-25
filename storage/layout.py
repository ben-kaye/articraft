"""All on-disk paths in one place. Everything hangs off a repo root."""

from __future__ import annotations

from pathlib import Path


class Layout:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def records_dir(self) -> Path:
        return self.data / "records"

    @property
    def categories_dir(self) -> Path:
        return self.data / "categories"

    @property
    def runs_dir(self) -> Path:
        return self.data / "runs"

    @property
    def index_db(self) -> Path:
        return self.data / "index.db"

    def record_dir(self, record_id: str) -> Path:
        return self.records_dir / record_id

    def record_json(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "record.json"

    def prompt_txt(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "prompt.txt"

    def model_py(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "model.py"

    def provenance_json(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "provenance.json"

    def model_urdf(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "model.urdf"

    def trace_json(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "trace.json.gz"

    def run_lock(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "run.lock"

    def model_git(self, record_id: str) -> Path:
        return self.record_dir(record_id) / ".modelgit"

    def inputs_dir(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "inputs"

    def assets_dir(self, record_id: str) -> Path:
        return self.record_dir(record_id) / "assets"

    def category_json(self, slug: str) -> Path:
        return self.categories_dir / f"{slug}.json"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def run_json(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run.json"

    def run_results(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "results.jsonl"
