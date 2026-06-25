"""Render a square, low-res thumbnail of a compiled record by driving the built
web viewer headless. Reuses the React/Three.js renderer (no second renderer to
maintain) via Playwright; the app's ?snapshot=1 mode strips all chrome and flags
`document.body.dataset.ready` once the model is framed.

Best-effort: returns None (and logs) if the frontend isn't built or Playwright
isn't installed, so a compile never fails for want of a thumbnail.

Self-check: uv run python -m viewer.thumbnail <record_id> [--root .]
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

from .server import WEB_DIST, create_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def render_thumbnail(record_id: str, *, root: Path | str = ".", size: int = 128) -> Path | None:
    """Write assets/thumb.png (size×size) under the record dir. None if unavailable."""
    if not WEB_DIST.is_dir():
        print("thumbnail: frontend not built (run `npm run build` in viewer/web) — skipping")
        return None
    try:
        import uvicorn
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        print(
            f"thumbnail: {e.name} not installed — skipping (`uv sync` + `playwright install chromium`)"
        )
        return None

    from storage.repo import Repo

    repo = Repo(root)
    out = repo.layout.assets_dir(record_id) / "thumb.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(root), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _wait_until_serving("127.0.0.1", port)
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader"])
            # Square viewport → square crop for free; small size keeps the asset tiny.
            page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
            page.goto(f"http://127.0.0.1:{port}/?record={record_id}&snapshot=1")
            page.wait_for_selector("body[data-ready='1']", state="attached", timeout=30_000)
            page.locator("canvas").screenshot(path=str(out))
            browser.close()
    except Exception as e:  # headless GL flakes; a missing thumbnail is non-fatal
        print(f"thumbnail: render failed — {e}")
        return None
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    return out if out.exists() else None


def _wait_until_serving(host: str, port: int, timeout: float = 10.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError("thumbnail server did not start")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("record_id")
    ap.add_argument("--root", default=".")
    ap.add_argument("--size", type=int, default=128)
    args = ap.parse_args()
    path = render_thumbnail(args.record_id, root=args.root, size=args.size)
    if path is None:
        raise SystemExit("no thumbnail produced")
    # Self-check: valid PNG, square, non-empty. Parse IHDR — no image lib needed.
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    w = int.from_bytes(data[16:20], "big")
    h = int.from_bytes(data[20:24], "big")
    assert w == h, f"not square: {w}x{h}"
    assert len(data) > 0
    print(f"ok: {path} ({w}x{h}, {len(data)}B)")
