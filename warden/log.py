"""Logging for Warden: the standard library's `logging`, written to stderr only.

Stdout belongs to the run record (one JSON document, `cns.run/1`) and nothing here may ever write
to it. Warden used to say nothing about its own seams, so a run that went wrong could only be read
from the final record. These loggers say what happened at the seams, in order: a seat was loaded,
an instrument (SWIZZLE, Ghost, ASSAY grading, the target's suite) was run and what it returned, a
verdict was reached and the exit code that goes with it.

Levels, quietest first:

  WARNING  (the default)  only things that deserve to be seen on every run
  INFO     (`-v`)         one line per seam: seats, instruments, verdict
  DEBUG    (`-vv`)        the same, with commands and detail

`WARDEN_LOG_LEVEL` sets the level by name (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) or by
number. `-v` / `--verbose` on a command raises the level to INFO, twice to DEBUG, and never lowers
what the environment asked for. A value that is not a level is reported once on stderr and ignored.

Library use stays quiet: importing Warden installs a `NullHandler` and nothing else. Only the
command line (`configure`) attaches a handler.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Mapping, Optional

ROOT = "warden"
ENV_VAR = "WARDEN_LOG_LEVEL"
DEFAULT_LEVEL = logging.WARNING
_FORMAT = "warden: %(levelname)s %(name)s: %(message)s"

logging.getLogger(ROOT).addHandler(logging.NullHandler())


class _StderrHandler(logging.Handler):
    """Writes to whatever `sys.stderr` is at the moment of the record, so a caller that swaps the
    stream (a test, a wrapper) is followed and stdout is never used."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
        except Exception:  # noqa: BLE001 - logging must never be the reason a governed run fails
            self.handleError(record)


def get(name: str) -> logging.Logger:
    """The logger for one Warden module, e.g. `get("cli")` is `warden.cli`."""
    return logging.getLogger(f"{ROOT}.{name}" if name else ROOT)


def parse_level(text: str) -> Optional[int]:
    """A level from its name or number; None when the text is neither."""
    text = text.strip()
    if text.isdigit():
        return int(text)
    value = logging.getLevelName(text.upper())
    return value if isinstance(value, int) else None


def resolve_level(verbose: int = 0, environ: Optional[Mapping[str, str]] = None) -> int:
    """The level for this run: the environment's, lowered to INFO or DEBUG by `-v` / `-vv`."""
    env = os.environ if environ is None else environ
    level = DEFAULT_LEVEL
    asked = env.get(ENV_VAR, "")
    if asked.strip():
        parsed = parse_level(asked)
        if parsed is None:
            print(f"warden: {ENV_VAR}={asked!r} is not a log level (use DEBUG, INFO, WARNING, ERROR "
                  "or CRITICAL); using WARNING.", file=sys.stderr)
        else:
            level = parsed
    if verbose >= 2:
        level = min(level, logging.DEBUG)
    elif verbose == 1:
        level = min(level, logging.INFO)
    return level


def configure(verbose: int = 0, environ: Optional[Mapping[str, str]] = None) -> int:
    """Attach the stderr handler (once) and set the level. Returns the level. Safe to call again."""
    logger = logging.getLogger(ROOT)
    level = resolve_level(verbose, environ)
    logger.setLevel(level)
    if not any(isinstance(h, _StderrHandler) for h in logger.handlers):
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)
    return level
