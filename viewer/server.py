"""FastAPI viewer backend. Reuses the storage layer; serves records + their files to web/.

Run: uv run python -m viewer.server [--root .] [--port 8000]
Self-check: uv run python -m viewer.server --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent import analytics, gittrack
from agent.compiler import compile_model
from storage import locks
from storage.db import Index
from storage.models import avg_rating
from storage.records import RecordStore
from storage.repo import Repo

WEB_DIST = Path(__file__).parent / "web" / "dist"


def create_app(root: Path | str = ".") -> FastAPI:
    repo = Repo(root)
    store = RecordStore(repo)
    store.reap_stale()  # heal records orphaned 'running' by a crashed harness
    index = Index(repo)
    app = FastAPI(title="articraft viewer")

    # ponytail: wide-open CORS — local dev tool, not internet-facing.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def summary(rid: str) -> dict:
        r = store.load(rid)
        return {
            "record_id": r.record_id,
            "title": r.title or r.prompt,
            "prompt": r.prompt,
            "rating": avg_rating(r.ratings),
            "n_ratings": len(r.ratings),
            "model": r.model,
            "compile_ok": r.compile_ok,
            # Trust the file on disk, not the stored flag: a run that crashed
            # mid-compile leaves a valid model.urdf but a stale has_urdf=False.
            "has_urdf": repo.layout.model_urdf(rid).exists(),
            "status": r.status,
            "created_at": r.created_at,
        }

    @app.get("/api/records")
    def list_records(q: str = "") -> list[dict]:
        return [summary(rid) for rid in index.search(q)]

    @app.get("/api/records/{record_id}")
    def get_record(record_id: str) -> dict:
        if not store.exists(record_id):
            raise HTTPException(404, "no such record")
        r = store.load(record_id)
        prov_path = repo.layout.provenance_json(record_id)
        return {
            **r.model_dump(),
            "has_urdf": repo.layout.model_urdf(record_id).exists(),
            "model_py": store.load_model_py(record_id),
            "provenance": repo.read_json(prov_path) if prov_path.exists() else None,
            "trace": (trace := store.load_trace(record_id)),
            "diffs": gittrack.diffs(repo.layout.model_py(record_id)),
            "meta_turns": analytics.meta_turns(trace),
        }

    # Serialize on-demand per-turn compiles: the viewer fires several file requests at
    # once (URDF + its meshes), and a cold turn must compile only once.
    # ponytail: one global lock; per-turn locks only if parallel record browsing stalls.
    _turn_compile_lock = threading.Lock()

    def build_turn(record_id: str, turn: int, turn_dir: Path) -> None:
        """Compile the model.py snapshot at `turn` into turn_dir (model.urdf + assets/).
        Cached: a no-op once model.urdf exists. No-op if the snapshot can't be read."""
        with _turn_compile_lock:
            if (turn_dir / "model.urdf").exists():
                return  # built while we waited on the lock
            src = gittrack.model_at(repo.layout.model_py(record_id), turn)
            if src is None:
                return
            turn_dir.mkdir(parents=True, exist_ok=True)
            model_py = turn_dir / "model.py"
            model_py.write_text(src, encoding="utf-8")
            compile_model(model_py, repo_root=repo.root)  # writes model.urdf + assets/ here

    @app.get("/api/records/{record_id}/turn/{turn}/files/{path:path}")
    def get_turn_file(record_id: str, turn: int, path: str) -> FileResponse:
        if not store.exists(record_id):
            raise HTTPException(404, "no such record")
        turn_dir = repo.layout.record_dir(record_id) / "turns" / str(turn)
        if not (turn_dir / "model.urdf").exists():
            build_turn(record_id, turn, turn_dir)
        target = resolve_in_record(turn_dir, path)
        if target is None or not target.is_file():
            raise HTTPException(404, "no geometry at this turn")
        return FileResponse(target)

    @app.post("/api/records/{record_id}/stop")
    def stop_run(record_id: str) -> dict:
        if not store.exists(record_id):
            raise HTTPException(404, "no such record")
        lock = repo.layout.run_lock(record_id)
        signalled = locks.stop(lock)
        # SIGTERM skips the harness's finally, so flip status + drop the lock here.
        r = store.load(record_id)
        if r.status == "running":
            store.update_progress(r, status="failed")
        lock.unlink(missing_ok=True)
        return {"stopped": signalled}

    @app.post("/api/records/{record_id}/rating")
    def set_rating(record_id: str, body: dict) -> dict:
        if not store.exists(record_id):
            raise HTTPException(404, "no such record")
        return store.rate(record_id, body["rater"], int(body["score"])).model_dump()

    @app.delete("/api/records/{record_id}/rating")
    def clear_rating(record_id: str, rater: str) -> dict:
        if not store.exists(record_id):
            raise HTTPException(404, "no such record")
        return store.unrate(record_id, rater).model_dump()

    @app.get("/api/records/{record_id}/files/{path:path}")
    def get_file(record_id: str, path: str) -> FileResponse:
        target = resolve_in_record(repo.layout.record_dir(record_id), path)
        if target is None or not target.is_file():
            raise HTTPException(404, "no such file")
        return FileResponse(target)

    # Serve the built frontend at / (run `npm run build` in web/ first).
    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

    return app


def resolve_in_record(record_dir: Path, rel: str) -> Path | None:
    """Resolve rel under record_dir, or None if it escapes the dir (path traversal guard)."""
    base = record_dir.resolve()
    target = (base / rel).resolve()
    return target if base in target.parents or target == base else None


def _selftest() -> None:
    base = Path("data/records/x").resolve()
    assert resolve_in_record(base, "model.urdf") == base / "model.urdf"
    assert resolve_in_record(base, "../../secret") is None
    assert resolve_in_record(base, "/etc/passwd") is None
    print("ok: path traversal guard")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-open", action="store_true", help="don't auto-open the browser")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return
    import threading
    import webbrowser

    import uvicorn

    url = f"http://127.0.0.1:{args.port}"
    if WEB_DIST.is_dir():
        print(f"\n  viewer → {url}\n", flush=True)
        # ponytail: open once the server is up (~1s); skip with --no-open.
        if not args.no_open:
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    else:
        print(
            f"\n  api → {url}  (frontend not built: run `npm run build` in viewer/web)\n",
            flush=True,
        )
    uvicorn.run(create_app(args.root), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
