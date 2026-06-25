"""Per-generation git history for model.py.

Uses a `.modelgit` git dir (NOT `.git`) inside the record dir so the parent repo never sees it as
a nested repo/gitlink. Best-effort: a failed snapshot logs and returns — it must never abort a run.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def _git(work: Path, *args: str) -> str:
    gitdir = work / ".modelgit"
    return subprocess.run(
        ["git", f"--git-dir={gitdir}", f"--work-tree={work}", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def snapshot(model_path: Path, message: str) -> None:
    """Commit the current model.py to the record's .modelgit history. Best-effort."""
    work = model_path.parent
    try:
        if not (work / ".modelgit").exists():
            _git(work, "init", "-q")
            _git(work, "config", "user.email", "agent@articraft")
            _git(work, "config", "user.name", "articraft")
        _git(work, "add", model_path.name)
        _git(work, "commit", "-q", "--allow-empty", "-m", message)
    except Exception as exc:  # ponytail: best-effort, swallow git errors
        log.warning("model.py git snapshot failed (%s): %s", message, exc)


_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's canonical empty tree


def diffs(model_path: Path) -> dict[str, str]:
    """Map each snapshot's commit subject -> unified diff vs its parent. {} if no history."""
    work = model_path.parent
    if not (work / ".modelgit").exists():
        return {}
    try:
        log_out = _git(work, "log", "--reverse", "--format=%H %s")
        out: dict[str, str] = {}
        prev = _EMPTY_TREE
        for line in log_out.splitlines():
            sha, _, subject = line.partition(" ")
            out[subject] = _git(work, "diff", prev, sha, "--", model_path.name)
            prev = sha
        return out
    except Exception as exc:  # ponytail: best-effort, swallow git errors
        log.warning("model.py git diff failed: %s", exc)
        return {}


def model_at(model_path: Path, turn: int) -> str | None:
    """The model.py text as of the 'turn N' snapshot, or None if there's no such commit."""
    work = model_path.parent
    if not (work / ".modelgit").exists():
        return None
    try:
        log_out = _git(work, "log", "--format=%H %s")
        want = f"turn {turn}"
        for line in log_out.splitlines():
            sha, _, subject = line.partition(" ")
            if subject == want:
                return _git(work, "show", f"{sha}:{model_path.name}")
        return None
    except Exception as exc:  # ponytail: best-effort, swallow git errors
        log.warning("model.py read-at-turn %d failed: %s", turn, exc)
        return None


def _demo() -> None:
    import tempfile

    model = Path(tempfile.mkdtemp()) / "model.py"
    assert diffs(model) == {}  # no history yet
    model.write_text("x = 1\n")
    snapshot(model, "seed")
    model.write_text("x = 2\n")
    snapshot(model, "turn 1")
    d = diffs(model)
    assert list(d) == ["seed", "turn 1"], d  # one diff per snapshot, in order
    assert "+x = 1" in d["seed"]
    assert "-x = 1" in d["turn 1"] and "+x = 2" in d["turn 1"]
    assert model_at(model, 1) == "x = 2\n"  # read model.py at a past turn
    assert model_at(model, 99) is None  # no such turn
    print("ok: snapshot + per-turn diff roundtrip")


if __name__ == "__main__":
    _demo()
