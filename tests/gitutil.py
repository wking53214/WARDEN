"""Small helpers for tests that need a real git repository."""

from __future__ import annotations

import subprocess
from pathlib import Path

_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/nonexistent",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True, env=_ENV)
    return done.stdout.strip()


def commit_all(root: Path, message: str = "initial") -> None:
    """Make `root` a git repository (if it is not one yet) with everything committed and nothing left over."""
    if not (Path(root) / ".git").exists():
        git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)
