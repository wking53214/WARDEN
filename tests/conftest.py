"""Run policy for this suite: with WARDEN_FAIL_ON_SKIP=1, a skipped test fails the run.

A skip is a check that did not run. A few tests skip when something they exercise is absent (the real Judge, an
ASSAY checkout for the live registry read, `cargo`); on a developer's machine that is a convenience, but in CI it
would let a broken integration go unseen. CI sets WARDEN_FAIL_ON_SKIP=1 and installs what those tests need, so
any skip there turns the run red and says which test and why. Without the variable nothing changes.
"""

from __future__ import annotations

import os

import pytest

_skipped: list[tuple[str, str]] = []


def _enforced() -> bool:
    return os.environ.get("WARDEN_FAIL_ON_SKIP") == "1"


def _note_skip(report) -> None:
    if report.skipped and not hasattr(report, "wasxfail"):
        longrepr = report.longrepr
        reason = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
        _skipped.append((report.nodeid, reason.removeprefix("Skipped: ")))


def pytest_runtest_logreport(report):
    _note_skip(report)


def pytest_collectreport(report):
    """A module-level `pytest.importorskip` skips at collection, not at run time."""
    _note_skip(report)


def pytest_terminal_summary(terminalreporter):
    if _enforced() and _skipped:
        terminalreporter.section("skipped tests fail this run (WARDEN_FAIL_ON_SKIP=1)", sep="!", red=True)
        for nodeid, reason in _skipped:
            terminalreporter.write_line(f"{nodeid}: {reason}")


def pytest_sessionfinish(session, exitstatus):
    if _enforced() and _skipped and exitstatus in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
