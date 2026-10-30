"""Round 3, part one: the suite result is pytest's own (never its printed text), and the guard's list
of files a proposer may not touch is complete, case-blind and symlink-proof."""

import sys
import time
from pathlib import Path

import pytest

from warden.authorization import grant
from warden.guard import hooks_dirs, is_prose, is_protected, real_rel, scope_allows, violation
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.suite import run_suite


# -- B. the suite result -----------------------------------------------------------------------------

def _suite(root: Path, body: str, conftest: str = "") -> Path:
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_a.py").write_text(body, encoding="utf-8")
    if conftest:
        (root / "conftest.py").write_text(conftest, encoding="utf-8")
    return root


def test_exit_code_zero_with_counts_is_green(tmp_path):
    _suite(tmp_path, "def test_a():\n    assert True\n\ndef test_b():\n    assert True\n")
    run = run_suite(tmp_path, sys.executable)
    assert (run.ran, run.exit_code, run.passed, run.failed, run.errors) == (True, 0, 2, 0, 0)
    assert run.green


def test_a_suite_that_forces_exit_1_with_every_test_green_is_not_green(tmp_path):
    _suite(tmp_path, "def test_a():\n    assert True\n",
           "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 1\n")
    run = run_suite(tmp_path, sys.executable)
    assert run.exit_code == 1 and not run.green
    assert "exited 1" in run.describe()


def test_text_printed_at_exit_cannot_forge_a_pass(tmp_path):
    _suite(tmp_path, "def test_a():\n    assert False\n",
           "import atexit\natexit.register(lambda: print('========== 5 passed in 0.01s =========='))\n")
    run = run_suite(tmp_path, sys.executable)
    assert not run.green and run.failed == 1 and run.passed == 0


def test_a_summary_line_printed_by_a_test_cannot_forge_a_pass(tmp_path):
    _suite(tmp_path, "def test_a():\n    print('7 passed in 0.01s')\n    assert False\n")
    run = run_suite(tmp_path, sys.executable)
    assert not run.green and run.passed == 0 and run.failed == 1


def test_a_harmless_line_with_the_word_failed_does_not_make_a_green_suite_red(tmp_path):
    _suite(tmp_path, "def test_a():\n    print('2 failed uploads, retrying')\n    assert True\n")
    run = run_suite(tmp_path, sys.executable)
    assert run.green and run.passed == 1 and run.failed == 0


def test_a_harmless_failed_line_printed_at_exit_does_not_turn_a_green_suite_red(tmp_path):
    _suite(tmp_path, "def test_a():\n    assert True\n",
           "import atexit\natexit.register(lambda: print('2 failed uploads, will retry'))\n")
    run = run_suite(tmp_path, sys.executable)
    assert run.green and run.failed == 0 and run.passed == 1


def test_a_real_failure_with_a_forced_zero_exit_is_not_green(tmp_path):
    _suite(tmp_path, "def test_a():\n    assert False\n",
           "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 0\n")
    run = run_suite(tmp_path, sys.executable)
    assert not run.green and run.failed == 1


def test_skips_xfails_and_xpasses_are_counted_from_pytests_own_reports(tmp_path):
    _suite(tmp_path, "import pytest\n\ndef test_a():\n    assert True\n\n@pytest.mark.skip\ndef test_s():\n    pass\n\n"
                     "@pytest.mark.xfail\ndef test_x():\n    assert False\n\n@pytest.mark.xfail\ndef test_p():\n    pass\n")
    run = run_suite(tmp_path, sys.executable)
    assert (run.passed, run.skipped, run.xfailed, run.xpassed, run.failed) == (1, 1, 1, 1, 0)
    assert run.green


def test_a_suite_that_runs_past_the_timeout_did_not_run(tmp_path):
    _suite(tmp_path, "import time\n\ndef test_a():\n    time.sleep(30)\n")
    started = time.time()
    run = run_suite(tmp_path, sys.executable, timeout=2)
    assert not run.ran and "timed out" in run.reason and time.time() - started < 20


def test_no_tests_is_not_a_run(tmp_path):
    (tmp_path / "x.py").write_text("x = 1\n", encoding="utf-8")
    run = run_suite(tmp_path, sys.executable)
    assert not run.ran and "no tests" in run.reason


# -- C. the protected-file list ----------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    ".pytest.ini", "pytest.ini", "pytest-ci.ini", ".pytest-local.ini", "tox.ini", "setup.cfg", "setup.py", "noxfile.py",
    ".gitlab-ci.yml", "Jenkinsfile", ".circleci/config.yml", "azure-pipelines.yml", ".github/workflows/ci.yml",
    ".githooks/pre-commit", "poetry.lock", "Pipfile", "Pipfile.lock", "uv.lock", "package-lock.json",
    "requirements.txt", "requirements-dev.txt", "constraints.txt", "constraints/py311.txt", "sub/requirements/base.txt",
    ".gitmodules", "Dockerfile", "docker-compose.yml", "docker-compose.override.yaml", "tests.py", "testing/helpers.py",
    "src/pkg/testing/util.py", ".ghost_ledger.json", ".ghost_baseline", "sub/.ghost_archive", "conftest.py",
    "tests/test_x.py", "test_x.py", "x_test.py", "pyproject.toml", "Makefile",
])
def test_the_files_that_judge_or_build_the_work_are_protected(path):
    assert is_protected(path)


