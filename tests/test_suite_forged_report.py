"""A suite cannot report itself green when pytest's own printed summary says it failed.

The report file is written by a plugin inside the same process as the code under test, so code under test that reads the
environment variables Warden hands it can write a report of its own. Printed text is never used to approve a run, but it can
doubt one: pytest prints its own summary, and a report that lists no failure beside a summary that counts some is not believed.
This does not stop a forger that also silences pytest's output; README says so.
"""

import sys
from pathlib import Path

from warden.suite import _printed_failures, run_suite

FORGER = '''import atexit, json, os
VALUE = 2


def _forge():
    path, nonce = os.environ.get("WARDEN_SUITE_REPORT"), os.environ.get("WARDEN_SUITE_NONCE")
    with open(path, "w") as handle:
        json.dump({"nonce": nonce, "exitstatus": 0, "collected": 1, "passed": 1, "failed": 0, "errors": 0,
                   "skipped": 0, "xfailed": 0, "xpassed": 0}, handle)
    os._exit(0)


atexit.register(_forge)
'''
OBFUSCATED = '''import os as _o, json as _j
VALUE = 2
_a = __import__("at" + "exit")


def _go():
    env = {k: v for k, v in _o.environ.items() if k.startswith("WAR" + "DEN_SUITE_")}
    p = [v for k, v in env.items() if k.endswith("REPORT")][0]
    n = [v for k, v in env.items() if k.endswith("NONCE")][0]
    with open(p, "w") as h:
        _j.dump({"nonce": n, "exitstatus": 0, "collected": 1, "passed": 1, "failed": 0, "errors": 0,
                 "skipped": 0, "xfailed": 0, "xpassed": 0}, h)
    getattr(_o, "_" + "ex" + "it")(0)


_a.register(_go)
'''
TEST = "from pkg import VALUE\n\n\ndef test_value():\n    assert VALUE == 1\n"


def _repo(root: Path, module: str) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text(module, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_pkg.py").write_text(TEST, encoding="utf-8")
    return root


def test_a_forged_report_beside_a_printed_failure_is_not_believed(tmp_path):
    run = run_suite(_repo(tmp_path, FORGER), sys.executable)
    assert not run.ran and "report is not believed" in run.reason, run.describe()


def test_an_obfuscated_forger_that_leaves_the_printed_summary_alone_is_not_believed_either(tmp_path):
    run = run_suite(_repo(tmp_path, OBFUSCATED), sys.executable)
    assert not run.ran and "report is not believed" in run.reason, run.describe()


def test_an_honest_failing_suite_is_still_red_with_its_failure_named(tmp_path):
    run = run_suite(_repo(tmp_path, "VALUE = 2\n"), sys.executable)
    assert run.ran and run.failed == 1 and not run.green and run.failed_ids


def test_an_honest_passing_suite_is_still_green(tmp_path):
    run = run_suite(_repo(tmp_path, "VALUE = 1\n"), sys.executable)
    assert run.ran and run.green and run.passed == 1


def test_harmless_text_about_failures_does_not_turn_a_green_suite_red(tmp_path):
    root = _repo(tmp_path, "VALUE = 1\n")
    (root / "tests" / "test_talk.py").write_text(
        "def test_talk(capsys):\n    print('2 failed uploads, retrying')\n    print('3 failed in the queue')\n", encoding="utf-8")
    run = run_suite(root, sys.executable)
    assert run.ran and run.green, run.describe()


def test_only_a_pytest_summary_line_counts_as_a_printed_failure():
    assert _printed_failures("1 failed, 4 passed in 0.12s\n") == 1
    assert _printed_failures("=== 2 failed, 1 error in 3.00s ===\n") == 3
    assert _printed_failures("5 passed in 0.01s\n") == 0
    assert _printed_failures("2 failed uploads\n3 failed in the queue\n") == 0
    assert _printed_failures("") == 0
