"""A report nobody received is handled on purpose: the reader leaving keeps the earned exit code, and any other failed
delivery is said on stderr and is never exit 0.

Found by the round-6 audit: `warden tagteam ... | head -c0` printed a BrokenPipeError traceback and exited 1 where the
run had earned 6 (INCONCLUSIVE), with and without PYTHONUNBUFFERED=1; buffered, the interpreter's flush at exit made it
120. Rules, the same as JUDGE 0.4.9 documents:

* the reader of stdout went away (a broken pipe): nothing more is printed, the earned code stands;
* stdout is closed or the write fails for another reason (a full device): one plain line on stderr, no traceback, and a
  run that earned 0 exits 1, because an undelivered ACCEPT is not an ACCEPT. A non-zero code is kept.

No test opens /dev/full or any device node. The unwritable stream is a pipe whose reader is gone, a closed descriptor, or an
object whose write raises ENOSPC.
"""

import errno
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gitutil import commit_all

from warden import cli

ROOT = Path(__file__).resolve().parents[1]


def _target(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    (target / "m.py").write_text("V = 1\n", encoding="utf-8")
    commit_all(target)
    return target


def _run(args, *, stdout, unbuffered, close_fd1=False, cwd=None):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env["PYTHONPATH"] = str(ROOT)
    if unbuffered:
        env["PYTHONUNBUFFERED"] = "1"
    cmd = [sys.executable, "-m", "warden.cli", *args]
    if close_fd1:
        cmd = ["sh", "-c", 'exec "$@" >&-', "sh", *cmd]
    return subprocess.run(cmd, stdout=stdout, stderr=subprocess.PIPE, text=True, env=env, cwd=cwd, timeout=300)


def _gone_reader():
    """The write end of a pipe whose read end is already closed: the first write fails with EPIPE."""
    read_end, write_end = os.pipe()
    os.close(read_end)
    return write_end


@pytest.mark.parametrize("unbuffered", [False, True])
def test_a_reader_that_left_keeps_the_earned_exit_code(tmp_path, unbuffered):
    write_end = _gone_reader()
    try:
        done = _run(["tagteam", str(_target(tmp_path))], stdout=write_end, unbuffered=unbuffered)
    finally:
        os.close(write_end)
    assert done.returncode == 6, done.stderr  # INCONCLUSIVE: observe only, nothing to propose
    assert "Traceback" not in done.stderr and "BrokenPipe" not in done.stderr


@pytest.mark.parametrize("unbuffered", [False, True])
def test_a_closed_stdout_is_said_and_keeps_a_non_zero_code(tmp_path, unbuffered):
    done = _run(["tagteam", str(_target(tmp_path))], stdout=None, unbuffered=unbuffered, close_fd1=True)
    assert done.returncode == 6, done.stderr
    assert "could not be delivered on standard output" in done.stderr and "Traceback" not in done.stderr


@pytest.mark.parametrize("unbuffered", [False, True])
def test_an_undelivered_zero_becomes_one(tmp_path, unbuffered):
    """`warden audit` prints the table and exits 0; with nowhere to print it, 0 is not earned."""
    target = _target(tmp_path)
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")
    args = ["audit", str(target), "--from-ghost", str(findings)]
    done = _run(args, stdout=None, unbuffered=unbuffered, close_fd1=True)
    assert done.returncode == 1, done.stderr
    assert "could not be delivered on standard output" in done.stderr and "is not an ACCEPT" in done.stderr
    assert "Traceback" not in done.stderr


@pytest.mark.parametrize("unbuffered", [False, True])
def test_a_reader_that_left_does_not_turn_a_zero_into_a_failure(tmp_path, unbuffered):
    target = _target(tmp_path)
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")
    write_end = _gone_reader()
    try:
        done = _run(["audit", str(target), "--from-ghost", str(findings)], stdout=write_end, unbuffered=unbuffered)
    finally:
        os.close(write_end)
    assert done.returncode == 0, done.stderr
    assert "Traceback" not in done.stderr


class _FullDevice:
    """A stream whose every write fails the way a full device does."""

    def write(self, text):
        raise OSError(errno.ENOSPC, "No space left on device")

    def flush(self):
        raise OSError(errno.ENOSPC, "No space left on device")


def test_a_write_that_fails_for_another_reason_is_said_and_a_zero_becomes_one(tmp_path, monkeypatch, capsys):
    target = _target(tmp_path)
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(sys, "stdout", _FullDevice())
    code = cli.main(["audit", str(target), "--from-ghost", str(findings)])
    err = capsys.readouterr().err
    assert code == 1
    assert "could not be delivered on standard output" in err and "No space left" in err


def test_a_write_that_fails_keeps_a_non_zero_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdout", _FullDevice())
    code = cli.main(["tagteam", str(_target(tmp_path))])
    assert code == 6
    assert "could not be delivered on standard output" in capsys.readouterr().err


def test_state_from_one_call_does_not_leak_into_the_next(tmp_path, monkeypatch, capsys):
    target = _target(tmp_path)
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")
    with monkeypatch.context() as m:
        m.setattr(sys, "stdout", _FullDevice())
        assert cli.main(["audit", str(target), "--from-ghost", str(findings)]) == 1
    capsys.readouterr()
    assert cli.main(["audit", str(target), "--from-ghost", str(findings)]) == 0
    assert "could not be delivered" not in capsys.readouterr().err


def test_a_reader_that_left_during_help_is_not_a_traceback(tmp_path):
    write_end = _gone_reader()
    try:
        done = _run(["--version"], stdout=write_end, unbuffered=True)
    finally:
        os.close(write_end)
    assert done.returncode == 0 and "Traceback" not in done.stderr
