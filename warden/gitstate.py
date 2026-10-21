"""What git says about a folder, asked in a way that cannot change it or run its code.

Used for three things: the dirty-folder policy (a run refuses to start on uncommitted work),
the place the run's lock and journal live (inside the repository's own git folder, so a different
TMPDIR cannot lose them), and the `dirty` flag in the `versions` report.

Every call:
  - drops GIT_* variables from the environment, so a stray GIT_DIR cannot point git elsewhere,
  - passes --no-optional-locks, so asking never writes to the index,
  - turns off core.fsmonitor, which would otherwise run a program named in the repository's config.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .textio import clip

_TIMEOUT = 60


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _git(cwd: Path, *args: str) -> Optional[subprocess.CompletedProcess]:
    """Run git in `cwd`. None when git cannot be run at all (missing, timed out)."""
    cmd = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", *args]
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=_TIMEOUT,
                              env=_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


@dataclass(frozen=True)
class TreeState:
    """kind is one of: clean, dirty, not_git, unknown. `detail` is a plain sentence for dirty/unknown."""

    kind: str
    detail: str = ""
    changed: int = 0
    git_dir: Optional[Path] = None


def _has_git_ancestor(path: Path) -> bool:
    return any((p / ".git").exists() for p in (path, *path.parents))


def absolute_git_dir(path: Path) -> Optional[Path]:
    """The repository's git folder for a path inside a work tree, or None."""
    proc = _git(Path(path), "rev-parse", "--absolute-git-dir")
    if proc is None or proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    return Path(text) if text else None


def tree_state(path: Path, allow: tuple = ()) -> TreeState:
    """Whether `path` is inside a git work tree with anything uncommitted.

    `git status --porcelain` with untracked files included and ignored files left out. A stray
    index.lock is reported as unknown (another git process may be running, or one died). Paths named
    in `allow` (repository-relative file names) are not counted as uncommitted work.
    """
    path = Path(path).resolve()
    inside = _git(path, "rev-parse", "--is-inside-work-tree")
    if inside is None:
        if _has_git_ancestor(path):
            return TreeState("unknown", "git could not be run, so whether this folder has uncommitted work "
                                        "cannot be checked")
        return TreeState("not_git")
    if inside.returncode != 0:
        said = (inside.stderr or "").lower()
        if "not a git repository" in said:
            return TreeState("not_git")
        return TreeState("unknown", "git would not say whether this folder has uncommitted work "
                                    f"({clip((inside.stderr.strip().splitlines() or ['no reason given'])[-1], 160)})")
    if inside.stdout.strip() != "true":
        return TreeState("unknown", "this folder is inside a git folder (.git), not a work tree, so whether it has "
                                    "uncommitted work cannot be checked")
    gdir = absolute_git_dir(path)
    if gdir is not None and (gdir / "index.lock").exists():
        return TreeState("unknown", "git's index.lock exists (another git command is running, or one died); "
                                    "remove it if nothing is running, then run again", git_dir=gdir)
    status = _git(path, "status", "--porcelain")
    if status is None or status.returncode != 0:
        last = "" if status is None else (status.stderr.strip().splitlines() or ["no reason"])[-1]
        why = "git status failed" if status is None else clip(last, 160)
        return TreeState("unknown", f"git status could not be read ({why}), so uncommitted work cannot be ruled out",
                         git_dir=gdir)
    lines = [ln for ln in status.stdout.splitlines() if ln.strip() and ln[3:].strip().strip('"') not in allow]
    if lines:
        return TreeState("dirty", f"{len(lines)} path(s) have uncommitted changes", len(lines), gdir)
    return TreeState("clean", git_dir=gdir)


def is_dirty(path: Path) -> Optional[bool]:
    """True/False for a git work tree; None when it is not one or git cannot say."""
    state = tree_state(path)
    return {"dirty": True, "clean": False}.get(state.kind)


def hooks_path(path: Path) -> Optional[Path]:
    """The folder git runs hooks from when core.hooksPath is set (all config levels), else None."""
    path = Path(path).resolve()
    proc = _git(path, "config", "--type=path", "--get", "core.hooksPath")
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    value = Path(proc.stdout.strip())
    if value.is_absolute():
        return value
    top = _git(path, "rev-parse", "--show-toplevel")
    base = Path(top.stdout.strip()) if top is not None and top.returncode == 0 and top.stdout.strip() else path
    return base / value
