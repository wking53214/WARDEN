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

`python -m pytest -q -p no:cacheprovider` in the target's own directory, with
the target's own configuration. For a Rust project (a Cargo.toml and no Python
test setup) it runs `cargo test` instead; see `_run_cargo`. It only runs after
a human has authorized a write, because running a repository's tests runs that
repository's code.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from cns.suite import SuiteRun  # the shared row: cns 1.9.0

from .isolation import suite_env
from .textio import clip

logger = logging.getLogger("warden.suite")

#: pytest's exit code when it collected nothing.
_NO_TESTS = 5

DEFAULT_TIMEOUT = 900.0

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


RUNNERS = ("auto", "pytest", "cargo")

#: Files whose presence at the top of the target mean its tests are Python's.
_PYTHON_TEST_MARKERS = ("pytest.ini", ".pytest.ini", "conftest.py", "tox.ini", "setup.cfg", "setup.py",
                        "pyproject.toml")


def detect_runner(target: Path) -> str:
    """`cargo` for a Rust project with no Python test setup, otherwise `pytest`.

    Python wins whenever both are present, so no project that ran before changes how it runs. A
    mixed project that wants Cargo says so with `--suite-runner cargo`.
    """
    root = Path(target)
    if not (root / "Cargo.toml").is_file():
        return "pytest"
    if any((root / name).is_file() for name in _PYTHON_TEST_MARKERS):
        return "pytest"
    for _here, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", "target", ".venv", "venv", "node_modules"}]
        if any(f.startswith("test_") and f.endswith(".py") or f.endswith("_test.py") for f in files):
            return "pytest"
    return "cargo"


def run_suite(target: Path, python: str, timeout: float = DEFAULT_TIMEOUT, runner: str = "auto") -> SuiteRun:
    """Run the target's own tests with the right runner and return what it reported.

    `runner` is `auto` (see `detect_runner`), `pytest` or `cargo`.
    """
    if runner not in RUNNERS:
        return SuiteRun(ran=False, reason=f"unknown suite runner {runner!r}")
    chosen = detect_runner(target) if runner == "auto" else runner
    logger.info("suite: running the target's own tests with %s (timeout %gs)", chosen, timeout)
    started = time.monotonic()
    if chosen == "cargo":
        run = _run_cargo(Path(target), timeout)
    else:
        run = _run_pytest(target, python, timeout)
    logger.info("suite: %s in %.1fs: %s", "ran" if run.ran else "did not run", time.monotonic() - started,
                run.describe())
    return run


def _run_pytest(target: Path, python: str, timeout: float = DEFAULT_TIMEOUT) -> SuiteRun:
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
        env = dict(suite_env(), PYTHONPYCACHEPREFIX=str(pyc), WARDEN_SUITE_REPORT=str(report_path),
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
                        reason=f"pytest left no result file (exit {code}): {clip(last, 160)}")
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


@dataclass(frozen=True)
class CargoSuiteRun(SuiteRun):
    """A SuiteRun measured by Cargo. It differs only in what it calls the runner when it describes itself."""

    def describe(self) -> str:
        text = super().describe()
        return text.replace("; pytest exited", "; cargo exited", 1)


#: What `cargo test` is asked to do. `--locked` keeps Cargo.lock as it is, so a build never rewrites a
#: file in the target. Unit tests, integration tests and examples are built; documentation tests are
#: not run, because their results cannot be read in the form below.
_CARGO_ARGS = ("test", "--locked", "--workspace", "--no-fail-fast", "--lib", "--bins", "--tests", "--examples",
               "--", "-Z", "unstable-options", "--format", "json", "--test-threads=1")


def _run_cargo(target: Path, timeout: float = DEFAULT_TIMEOUT) -> SuiteRun:
    """Run `cargo test` and read the test harness's own structured result, never its printed text.

    The harness prints one JSON line per suite with its pass, fail and ignore counts. Those lines
    are read, and Cargo's exit status must agree with them. A suite that prints text, or one test
    that fails, cannot be hidden by what the tests say: a failing test makes Cargo exit non-zero
    whatever was printed.

    Two things differ from the pytest runner, and the record should be honest about both:

      * The JSON output is a nightly feature of the test harness, so `RUSTC_BOOTSTRAP=1` is set for
        this run only. Cargo has no stable machine-readable test result.
      * There is no private file to carry a one-time code, as pytest has. A test that writes forged
        JSON straight to the process's output could inflate the pass count. It cannot turn a failing
        run green, because the exit status and the failure count must both be clean for that.

    Build output goes to a fresh temporary folder per run, so nothing stale from an earlier run can
    pass for a fresh build and nothing is left in the target's own tree.
    """
    with tempfile.TemporaryDirectory(prefix="warden-cargo-") as private:
        env = dict(suite_env(), RUSTC_BOOTSTRAP="1", CARGO_TARGET_DIR=str(Path(private) / "target"),
                   CARGO_TERM_COLOR="never", CARGO_INCREMENTAL="0")
        try:
            proc = subprocess.Popen(
                ["cargo", *_CARGO_ARGS], cwd=str(target), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, text=True, errors="replace", env=env, start_new_session=True)
        except OSError as exc:
            return SuiteRun(ran=False, reason=f"cargo could not run: {exc}")
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.communicate()
            return SuiteRun(ran=False, reason=f"cargo could not run: timed out after {timeout:g} seconds")
        except BaseException:
            _kill_group(proc)
            raise
        finally:
            _kill_group(proc)
        code = proc.returncode
    passed = failed = ignored = suites = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "suite" or event.get("event") not in ("ok", "failed"):
            continue
        counts = [n for n in (event.get(k) for k in ("passed", "failed", "ignored"))
                  if isinstance(n, int) and not isinstance(n, bool) and n >= 0]
        if len(counts) != 3:
            continue
        suites += 1
        passed, failed, ignored = passed + counts[0], failed + counts[1], ignored + counts[2]
    build_errors = stderr.count("error: could not compile")
    last = (stderr.strip().splitlines() or [f"exit {code}"])[-1]
    last = clip(last, 160)
    if suites == 0:
        return SuiteRun(ran=False, exit_code=code, reason=f"cargo reported no test results (exit {code}): {last}")
    if passed + failed == 0 and code == 0:
        return SuiteRun(ran=False, exit_code=code, reason="cargo ran no tests")
    reason = ""
    if code != 0 and not failed and not build_errors:
        reason = "the exit status says the run failed but no test is reported as failing"
    elif code != 0 and not failed:
        reason = "a test target did not build"
    elif code == 0 and failed:
        reason = "the exit status says the run passed but the report lists failures"
    return CargoSuiteRun(ran=True, passed=passed, failed=failed, errors=build_errors, skipped=ignored,
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
