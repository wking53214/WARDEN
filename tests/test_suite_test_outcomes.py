"""The suite result names every test and its outcome, so the Judge can compare tests by name (JUDGE 0.16.0).

Counts alone cannot show a run that removed one passing test and added another: every count stays the same. The
pytest runner now carries `test_outcomes`, each test's id and outcome, on its result. These tests run real pytest on a
small project and check the names against the counts the same run reports.
"""

import sys
from collections import Counter

from warden import suite
from warden.suite import PytestSuiteRun, run_suite

BODY = '''import pytest


@pytest.fixture
def broken_setup():
    raise RuntimeError("setup")


@pytest.fixture
def broken_teardown():
    yield
    raise RuntimeError("teardown")


def test_pass():
    assert True


def test_fail():
    assert False


@pytest.mark.skip(reason="x")
def test_skip():
    pass


@pytest.mark.xfail
def test_xfail():
    assert False


@pytest.mark.xfail
def test_xpass():
    assert True


def test_setup_error(broken_setup):
    pass


def test_teardown_error(broken_teardown):
    pass
'''

WORDS = {"passed": "passed", "failed": "failed", "error": "errors", "skipped": "skipped", "xfailed": "xfailed",
         "xpassed": "xpassed"}


def _project(root, body=BODY, extra=None):
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_all.py").write_text(body, encoding="utf-8")
    for name, text in (extra or {}).items():
        (root / "tests" / name).write_text(text, encoding="utf-8")
    return root


def test_every_test_is_named_with_its_outcome(tmp_path):
    run = run_suite(_project(tmp_path), sys.executable)
    assert isinstance(run, PytestSuiteRun) and run.ran
    got = dict(run.test_outcomes)
    t = "tests/test_all.py::"
    assert got == {
        t + "test_pass": "passed", t + "test_fail": "failed", t + "test_skip": "skipped", t + "test_xfail": "xfailed",
        t + "test_xpass": "xpassed", t + "test_setup_error": "error", t + "test_teardown_error": "passed",
        t + "test_teardown_error [teardown]": "error",
    }


def test_the_names_agree_with_the_counts(tmp_path):
    broken = {"test_broken.py": "import nothing_here_at_all\n"}
    run = run_suite(_project(tmp_path, extra=broken), sys.executable)
    told = Counter(w for _, w in run.test_outcomes)
    for word, count in WORDS.items():
        assert told[word] == getattr(run, count), word
    assert ("tests/test_broken.py [collect]", "error") in run.test_outcomes


def test_one_test_swapped_for_another_keeps_the_counts_but_not_the_names(tmp_path):
    a = run_suite(_project(tmp_path / "a", "def test_one():\n    pass\n"), sys.executable)
    b = run_suite(_project(tmp_path / "b", "def test_two():\n    pass\n"), sys.executable)
    assert (a.passed, a.failed) == (b.passed, b.failed)
    assert a.test_outcomes != b.test_outcomes


def test_names_are_given_in_a_fixed_order(tmp_path):
    body = "def test_b():\n    pass\n\ndef test_a():\n    pass\n"
    run = run_suite(_project(tmp_path, body), sys.executable)
    assert [i for i, _ in run.test_outcomes] == sorted(i for i, _ in run.test_outcomes)


def test_a_report_without_names_still_gives_its_counts(tmp_path, monkeypatch):
    """An older plugin file, or one that gave up on names, is read as names not known, never as a failed run."""
    monkeypatch.setattr(suite, "_PLUGIN_SOURCE", suite._PLUGIN_SOURCE.replace(
        '"test_outcomes": sorted(_OUTCOMES.items()) if _NAMES["ok"] else None', '"test_outcomes": None'))
    run = run_suite(_project(tmp_path, "def test_one():\n    pass\n"), sys.executable)
    assert run.ran and run.passed == 1 and run.test_outcomes is None


def test_too_many_tests_gives_no_names_rather_than_some(tmp_path, monkeypatch):
    monkeypatch.setattr(suite, "_PLUGIN_SOURCE", suite._PLUGIN_SOURCE.replace("_MAX_NAMED = 100000", "_MAX_NAMED = 2"))
    body = "import pytest\n\n@pytest.mark.parametrize('n', range(3))\ndef test_n(n):\n    pass\n"
    run = run_suite(_project(tmp_path, body), sys.executable)
    assert run.ran and run.passed == 3 and run.test_outcomes is None
