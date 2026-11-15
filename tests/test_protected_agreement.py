"""Warden protects at least what the Judge treats as test or build material, so the two lists cannot drift apart.

Warden names its protected paths to the Judge (`judging_files_touched`) and the Judge adds its own list to them, so a path
only one of them knows is still held. This test keeps Warden's list from falling behind the Judge's anyway, because the
Judge may be run on evidence from another governor. The Judge's `hooks/` folder is left out on purpose: Warden protects the
folder git is told to use (`core.hooksPath`) and not every folder called hooks.
"""

import pytest

from warden import guard

#: Paths each of which is a test, a test setting, a build file or a file Python runs at start-up. Written out here so this
#: file needs no Judge to say what Warden must protect.
MUST_BE_PROTECTED = (
    "conftest.py", "pkg/conftest.py", "sitecustomize.py", "usercustomize.py", "x.pth", "test.py", "tests.py",
    "testfoo.txt", "test_data.txt", ".gitattributes", "package.json", "__tests__/a.js", "githooks/pre-commit",
    ".git-hooks/pre-commit", ".githooks/pre-commit", "pytest.ini", "tox.ini", "setup.py", "pyproject.toml",
    "requirements-dev.txt", "poetry.lock", "Dockerfile", ".github/workflows/x.yml", "tests/data.json",
    "tests/helpers.py", "pkg/test_x.py", "pkg/x_test.py",
)


@pytest.mark.parametrize("path", MUST_BE_PROTECTED)
def test_the_path_is_protected(path):
    assert guard.is_protected(path), f"{path} decides whether a change is acceptable, or how it is built and run"


def test_everything_the_judge_protects_by_name_is_protected_here_too():
    seat = pytest.importorskip("judge.seat")
    probes = sorted(seat._JUDGING_NAMES) + [f"{d}/x.txt" for d in sorted(seat._JUDGING_DIRS) if d != "hooks"]
    probes += ["pkg/test_x.py", "pkg/x_test.py", "testfoo.txt", "pytest.ini", ".pytest.ini", "requirements-dev.txt",
               "constraints.in", "a.lock", "a.pth", "Dockerfile.dev", "x.dockerfile", ".ghost_baseline.json",
               "docker-compose.override.yml"]
    missing = [p for p in probes if not guard.is_protected(p)]
    assert not missing, f"the Judge holds these and Warden does not name them: {missing}"
