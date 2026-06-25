"""Per-record run lock: a file holding the PID of the harness process building it.

Crash-safe by construction. A normal exit removes the lock (the `hold` context
manager's finally). A dirty crash leaves it behind, but the PID inside lets us
distinguish a live run from a dead one via os.kill(pid, 0). Stale locks (no live
process) are reaped, flipping abandoned 'running' records to 'failed'.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path


def _alive(pid: int) -> bool:
    # ponytail: PIDs can be reused, so a recycled PID looks alive. Acceptable for a
    # local dev tool; add a start-time stamp to the lock if false positives bite.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, just owned by another user
    return True


@contextlib.contextmanager
def hold(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def is_active(path: Path) -> bool:
    """True if a live process currently holds this lock."""
    try:
        return _alive(int(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        return False


def stop(path: Path) -> bool:
    """SIGTERM the process holding this lock. Returns True if a live run was signalled.

    Default SIGTERM won't run the harness's `finally`, so the caller is responsible
    for flipping status + removing the lock (or letting reap_stale clean up).
    """
    try:
        pid = int(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return False
    if not _alive(pid):
        return False
    try:
        os.kill(pid, 15)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _demo() -> None:
    import tempfile

    p = Path(tempfile.mkdtemp()) / "run.lock"
    assert not is_active(p)  # no lock yet
    with hold(p):
        assert is_active(p)  # this process holds it
    assert not is_active(p)  # released on exit
    p.write_text("999999999", encoding="utf-8")  # dead PID
    assert not is_active(p)
    print("ok: lock lifecycle + stale detection")


if __name__ == "__main__":
    _demo()
