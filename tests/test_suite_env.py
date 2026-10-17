"""The target's suite is handed the caller's environment without the credentials in it."""

import sys
import textwrap
from pathlib import Path

import pytest

from warden import isolation
from warden.suite import run_suite


def test_credential_names_are_withheld_and_ordinary_ones_kept():
    env = isolation.suite_env({
        "PATH": "/usr/bin", "HOME": "/h", "PYTHONPATH": "/siblings", "LANG": "C", "AUTHOR": "me",
        "GITHUB_TOKEN": "t", "GH_TOKEN": "t", "MY_API_KEY": "k", "API_KEY": "k", "DB_PASSWORD": "p",
        "AWS_ACCESS_KEY_ID": "a", "AWS_REGION": "r", "ANTHROPIC_API_KEY": "k", "OPENAI_ORG": "o",
        "SSH_AUTH_SOCK": "/s", "NPM_TOKEN": "n", "CARGO_REGISTRIES_X_TOKEN": "c", "client_secret": "s",
    })
    assert set(env) == {"PATH", "HOME", "PYTHONPATH", "LANG", "AUTHOR"}


def test_passthrough_is_an_explicit_opt_in():
    env = isolation.suite_env({"GITHUB_TOKEN": "t", "PATH": "/p", isolation.SUITE_ENV_PASSTHROUGH: "1"})
    assert env["GITHUB_TOKEN"] == "t"


def test_the_withheld_names_are_logged_without_their_values(caplog):
    with caplog.at_level("DEBUG", logger="warden.isolation"):
        isolation.suite_env({"GITHUB_TOKEN": "hunter2-secret", "PATH": "/p"})
    assert "GITHUB_TOKEN" in caplog.text and "hunter2" not in caplog.text


def test_a_real_suite_never_sees_the_callers_token(tmp_path: Path, monkeypatch):
    (tmp_path / "test_env.py").write_text(textwrap.dedent('''
        import os

        def test_no_credentials():
            assert "WARDEN_TEST_SECRET_TOKEN" not in os.environ
            assert os.environ.get("WARDEN_TEST_ORDINARY") == "kept"
    '''), encoding="utf-8")
    monkeypatch.setenv("WARDEN_TEST_SECRET_TOKEN", "do-not-leak")
    monkeypatch.setenv("WARDEN_TEST_ORDINARY", "kept")
    run = run_suite(tmp_path, sys.executable, 120, "pytest")
    assert run.ran and run.green, run.describe()


def test_a_suite_that_needs_the_credential_can_opt_in(tmp_path: Path, monkeypatch):
    (tmp_path / "test_env.py").write_text(
        'import os\n\ndef test_has_it():\n    assert os.environ["WARDEN_TEST_SECRET_TOKEN"] == "x"\n',
        encoding="utf-8")
    monkeypatch.setenv("WARDEN_TEST_SECRET_TOKEN", "x")
    assert not run_suite(tmp_path, sys.executable, 120, "pytest").green
    monkeypatch.setenv(isolation.SUITE_ENV_PASSTHROUGH, "1")
    assert run_suite(tmp_path, sys.executable, 120, "pytest").green


def test_a_hung_suite_is_cut_off_and_counts_as_not_run(tmp_path: Path):
    (tmp_path / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(30)\n", encoding="utf-8")
    run = run_suite(tmp_path, sys.executable, 3, "pytest")
    assert not run.ran and "timed out" in run.reason


@pytest.mark.parametrize("name", ["PATH", "HOME", "PYTHONPATH"])
def test_the_names_a_suite_needs_are_never_matched(name):
    assert not isolation._SECRET_NAME.search(name)
