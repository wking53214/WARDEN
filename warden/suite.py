"""Rule 7, the behavior-preservation gate: the target's own suite, before and after.

Elegant.md, Rule 7: "No beautification or fix commit merges without a green
automated suite." Until 2026-10-07 the tag team re-inspected with Ghost Tools
and attacked with the documentation-honesty oracle, and never ran the
target's tests. A transformation could therefore be ACCEPTED while breaking
the code it was beautifying. This module is the missing gate.

THE GATE

  before   the suite must run, collect at least one test, and be green.
           A suite that cannot protect behavior cannot license a change:
           "If the suite cannot protect invariants, add tests before
           changing behavior."
  after    no new failures or errors, and at least as many passes as before.

Anything else and the change is put back. The counts go into the notes so the
record says what was measured, not only the verdict.

WHAT IT RUNS

A Python target: `python -m pytest -q -p no:cacheprovider` in the target's own
directory, with the target's own configuration.

A Rust target (a Cargo.toml and no Python test setup): `cargo test --workspace
--no-fail-fast` in the target's directory. Green needs cargo's exit status 0,
at least one passing test, and no failing test, the same rule as pytest.
Rust's own summary lines ("test result: ok. N passed; ...") supply the counts.

It only runs after a human has authorized a write, because running a
repository's tests runs that repository's code.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: pytest's exit code when it collected nothing.
_NO_TESTS = 5

DEFAULT_TIMEOUT = 900.0

#: Files whose presence says a target's tests are pytest's. Checked before Cargo.toml, so a
#: repository with Python tests keeps the pytest path it always had.
_PYTEST_MARKERS = ("pytest.ini", "conftest.py", "tox.ini", "setup.cfg")

#: One libtest summary line per test binary (and per doc-test run): "test result: ok. 3 passed;
#: 0 failed; 1 ignored; ...". Cargo prints it after the tests run, so a test cannot print it
#: after the fact, but a test can print a line like it while it runs; see the note on run_cargo.
_CARGO_RESULT = re.compile(r"^test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", re.MULTILINE)

#: The pytest plugin Warden loads into the target's run. It counts every test outcome as pytest
#: reports it and writes them, with pytest's own exit status, to a file only Warden reads. Text
#: that the target's code prints is never read.
_PLUGIN_SOURCE = '''
import json, os

_COUNTS = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
_STATE = {"collected": 0}


def pytest_collection_finish(session):
    _STATE["collected"] = len(session.items)


def pytest_collectreport(report):
    if report.failed:
        _COUNTS["errors"] += 1
    elif report.skipped:
        _COUNTS["skipped"] += 1


def pytest_runtest_logreport(report):
    wasxfail = hasattr(report, "wasxfail")
    if report.when == "call":
        if report.passed:
            _COUNTS["xpassed" if wasxfail else "passed"] += 1
        elif report.failed:
            _COUNTS["failed"] += 1
        elif report.skipped:
            _COUNTS["xfailed" if wasxfail else "skipped"] += 1
    elif report.when == "setup":
        if report.failed:
            _COUNTS["errors"] += 1
        elif report.skipped:
            _COUNTS["skipped"] += 1
    elif report.when == "teardown" and report.failed:
        _COUNTS["errors"] += 1


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("WARDEN_SUITE_REPORT")
    if not path:
        return
    body = {"nonce": os.environ.get("WARDEN_SUITE_NONCE"), "exitstatus": int(exitstatus),
            "collected": _STATE["collected"], **_COUNTS}
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(body, handle)
    os.replace(tmp, path)
'''


@dataclass(frozen=True)
class SuiteRun:
    """One run of a target's suite, as pytest reported it."""

    ran: bool
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    reason: str = ""
    #: Tests marked as expected to fail that did fail, and ones that passed anyway.
    xfailed: int = 0
    xpassed: int = 0
    #: The runner's own exit status. None only for a SuiteRun made by hand. Green needs 0.
    exit_code: Optional[int] = None
    #: Which runner produced the result: "pytest" or "cargo".
    runner: str = "pytest"

    @property
    def green(self) -> bool:
        return (self.ran and self.exit_code in (None, 0)
                and self.passed > 0 and self.failed == 0 and self.errors == 0)

    def describe(self) -> str:
        if not self.ran:
            return f"did not run ({self.reason})"
        text = (f"{self.passed} passed, {self.failed} failed, {self.errors} errors, "
                f"{self.skipped} skipped, {self.xfailed} xfailed, {self.xpassed} xpassed")
        if self.exit_code not in (None, 0):
            text += f"; {self.runner} exited {self.exit_code}" + (f" ({self.reason})" if self.reason else "")
        return text


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def _read_report(path: Path, nonce: str) -> Optional[dict]:
    """The plugin's file, or None if it is missing, too big, or not what the plugin writes."""
    try:
        if path.stat().st_size > 1_000_000:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("nonce") != nonce:
        return None
    keys = ("exitstatus", "collected", "passed", "failed", "errors", "skipped", "xfailed", "xpassed")
    if not all(isinstance(data.get(k), int) and not isinstance(data.get(k), bool) and data[k] >= 0 for k in keys):
        return None
    return data


