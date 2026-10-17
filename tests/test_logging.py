"""Logging goes to stderr only, at the seams, and never into the JSON on stdout."""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from warden import log

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("env,verbose,expected", [
    ({}, 0, logging.WARNING),
    ({}, 1, logging.INFO),
    ({}, 2, logging.DEBUG),
    ({"WARDEN_LOG_LEVEL": "debug"}, 0, logging.DEBUG),
    ({"WARDEN_LOG_LEVEL": "ERROR"}, 1, logging.INFO),     # -v lowers the level, never raises it
    ({"WARDEN_LOG_LEVEL": "INFO"}, 0, logging.INFO),
    ({"WARDEN_LOG_LEVEL": "10"}, 0, 10),
])
def test_the_level_comes_from_the_environment_and_verbose(env, verbose, expected):
    assert log.resolve_level(verbose, env) == expected


def test_a_level_that_is_not_one_is_said_once_and_ignored(capsys):
    assert log.resolve_level(0, {"WARDEN_LOG_LEVEL": "LOUD"}) == logging.WARNING
    err = capsys.readouterr()
    assert "not a log level" in err.err and err.out == ""


def test_configure_is_idempotent_and_follows_the_current_stderr(capsys):
    logger = logging.getLogger("warden")
    before = len(logger.handlers)
    log.configure(1, {})
    log.configure(1, {})
    assert len(logger.handlers) <= before + 1
    log.get("probe").info("seam reached")
    out = capsys.readouterr()
    assert "seam reached" in out.err and out.out == ""
    log.configure(0, {})
    log.get("probe").info("quiet now")
    assert "quiet now" not in capsys.readouterr().err


def test_importing_warden_installs_no_visible_handler():
    code = ("import logging, warden; h = logging.getLogger('warden').handlers; "
            "print([type(x).__name__ for x in h])")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert done.stdout.strip() == "['NullHandler']"


def _cli(args, env=None):
    import os
    environment = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    environment.update(env or {})
    return subprocess.run([sys.executable, "-m", "warden.cli", *args], capture_output=True, text=True,
                          env=environment, cwd=str(REPO_ROOT))


def test_verbose_logs_the_seams_on_stderr_and_stdout_stays_one_json_document(tmp_path):
    missing = tmp_path / "nope"
    quiet = _cli(["tagteam", str(missing)])
    loud = _cli(["tagteam", str(missing), "-vv"])
    for done in (quiet, loud):
        assert done.returncode == 2
        assert json.loads(done.stdout)["decision"] == "USAGE_ERROR"
    assert "INFO" not in quiet.stderr and "DEBUG" not in quiet.stderr
    assert "warden: INFO warden.cli: stopped before a run: USAGE_ERROR (exit 2)" in loud.stderr
    assert "warden: DEBUG warden.cli:" in loud.stderr
    assert "INFO" not in loud.stdout


def test_the_environment_variable_alone_turns_logging_on(tmp_path):
    done = _cli(["tagteam", str(tmp_path / "nope")], env={"WARDEN_LOG_LEVEL": "INFO"})
    assert "warden.cli: stopped before a run" in done.stderr
    assert json.loads(done.stdout)["decision"] == "USAGE_ERROR"


def test_a_governed_run_logs_seat_instrument_and_verdict_seams(tmp_path):
    from gitutil import commit_all
    from test_honest_exit_codes import SEATS, _repo
    target = _repo(tmp_path / "t")
    commit_all(target)
    seats = tmp_path / "seats"
    seats.mkdir()
    (seats / "exit_seats.py").write_text(SEATS, encoding="utf-8")
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    done = _cli(["tagteam", str(target), "--from-ghost", str(findings), "--drafter", "exit_seats:Once",
                 "--judge", "exit_seats:Judge", "--authorize", "william", "--reason", "log test", "-v"],
                env={"PYTHONPATH": f"{REPO_ROOT}:{seats}", "HOME": str(home), "XDG_STATE_HOME": str(home / "s")})
    assert done.returncode == 3, done.stderr[-500:]
    payload = json.loads(done.stdout)
    assert payload["decision"] == "ACCEPT_UNVERIFIED"
    for expected in ("seat loaded: exit_seats:Once", "seat loaded: exit_seats:Judge", "suite: running",
                     "verdict: ACCEPT_UNVERIFIED", "tagteam finished: decision=ACCEPT_UNVERIFIED exit=3",
                     "put back:"):
        assert expected in done.stderr, expected
