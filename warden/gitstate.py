"""What git says about a folder, asked in a way that cannot change it or run its code.

Used for three things: the dirty-folder policy (a run refuses to start on uncommitted work),
the place the run's lock and journal live (inside the repository's own git folder, so a different
TMPDIR cannot lose them), and the `dirty` flag in the `versions` report.

Every call:
  - drops GIT_* variables from the environment, so a stray GIT_DIR cannot point git elsewhere,
  - passes --no-optional-locks, so asking never writes to the index,
  - turns off core.fsmonitor, which would otherwise run a program named in the repository's config.

The question "is anything uncommitted" (`tree_state`) is asked more strictly still, because its answer is a trust
decision about code that is about to run. Git's answer otherwise depends on the asker's own configuration and on
flags in the index, and either can hide a change: a global `status.showUntrackedFiles=no`, a global
`core.excludesFile`, `core.fileMode=false`, and the index flags `assume-unchanged` and `skip-worktree`. So
`tree_state` runs git with no user or system configuration at all, says explicitly what to count, and refuses a
tracked file that carries either index flag. Only the repository's own `.gitignore` can still hide a file.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import tempfile
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


_empty_config_dir: Optional[Path] = None


def _empty_config() -> Path:
    """A folder with an empty git config file in it, made once per process and removed when it ends."""
    global _empty_config_dir
    if _empty_config_dir is None or not (_empty_config_dir / "gitconfig").is_file():
        folder = Path(tempfile.mkdtemp(prefix="warden-git-"))
        (folder / "gitconfig").write_text("", encoding="utf-8")
        atexit.register(shutil.rmtree, str(folder), True)
        _empty_config_dir = folder
    return _empty_config_dir


def _neutral_env() -> dict:
    """The environment with no user or system git configuration: the global file is an empty one, the system
    file is off, and HOME and XDG_CONFIG_HOME point at the empty folder for a git that predates GIT_CONFIG_GLOBAL."""
    folder = _empty_config()
    env = _env()
    env["HOME"] = env["XDG_CONFIG_HOME"] = str(folder)
    env["GIT_CONFIG_GLOBAL"] = env["GIT_CONFIG_SYSTEM"] = str(folder / "gitconfig")
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


#: What a status of uncommitted work must not be talked out of by configuration: every untracked file is listed (not
#: hidden by a global ignore file), submodules are not ignored, file stat is not trusted blindly, and a change of
#: mode bit counts.
_STRICT = ("-c", "core.excludesFile=", "-c", "core.ignoreStat=false", "-c", "core.fileMode=true")


def _git(cwd: Path, *args: str, neutral: bool = False) -> Optional[subprocess.CompletedProcess]:
    """Run git in `cwd`. None when git cannot be run at all (missing, timed out).

    `neutral` runs it with no user or system configuration (see the module note) and the strict settings."""
    cmd = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
           *(_STRICT if neutral else ()), *args]
    try:
        env = _neutral_env() if neutral else _env()
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=_TIMEOUT,
                              env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None


@dataclass(frozen=True)
class TreeState:
    """kind is one of: clean, dirty, not_git, unknown. `detail` is a plain sentence for dirty/unknown."""

    kind: str
    detail: str = ""
    changed: int = 0
    git_dir: Optional[Path] = None
    hidden: int = 0  #: of `changed`, the tracked files an index flag hides from status


def _has_git_ancestor(path: Path) -> bool:
    return any((p / ".git").exists() for p in (path, *path.parents))


def absolute_git_dir(path: Path, neutral: bool = False) -> Optional[Path]:
    """The repository's git folder for a path inside a work tree, or None."""
    proc = _git(Path(path), "rev-parse", "--absolute-git-dir", neutral=neutral)
    if proc is None or proc.returncode != 0:
        return None
    text = proc.stdout.strip()
    return Path(text) if text else None


def _hidden_flags(path: Path, allow: tuple) -> Optional[list]:
    """Tracked files whose index entry tells git to stop looking for changes: assume-unchanged (`git ls-files -v`
    prints a lowercase letter) or skip-worktree (`S`). `git status` reports nothing for them whatever they hold.
    None when git could not say."""
    proc = _git(path, "ls-files", "-v", "-z", "--full-name", "--", ":/", neutral=True)
    if proc is None or proc.returncode != 0:
        return None
    hidden = []
    for entry in proc.stdout.split("\0"):
        tag, _, name = entry.partition(" ")
        if (tag.islower() or tag == "S") and name not in allow:
            hidden.append(name)
    return hidden


def tree_state(path: Path, allow: tuple = ()) -> TreeState:
    """Whether `path` is inside a git work tree with anything uncommitted.

    `git status --porcelain` with every untracked file listed and ignored files left out, asked with no user or
    system git configuration (see the module note). A tracked file the index tells git not to look at
    (assume-unchanged, skip-worktree) counts as uncommitted work, since its changes would not show. A stray
    index.lock is reported as unknown (another git process may be running, or one died). Paths named in `allow`
    (repository-relative file names) are not counted as uncommitted work.
    """
    path = Path(path).resolve()
    inside = _git(path, "rev-parse", "--is-inside-work-tree", neutral=True)
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
    gdir = absolute_git_dir(path, neutral=True)
    if gdir is not None and (gdir / "index.lock").exists():
        return TreeState("unknown", "git's index.lock exists (another git command is running, or one died); "
                                    "remove it if nothing is running, then run again", git_dir=gdir)
    status = _git(path, "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none", neutral=True)
    if status is None or status.returncode != 0:
        last = "" if status is None else (status.stderr.strip().splitlines() or ["no reason"])[-1]
        why = "git status failed" if status is None else clip(last, 160)
        return TreeState("unknown", f"git status could not be read ({why}), so uncommitted work cannot be ruled out",
                         git_dir=gdir)
    lines = [ln for ln in status.stdout.splitlines() if ln.strip() and ln[3:].strip().strip('"') not in allow]
    hidden = _hidden_flags(path, allow)
    if hidden is None:
        return TreeState("unknown", "git would not list the index flags, so a file hidden from git status "
                                    "cannot be ruled out", git_dir=gdir)
    if hidden:
        said = (f"{len(lines)} path(s) have uncommitted changes, and " if lines else "") + (
            f"{len(hidden)} tracked file(s) are hidden from git status by an index flag (assume-unchanged or "
            f"skip-worktree), such as {clip(hidden[0], 80)}")
        return TreeState("dirty", said, len(lines) + len(hidden), gdir, len(hidden))
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
