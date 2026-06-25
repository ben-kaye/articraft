"""Read/write records on disk. One directory per record, single revision."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone

from . import locks
from .models import Cost, Provenance, Record
from .repo import Repo


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_trace(path, trace: list[dict]) -> None:
    # gzip: traces are repetitive JSON and dominate record size at batch scale. stdlib, ~10x.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(trace).encode("utf-8")))


def _read_trace(path) -> list[dict]:
    if path.exists():
        return json.loads(gzip.decompress(path.read_bytes()))
    plain = path.with_suffix("")  # legacy uncompressed trace.json
    if plain.suffix == ".json" and plain.exists():
        return json.loads(plain.read_text(encoding="utf-8"))
    return []


class RecordStore:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.layout = repo.layout

    def write(
        self,
        record: Record,
        *,
        prompt: str,
        model_py: str,
        provenance: Provenance,
        urdf_xml: str | None = None,
        trace: list[dict] | None = None,
    ) -> Record:
        record = record.model_copy(
            update={
                "updated_at": now_iso(),
                "prompt": prompt,
                "prompt_sha256": sha256(prompt),
                "model_py_sha256": sha256(model_py),
                "has_urdf": urdf_xml is not None,
            }
        )
        self.layout.record_dir(record.record_id).mkdir(parents=True, exist_ok=True)
        self.layout.prompt_txt(record.record_id).write_text(prompt, encoding="utf-8")
        self.layout.model_py(record.record_id).write_text(model_py, encoding="utf-8")
        self.repo.write_json(self.layout.provenance_json(record.record_id), provenance.model_dump())
        if urdf_xml is not None:
            self.layout.model_urdf(record.record_id).write_text(urdf_xml, encoding="utf-8")
        if trace is not None:
            _write_trace(self.layout.trace_json(record.record_id), trace)
        self.repo.write_json(self.layout.record_json(record.record_id), record.model_dump())
        return record

    def update_progress(
        self,
        record: Record,
        *,
        status: str,
        trace: list[dict] | None = None,
        cost: Cost | None = None,
    ) -> Record:
        """Cheap per-turn write: only trace.json + record.json (no prompt/model re-hash)."""
        update: dict = {"updated_at": now_iso(), "status": status}
        if cost is not None:
            update["cost"] = cost
        record = record.model_copy(update=update)
        self.layout.record_dir(record.record_id).mkdir(parents=True, exist_ok=True)
        if trace is not None:
            _write_trace(self.layout.trace_json(record.record_id), trace)
        self.repo.write_json(self.layout.record_json(record.record_id), record.model_dump())
        return record

    def load(self, record_id: str) -> Record:
        return Record.model_validate(self.repo.read_json(self.layout.record_json(record_id)))

    def load_model_py(self, record_id: str) -> str:
        return self.layout.model_py(record_id).read_text(encoding="utf-8")

    def load_trace(self, record_id: str) -> list[dict]:
        return _read_trace(self.layout.trace_json(record_id))

    def _git(self, record_id: str, *args: str) -> str:
        gitdir = self.layout.model_git(record_id)
        work = self.layout.record_dir(record_id)
        out = subprocess.run(
            ["git", f"--git-dir={gitdir}", f"--work-tree={work}", *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout

    def model_history(self, record_id: str) -> list[tuple[str, str]]:
        """Per-turn (sha, message) of model.py, oldest first. [] if no .modelgit."""
        if not self.layout.model_git(record_id).exists():
            return []
        log = self._git(record_id, "log", "--reverse", "--format=%H %s").splitlines()
        return [tuple(line.split(" ", 1)) for line in log if line]  # type: ignore[misc]

    def model_diff(self, record_id: str, rev: str = "HEAD") -> str:
        """Diff of model.py for one commit (a turn), or a sha range like '<sha>..HEAD'."""
        if not self.layout.model_git(record_id).exists():
            return ""
        if ".." in rev:
            return self._git(record_id, "diff", rev, "--", "model.py")
        return self._git(record_id, "show", "--format=%s", rev, "--", "model.py")

    def exists(self, record_id: str) -> bool:
        return self.layout.record_json(record_id).exists()

    def delete(self, record_id: str) -> None:
        shutil.rmtree(self.layout.record_dir(record_id), ignore_errors=True)

    def list_ids(self) -> list[str]:
        d = self.layout.records_dir
        if not d.exists():
            return []
        return sorted(p.name for p in d.iterdir() if (p / "record.json").exists())

    def reap_stale(self) -> list[str]:
        """Flip 'running' records with a dead lock to 'failed'. Returns reaped ids.

        Call on startup to clean up after a dirty crash that left records hanging.
        Only scans run.lock files (present solely for active/crashed runs), not every
        record — O(active + crashed), not O(all records). A clean exit removes the lock.
        """
        reaped = []
        for lock in self.layout.records_dir.glob("*/run.lock"):
            if locks.is_active(lock):
                continue  # run still alive
            rid = lock.parent.name
            r = self.load(rid)
            if r.status == "running":
                self.update_progress(r, status="failed")
                reaped.append(rid)
            lock.unlink(missing_ok=True)  # drop the dead lock so we don't rescan it
        return reaped

    def rate(self, record_id: str, rater: str, score: int) -> Record:
        if not 1 <= score <= 5:
            raise ValueError("score must be 1-5")
        rec = self.load(record_id)
        record = rec.model_copy(
            update={"ratings": {**rec.ratings, rater: score}, "updated_at": now_iso()}
        )
        self.repo.write_json(self.layout.record_json(record_id), record.model_dump())
        return record

    def unrate(self, record_id: str, rater: str) -> Record:
        rec = self.load(record_id)
        record = rec.model_copy(
            update={
                "ratings": {k: v for k, v in rec.ratings.items() if k != rater},
                "updated_at": now_iso(),
            }
        )
        self.repo.write_json(self.layout.record_json(record_id), record.model_dump())
        return record