def runner_for(target: Path) -> str:
    """"pytest" or "cargo": Python test setup wins; a Rust-only target gets cargo."""
    if any((target / marker).is_file() for marker in _PYTEST_MARKERS):
        return "pytest"
    pyproject = target / "pyproject.toml"
    if pyproject.is_file() and "pytest" in pyproject.read_text(encoding="utf-8", errors="replace"):
        return "pytest"
    if any(target.glob("test_*.py")) or any((target / "tests").glob("test_*.py")):
        return "pytest"
    if (target / "Cargo.toml").is_file():
        return "cargo"
    return "pytest"


def _capture(argv: list, cwd: Path, env: dict, timeout: float):
    """Run one command in its own process group. Returns (exit code, stdout, stderr, "") or,
    when it could not run or ran past the timeout, (None, "", "", why). Anything it left running
    is killed."""
    try:
        proc = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True, errors="replace", env=env,
                                start_new_session=True)
    except OSError as exc:
        return None, "", "", f"could not start: {exc}"
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        proc.communicate()
        return None, "", "", f"timed out after {timeout:g} seconds"
    except BaseException:
        _kill_group(proc)
        raise
    finally:
        _kill_group(proc)
    return proc.returncode, stdout, stderr, ""


def run_cargo(target: Path, timeout: float = DEFAULT_TIMEOUT) -> SuiteRun:
    """Run a Rust target's tests with `cargo test --workspace --no-fail-fast`.

    Counts come from libtest's summary lines on stdout. Ignored tests are reported as skipped.
    There is no separate "errors" count in Rust: a test that cannot build stops the run with a
    nonzero exit, which is never green. Limit, stated plainly: a summary-shaped line printed by
    the target's own code could inflate the counts. It cannot turn a red run green, because green
    still needs cargo's exit status 0.
    """
    code, stdout, stderr, why = _capture(["cargo", "test", "--workspace", "--no-fail-fast"],
                                         target, dict(os.environ, CARGO_TERM_COLOR="never"), timeout)
    if code is None:
        return SuiteRun(ran=False, runner="cargo", reason=f"cargo could not run: {why}")
    totals = [tuple(int(n) for n in found) for found in _CARGO_RESULT.findall(stdout)]
    passed = sum(t[0] for t in totals)
    failed = sum(t[1] for t in totals)
    ignored = sum(t[2] for t in totals)
    if not totals:
        last = (stderr.strip().splitlines() or [f"exit {code}"])[-1]
        return SuiteRun(ran=False, runner="cargo", exit_code=code,
                        reason=f"cargo printed no test results (exit {code}): {last[:160]}")
    if passed + failed + ignored == 0:
        return SuiteRun(ran=False, runner="cargo", exit_code=code, reason="cargo collected no tests")
    reason = ""
    if code != 0 and not failed:
        reason = f"cargo exited {code} but no test is reported as failing"
    if "could not compile" in stderr:
        reason = (reason + "; " if reason else "") + "some tests did not build"
    return SuiteRun(ran=True, runner="cargo", passed=passed, failed=failed, skipped=ignored,
                    exit_code=code, reason=reason)


