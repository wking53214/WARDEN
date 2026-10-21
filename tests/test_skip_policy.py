"""WARDEN_FAIL_ON_SKIP=1 makes a skipped test fail the run (tests/conftest.py); without it a skip is just a skip."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

CONFTEST = Path(__file__).with_name("conftest.py")


def _run(tmp_path, tests: str, enforce: bool):
    shutil.copy(CONFTEST, tmp_path / "conftest.py")
    (tmp_path / "test_x.py").write_text(tests, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "WARDEN_FAIL_ON_SKIP"}
    if enforce:
        env["WARDEN_FAIL_ON_SKIP"] = "1"
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                          capture_output=True, text=True, cwd=str(tmp_path), env=env, timeout=120)


SKIPS = "import pytest\n\ndef test_a():\n    pass\n\n@pytest.mark.skip(reason='needs the thing')\ndef test_b():\n    pass\n"


def test_a_skip_fails_the_run_when_enforced_and_names_the_test_and_why(tmp_path):
    done = _run(tmp_path, SKIPS, enforce=True)
    assert done.returncode == 1, done.stdout
    assert "test_x.py::test_b" in done.stdout and "needs the thing" in done.stdout


def test_an_importorskip_and_a_skipif_count_as_skips_too(tmp_path):
    done = _run(tmp_path, "import pytest\n\nx = pytest.importorskip('no_such_module_anywhere')\n\n"
                          "def test_a():\n    pass\n", enforce=True)
    assert done.returncode == 1 and "no_such_module_anywhere" in done.stdout
    done = _run(tmp_path, "import pytest\n\n@pytest.mark.skipif(True, reason='nope')\ndef test_a():\n    pass\n",
                enforce=True)
    assert done.returncode == 1 and "nope" in done.stdout


def test_a_skip_is_only_a_skip_when_not_enforced(tmp_path):
    assert _run(tmp_path, SKIPS, enforce=False).returncode == 0


def test_a_run_with_no_skips_passes_when_enforced(tmp_path):
    assert _run(tmp_path, "def test_a():\n    pass\n", enforce=True).returncode == 0


def test_an_expected_failure_is_not_a_skip(tmp_path):
    done = _run(tmp_path, "import pytest\n\n@pytest.mark.xfail(reason='known')\ndef test_a():\n    assert 0\n",
                enforce=True)
    assert done.returncode == 0, done.stdout


def test_a_failing_run_stays_failing_when_enforced(tmp_path):
    assert _run(tmp_path, "def test_a():\n    assert 0\n", enforce=True).returncode == 1

