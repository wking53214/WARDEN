"""Run Warden's instruments (SWIZZLE, Ghost Tools, ASSAY grading) away from the target.

`python -m swizzle.cli` puts the current directory first on the import path.
If Warden is started from inside the target, a `swizzle/cli.py` planted in the
target would be run and believed. So every instrument runs with:

  - a fresh empty directory as its working directory,
  - `-P`, so Python does not add the working directory to the import path,
  - instrument roots turned into absolute paths first,
  - no inherited PYTHONPATH: an instrument sees its named roots and nothing else,
    so a sibling checkout on the caller's path cannot stand in for a missing root.

The target's own test suite is the one thing that still runs inside the
target. That cannot be avoided: running those tests is the point.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Optional, Sequence


def absolute(path: Optional[Path]) -> Optional[Path]:
    return None if path is None else Path(path).expanduser().resolve()


def instrument_env(*roots: Optional[Path]) -> dict:
    """The environment for an instrument: its named roots only.

    An inherited PYTHONPATH is dropped on purpose. If a root is missing, the
    instrument must fail, not quietly import a sibling checkout from the
    caller's path and report its result as if it came from the named root.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(str(absolute(r)) for r in roots if r is not None)
    return env


def run_instrument(cmd: Sequence[str], *, roots: Sequence[Optional[Path]], timeout: float,
                   extra_env: Optional[Mapping[str, str]] = None) -> subprocess.CompletedProcess:
    """Run `cmd` (python, then arguments) in an empty directory with `-P` added."""
    full = [cmd[0], "-P", *cmd[1:]]
    env = instrument_env(*roots)
    if extra_env:
        env.update(extra_env)
    with tempfile.TemporaryDirectory(prefix="warden-instrument-") as empty:
        return subprocess.run(full, capture_output=True, text=True, env=env, cwd=empty, timeout=timeout)
