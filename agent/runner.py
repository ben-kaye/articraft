"""Public entry point: run a generation, persist a record, expose a CLI.

Covers single generation and fork/edit. Batch lives in batch_runner.py.
"""

from __future__ import annotations

import argparse
import os
import shutil
import uuid
from pathlib import Path

from articraft.config import (
    default_model_from_env,
    default_thinking_level_from_env,
    load_repo_env,
)
from storage import locks
from storage.db import ExampleIndex, Index
from storage.models import Cost, Lineage, Provenance, Record
from storage.records import RecordStore, now_iso
from storage.repo import Repo

from . import prompts, tools
from .harness import AgentResult, ArticraftAgent

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAFFOLD = REPO_ROOT / "scaffold.py"
EXAMPLES_DIR = REPO_ROOT / "sdk" / "_examples"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _code_git(root: Path) -> str:
    """Harness git HEAD as '<sha>' or '<sha>-dirty'; '' if not a git repo."""
    import subprocess

    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True, text=True,
    ).stdout.strip()
    return f"{sha}-dirty" if dirty else sha


def _persist(
    repo: Repo,
    record_id: str,
    *,
    prompt: str,
    result: AgentResult,
    model: str,
    thinking_level: str,
    sdk_package: str,
    lineage: Lineage,
    created_at: str | None = None,
) -> Record:
    store = RecordStore(repo)
    record = Record(
        record_id=record_id,
        created_at=created_at or now_iso(),
        updated_at=now_iso(),
        prompt=prompt,
        title=prompt[:80],
        model=model,
        lineage=lineage,
        cost=Cost(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            total_usd=result.cost_usd,
        ),
        compile_ok=result.compile.passed,
        code_git=_code_git(Path(__file__).resolve().parent.parent),
    )
    provenance = Provenance(
        model=model,
        thinking_level=thinking_level,
        sdk_package=sdk_package,
        turn_count=result.turns,
    )
    record = store.write(
        record,
        prompt=prompt,
        model_py=result.model_py,
        provenance=provenance,
        urdf_xml=result.urdf_xml,
        trace=result.trace,
    )
    # Best-effort thumbnail (model.urdf + assets are now on disk in the record dir).
    # Spins headless Chromium (~seconds); set ARTICRAFT_THUMBNAILS=0 for bulk runs.
    if result.urdf_xml is not None and os.environ.get("ARTICRAFT_THUMBNAILS") != "0":
        from viewer.thumbnail import render_thumbnail

        render_thumbnail(record_id, root=repo.root)
    Index(repo).rebuild()
    return record


def _make_find_examples():
    """Curated sdk/_examples ranked by bm25. Records are not searched."""

    def find(query: str, k: int = 3) -> str:
        index = ExampleIndex(EXAMPLES_DIR)  # rebuilt per call: cheap, never stale
        out: list[str] = []
        for _kind, ref in index.search(query, limit=k):
            rel = Path(ref).relative_to(REPO_ROOT)
            out.append(
                f"===== example {rel} =====\n{Path(ref).read_text(encoding='utf-8').strip()}"
            )
        return "\n\n".join(out) if out else f"No examples found for {query!r}."

    return find


def _run_agent(
    workspace_dir: Path,
    repo_root: Path,
    prompt: str,
    *,
    model,
    thinking_level,
    sdk_package,
    max_turns,
    max_cost_usd,
    image_path,
    seed_from,
    find_examples=None,
    on_turn=None,
) -> AgentResult:
    workspace_dir.mkdir(parents=True, exist_ok=True)
    model_path = workspace_dir / "model.py"
    shutil.copy(seed_from or SCAFFOLD, model_path)
    ws = tools.Workspace(
        model_path=model_path,
        repo_root=repo_root,
        docs=prompts.doc_map(sdk_package),
        find_examples=find_examples,
    )
    agent = ArticraftAgent(
        ws,
        model=model,
        thinking_level=thinking_level,
        sdk_package=sdk_package,
        max_turns=max_turns,
        max_cost_usd=max_cost_usd,
    )
    return agent.run(prompt, image_path=image_path, on_turn=on_turn)


