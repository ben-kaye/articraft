"""Batch generation: a CSV of prompts -> parallel records, resumable.

Concurrency is asyncio + a Semaphore; no custom runtime layer.
CSV needs a `prompt` column; optional `category`.
"""

from __future__ import annotations

import asyncio
import csv
from pathlib import Path

from storage.models import RunResult
from storage.repo import Repo
from storage.runs import RunStore

from .runner import new_id, run_from_input


def _read_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run_batch(
    csv_path: Path | str,
    *,
    repo_root: Path | str,
    model: str | None = None,
    thinking_level: str | None = None,
    concurrency: int = 4,
    max_turns: int = 40,
    max_cost_usd: float | None = None,
    resume_run_id: str | None = None,
) -> str:
    csv_path = Path(csv_path)
    repo = Repo(repo_root)
    store = RunStore(repo)
    rows = _read_rows(csv_path)

    run_id = resume_run_id or new_id("run")
    if resume_run_id:
        done = {k for k, r in store.results(run_id).items() if r.status == "done"}
    else:
        store.create(run_id, total=len(rows), spec_path=str(csv_path))
        done = set()

    async def _drive() -> None:
        sem = asyncio.Semaphore(concurrency)

        async def _one(i: int, row: dict) -> None:
            key = row.get("id") or str(i)
            if key in done:
                return
            async with sem:
                try:
                    rec = await asyncio.to_thread(
                        run_from_input,
                        row["prompt"],
                        repo_root=repo_root,
                        model=model,
                        thinking_level=thinking_level,
                        max_turns=max_turns,
                        max_cost_usd=max_cost_usd,
                    )
                    status = "done" if rec.compile_ok else "failed"
                    store.append_result(
                        run_id,
                        RunResult(key=key, record_id=rec.record_id, status=status),
                    )
                except Exception as exc:  # noqa: BLE001 — record failure, keep going
                    store.append_result(run_id, RunResult(key=key, status="failed", error=str(exc)))

        await asyncio.gather(*(_one(i, row) for i, row in enumerate(rows)))

    asyncio.run(_drive())
    results = store.results(run_id)
    ok = sum(1 for r in results.values() if r.status == "done")
    store.set_status(run_id, "done")
    print(f"batch {run_id}: {ok}/{len(rows)} ok")
    return run_id
