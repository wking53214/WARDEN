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

import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Mapping, Optional, Sequence

logger = logging.getLogger("warden.isolation")

#: Environment variables that carry credentials. The target's suite is the target's code, run by
#: Warden on a person's machine; it is handed none of these, so a hostile or careless suite cannot
#: read the caller's tokens from its environment. Cheap, partial hardening, not a sandbox.
_SECRET_NAME = re.compile(
    r"(^|_)(TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|CREDENTIALS?|API_?KEY|PRIVATE_KEY|ACCESS_KEY|AUTH)(_|$)"
    r"|^(AWS|ANTHROPIC|OPENAI|GOOGLE_APPLICATION|AZURE|TWINE|NPM)_"
    r"|^SSH_AUTH_SOCK$|^SSH_AGENT_PID$|^GIT_ASKPASS$",
    re.IGNORECASE,
)
#: Set to 1 to hand the suite the full environment (a suite that really needs a credential).
SUITE_ENV_PASSTHROUGH = "WARDEN_SUITE_ENV_PASSTHROUGH"


def suite_env(environ: Optional[Mapping[str, str]] = None) -> dict:
    """The environment for the target's own test suite: the caller's, without credential-bearing names.

    `PYTHONPATH` is kept on purpose: a suite that imports sibling checkouts needs it, and the
    suite is the one thing that has to see the caller's setup. What is removed is listed at DEBUG
    (names only, never values). `WARDEN_SUITE_ENV_PASSTHROUGH=1` keeps everything.
    """
    env = dict(os.environ if environ is None else environ)
    if env.get(SUITE_ENV_PASSTHROUGH) == "1":
        logger.warning("%s=1: the target's suite is given the full environment, credentials included",
                       SUITE_ENV_PASSTHROUGH)
        return env
    dropped = sorted(name for name in env if _SECRET_NAME.search(name) and name != SUITE_ENV_PASSTHROUGH)
    for name in dropped:
        del env[name]
    if dropped:
        logger.debug("suite environment: withheld %d variable(s): %s", len(dropped), ", ".join(dropped))
    return env


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
    logger.debug("instrument: %s (timeout %ss)", " ".join(full), timeout)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="warden-instrument-") as empty:
        try:
            proc = subprocess.run(full, capture_output=True, text=True, env=env, cwd=empty, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.info("instrument %s did not finish after %.1fs: %s", _label(full), time.monotonic() - started,
                        type(exc).__name__)
            raise
    logger.info("instrument %s exited %s in %.1fs", _label(full), proc.returncode, time.monotonic() - started)
    return proc


def _label(cmd: Sequence[str]) -> str:
    """A short name for a command in a log line: the module and its first word, e.g. `swizzle.cli prove`."""
    words = list(cmd)
    if "-m" in words and words.index("-m") + 1 < len(words):
        at = words.index("-m")
        return " ".join(words[at + 1: at + 3])
    return Path(words[0]).name