def run_from_input(
    prompt: str,
    *,
    repo_root: Path | str,
    model: str | None = None,
    thinking_level: str | None = None,
    sdk_package: str = "sdk",
    max_turns: int = 40,
    max_cost_usd: float | None = None,
    image_path: Path | None = None,
    fork_of: str | None = None,
) -> Record:
    repo_root = Path(repo_root)
    load_repo_env(repo_root)
    repo = Repo(repo_root)
    model = model or default_model_from_env()
    thinking_level = thinking_level or default_thinking_level_from_env()

    RecordStore(repo).reap_stale()  # clean up runs orphaned by an earlier crash

    record_id = new_id("rec")
    lineage = Lineage()
    seed_from = None
    if fork_of is not None:
        parent = RecordStore(repo).load(fork_of)
        lineage = Lineage(
            origin_record_id=parent.lineage.origin_record_id or fork_of,
            parent_record_id=fork_of,
        )
        seed_from = repo.layout.model_py(fork_of)

    # Write an initial "running" record so the viewer can show the run in progress.
    store = RecordStore(repo)
    running = Record(
        record_id=record_id,
        created_at=now_iso(),
        updated_at=now_iso(),
        prompt=prompt,
        title=prompt[:80],
        model=model,
        lineage=lineage,
        status="running",
    )
    store.write(
        running,
        prompt=prompt,
        model_py="",
        provenance=Provenance(model=model, thinking_level=thinking_level, sdk_package=sdk_package),
        trace=[],
    )
    Index(repo).rebuild()

    def on_turn(trace: list[dict], in_tok: int, out_tok: int, cache_tok: int, cost: float) -> None:
        store.update_progress(
            running,
            status="running",
            trace=trace,
            cost=Cost(
                input_tokens=in_tok,
                output_tokens=out_tok,
                cache_read_tokens=cache_tok,
                total_usd=cost,
            ),
        )

    # Lock held for the run's lifetime: removed on normal exit *and* on exception
    # (the context manager's finally). A dirty crash leaves it, but the PID inside
    # is dead, so the next run's reap_stale() flips this record to 'failed'.
    with locks.hold(repo.layout.run_lock(record_id)):
        try:
            result = _run_agent(
                repo.layout.record_dir(record_id),
                repo_root,
                prompt,
                model=model,
                thinking_level=thinking_level,
                sdk_package=sdk_package,
                max_turns=max_turns,
                max_cost_usd=max_cost_usd,
                image_path=image_path,
                seed_from=seed_from,
                find_examples=_make_find_examples(),
                on_turn=on_turn,
            )
        except Exception:
            # Reload to keep the latest cost/trace written by on_turn; just flip status.
            store.update_progress(store.load(record_id), status="failed")
            raise

        return _persist(
            repo,
            record_id,
            prompt=prompt,
            result=result,
            model=model,
            thinking_level=thinking_level,
            sdk_package=sdk_package,
            lineage=lineage,
            created_at=running.created_at,
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="articraft")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="Generate a model from a prompt.")
    g.add_argument("prompt")
    f = sub.add_parser("fork", help="Fork/edit an existing record.")
    f.add_argument("record_id")
    f.add_argument("prompt")

    b = sub.add_parser("batch", help="Generate from a CSV of prompts.")
    b.add_argument("csv")
    b.add_argument("--concurrency", type=int, default=4)
    b.add_argument("--resume", default=None, help="resume an existing run id")

    for s in (g, f, b):
        s.add_argument("--repo-root", default=".")
        s.add_argument("--model", default=None)
        s.add_argument("--thinking", default=None)
        s.add_argument("--max-turns", type=int, default=40)
        s.add_argument("--max-cost", type=float, default=None)
    for s in (g, f):
        s.add_argument("--image", default=None)

    args = p.parse_args(argv)
    if args.cmd == "batch":
        from .batch_runner import run_batch

        run_batch(
            args.csv,
            repo_root=args.repo_root,
            model=args.model,
            thinking_level=args.thinking,
            concurrency=args.concurrency,
            max_turns=args.max_turns,
            max_cost_usd=args.max_cost,
            resume_run_id=args.resume,
        )
        return 0

    record = run_from_input(
        args.prompt,
        repo_root=args.repo_root,
        model=args.model,
        thinking_level=args.thinking,
        max_turns=args.max_turns,
        max_cost_usd=args.max_cost,
        image_path=Path(args.image) if args.image else None,
        fork_of=getattr(args, "record_id", None),
    )
    status = "OK" if record.compile_ok else "FAILED"
    cost = f"${record.cost.total_usd:.4f}" if record.cost.total_usd else "unknown cost"
    print(f"[{status}] {record.record_id}  {cost}  ({record.model})")
    return 0 if record.compile_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