def run_suite(target: Path, python: str, timeout: float = DEFAULT_TIMEOUT, runner: Optional[str] = None) -> SuiteRun:
    """Run the target's tests with the runner its files call for (see `runner_for`)."""
    if (runner or runner_for(target)) == "cargo":
        return run_cargo(target, timeout)
    return run_pytest(target, python, timeout)


def run_pytest(target: Path, python: str, timeout: float = DEFAULT_TIMEOUT) -> SuiteRun:
    """Run the target's tests and read pytest's own result, never its printed text.

    The result is pytest's exit status plus a count file written by a plugin Warden loads (see
    `_PLUGIN_SOURCE`). Text the suite prints, at the end or at exit, is ignored, so a line reading
    "5 passed" cannot make a failing run look green and a harmless "2 failed uploads" cannot make a
    green one look red. Green needs exit status 0, at least one passing test, and no failed or
    errored test in the count file.

    Bytecode goes to a fresh directory per run. Python trusts a cached .pyc
    whose source has the same size and the same mtime second, so an edit
    made within a second of the "before" run (VALUE = 1 -> VALUE = 2) was
    invisible to the "after" run and a breaking change passed the gate.
    Measured on this module's own test, 2 failures in 3 runs, before this.
    """
    nonce = secrets.token_hex(16)
    with tempfile.TemporaryDirectory(prefix="warden-suite-") as private:
        private_dir = Path(private)
        plugin = f"_warden_suite_report_{secrets.token_hex(6)}"
        (private_dir / f"{plugin}.py").write_text(_PLUGIN_SOURCE, encoding="utf-8")
        report_path = private_dir / "report.json"
        pyc = private_dir / "pyc"
        pyc.mkdir()
        env = dict(os.environ, PYTHONPYCACHEPREFIX=str(pyc), WARDEN_SUITE_REPORT=str(report_path),
                   WARDEN_SUITE_NONCE=nonce)
        # The plugin's folder goes last, after everything the target set: its name is random, so nothing can shadow it.
        env["PYTHONPATH"] = os.pathsep.join([p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
                                            + [str(private_dir)])
        try:
            proc = subprocess.Popen(
                [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", plugin],
                cwd=str(target), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                text=True, errors="replace", env=env, start_new_session=True)
        except OSError as exc:
            return SuiteRun(ran=False, reason=f"pytest could not run: {exc}")
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.communicate()
            return SuiteRun(ran=False, reason=f"pytest could not run: timed out after {timeout:g} seconds")
        except BaseException:
            _kill_group(proc)
            raise
        finally:
            _kill_group(proc)  # anything the suite left running
        code = proc.returncode
        report = _read_report(report_path, nonce)
    if code == _NO_TESTS:
        return SuiteRun(ran=False, reason="pytest collected no tests", exit_code=code)
    if report is None:
        last = (stderr.strip().splitlines() or stdout.strip().splitlines() or [f"exit {code}"])[-1]
        return SuiteRun(ran=False, exit_code=code,
                        reason=f"pytest left no result file (exit {code}): {last[:160]}")
    reason = ""
    if report["exitstatus"] != code:
        reason = f"pytest's report said exit {report['exitstatus']} but the process exited {code}"
    elif code != 0 and not (report["failed"] or report["errors"]):
        reason = "the exit status says the run failed but no test is reported as failing"
    elif code == 0 and (report["failed"] or report["errors"]):
        reason = "the exit status says the run passed but the report lists failures"
    return SuiteRun(ran=True, passed=report["passed"], failed=report["failed"], errors=report["errors"],
                    skipped=report["skipped"], xfailed=report["xfailed"], xpassed=report["xpassed"],
                    exit_code=code, reason=reason)


def preserved(before: SuiteRun, after: SuiteRun) -> Optional[str]:
    """None if behavior is preserved by Rule 7's standard, else why not."""
    if not after.ran:
        return f"the suite did not run after the change ({after.reason})"
    if after.exit_code not in (None, 0):
        return f"the suite did not exit cleanly after the change ({after.describe()})"
    if after.failed or after.errors:
        return f"the change introduced failures ({after.describe()})"
    if after.passed < before.passed:
        return f"fewer tests pass after the change ({before.passed} -> {after.passed})"
    return None