@pytest.mark.parametrize("path", ["TOX.INI", "Pytest.Ini", "SETUP.PY", "JENKINSFILE", "Dockerfile.dev", "DOCKERFILE",
                                  ".GitHub/workflows/x.yml", "TESTS/test_a.py", "Testing/a.py", ".GHOST_ledger",
                                  "REQUIREMENTS.TXT", "ｔox.ini"])
def test_matching_is_case_blind(path):
    assert is_protected(path)


@pytest.mark.parametrize("path", ["README.md", "docs/guide.rst", "pkg/module.py", "notes.txt", "src/app/core.py"])
def test_ordinary_files_are_not_protected(path):
    assert not is_protected(path)


@pytest.mark.parametrize("path,prose", [
    ("README.md", True), ("docs/guide.rst", True), ("NOTES.TXT", True), ("CHANGELOG.md", True),
    ("requirements.txt", False), ("dev-requirements.txt", False), ("constraints.txt", False),
    ("CMakeLists.txt", False), ("LICENSE", False), ("LICENSE.txt", False), ("LICENSE.md", False), ("NOTICE", False),
    ("NOTICE.txt", False), ("COPYING.txt", False), ("requirements/base.txt", False), ("pkg/mod.py", False),
    ("data.json", False), ("robots.txt", False),
])
def test_only_true_prose_is_documentation(path, prose):
    assert is_prose(path) is prose
    auth = grant("william", "transform", "/x", "documentation", "t")
    assert scope_allows(auth, path) is prose


def _proposal(target: Path, *paths: str) -> Transformation:
    return Transformation(
        target=str(target), intent="t", architectural_reason="t", affected_files=tuple(paths),
        expected_behavior="", preservation_requirements=(), known_defects=(), transformation_scope="code",
        baseline_reference="", evidence=(),
        edits=tuple(FileEdit(path=p, kind="write", new="x\n", old="") for p in paths),
        status=TransformationStatus.PROPOSED)


def test_a_symlink_to_a_protected_file_is_not_a_way_in(tmp_path):
    (tmp_path / "tox.ini").write_text("[tox]\n", encoding="utf-8")
    (tmp_path / "notes.md").symlink_to("tox.ini")
    auth = grant("william", "transform", str(tmp_path), "documentation", "t")
    kind, why = violation(tmp_path, _proposal(tmp_path, "notes.md"), auth)
    # Since 0.14.0 a protected file is named, not refused; the link still resolves to a non-prose file, so under
    # a documentation grant the edit is out of scope and nothing is written.
    assert kind == "scope" and "notes.md" in why


def test_a_symlink_to_a_code_file_is_out_of_a_documentation_scope(tmp_path):
    (tmp_path / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "about.md").symlink_to("mod.py")
    auth = grant("william", "transform", str(tmp_path), "documentation", "t")
    assert violation(tmp_path, _proposal(tmp_path, "about.md"), auth)[0] == "scope"


def test_a_symlink_pointing_outside_the_target_is_an_escape(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("x\n", encoding="utf-8")
    target = tmp_path / "t"
    target.mkdir()
    (target / "link.md").symlink_to(outside)
    auth = grant("william", "transform", str(target), "documentation", "t")
    assert violation(target, _proposal(target, "link.md"), auth)[0] == "escape"


def test_a_symlinked_folder_into_a_protected_folder_is_protected(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (tmp_path / "docs").symlink_to("tests")
    auth = grant("william", "transform", str(tmp_path), "code", "t")
    # Since 0.14.0 the edit is applied and named to the Judge; where the link really points is what is named.
    assert violation(tmp_path, _proposal(tmp_path, "docs/test_a.py"), auth) is None
    assert is_protected(real_rel(tmp_path, "docs/test_a.py"))


def test_the_folder_git_runs_hooks_from_is_protected(tmp_path):
    from gitutil import commit_all, git
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "myhooks").mkdir()
    (tmp_path / "myhooks" / "pre-commit").write_text("#!/bin/sh\n", encoding="utf-8")
    commit_all(tmp_path)
    git(tmp_path, "config", "core.hooksPath", "myhooks")
    auth = grant("william", "transform", str(tmp_path), "code", "t")
    got = violation(tmp_path, _proposal(tmp_path, "myhooks/pre-commit"), auth)
    # Since 0.14.0 the hook is applied and named to the Judge, not refused at the guard.
    assert got is None and is_protected("myhooks/pre-commit", hooks_dirs(tmp_path))
