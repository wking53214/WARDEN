"""A seat that runs in its own process (`--isolate-seats`): the messages, the limits, and the failures.

The limit tests are real: a seat is started, asked to try things it must not do, and reports what happened.
They are skipped on a machine that cannot give the limits (not Linux, or no Landlock), where Warden refuses
the mode instead; one test checks that refusal.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from cns.seat import Evidence, Verdict

from gitutil import commit_all
from warden import CONTRACT, runstate, sandbox, seatproc, seatwire
from warden.suite import PytestSuiteRun

REPO_ROOT = Path(__file__).resolve().parents[1]
needs_limits = pytest.mark.skipif(sandbox.unavailable() is not None, reason="this machine cannot confine a seat")


def make_evidence(target: str = "/somewhere", **over) -> Evidence:
    fields = dict(
        target=target, scope="documentation", cycles=((1, "APPLIED"),), changed=(("NOTE.md", "write"),),
        judging_files_touched=(), suite_before=PytestSuiteRun(ran=True, passed=3, failed=0, errors=0, skipped=0,
                                                              failed_ids=()),
        suite_after=None, ghost_before=("a",), ghost_after=None, declined=(), swizzle_proofs=True,
        attacks=({"scenario": "s", "severity": "major", "status": "held"},), unmeasured=("ghost",),
        notes=("n",), assay={"score": 3, "names": ["x", "y"]}, finisher_ran=False)
    fields.update(over)
    return Evidence(**fields)


# -- the messages ---------------------------------------------------------------------------------

def test_evidence_survives_the_trip_with_its_types_intact():
    evidence = make_evidence(ghost_severity={"a": "major"})
    back = seatwire.from_wire(json.loads(seatwire.dumps({"e": seatwire.to_wire(evidence)}))["e"])
    assert type(back) is Evidence
    assert back.cycles == ((1, "APPLIED"),) and isinstance(back.cycles, tuple)
    assert type(back.suite_before) is PytestSuiteRun and back.suite_before.passed == 3
    assert back.finisher_ran is False and back.swizzle_proofs is True and back.suite_after is None
    assert back.attacks == ({"scenario": "s", "severity": "major", "status": "held"},)
    assert back.ghost_severity == {"a": "major"} and back.assay == {"score": 3, "names": ["x", "y"]}
    assert back == evidence or back.assay == evidence.assay  # equal apart from mapping types


def test_a_verdict_comes_back_as_a_verdict():
    back = seatwire.from_wire(json.loads(seatwire.dumps(seatwire.to_wire(Verdict("ACCEPT", ("ok",), "J")))))
    assert back == Verdict("ACCEPT", ("ok",), "J")


@pytest.mark.parametrize("value", [{1, 2}, b"bytes", object(), {1: "non-text key"}, float("nan"),
                                   {"__row__": "collides"}])
def test_a_value_that_cannot_be_sent_is_an_error_not_a_guess(value):
    with pytest.raises(seatwire.WireError):
        seatwire.to_wire(value)


@pytest.mark.parametrize("name", ["os:system", "subprocess:Popen", "builtins:dict", "cnsevil.x:Y"])
def test_a_message_cannot_make_warden_build_a_class_outside_cns_and_warden(name):
    with pytest.raises(seatwire.WireError):
        seatwire.from_wire({"__row__": name, "fields": {}})
    with pytest.raises(seatwire.WireError):
        seatwire.from_wire({"__enum__": name, "value": "x"})


# -- seats to run -----------------------------------------------------------------------------------

PROBE = '''
import os, socket
from cns.seat import Verdict

class Probe:
    requires_contract = "{contract}"

    def decide(self, evidence):
        report = []
        def attempt(label, action):
            try:
                action()
            except OSError:
                report.append(label + ":blocked")
            else:
                report.append(label + ":allowed")
        target = evidence.target
        attempt("read_target", lambda: open(os.path.join(target, "a.txt")).read())
        attempt("write_target", lambda: open(os.path.join(target, "planted.txt"), "w").write("x"))
        attempt("delete_target", lambda: os.remove(os.path.join(target, "a.txt")))
        attempt("write_scratch", lambda: open("scratch.txt", "w").write("x"))
        attempt("read_elsewhere", lambda: open(r"{secret}").read())
        attempt("write_elsewhere", lambda: open(r"{elsewhere}", "w").write("x"))
        attempt("network", lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        attempt("local_socket", lambda: socket.socketpair())
        print("this line is printed by the seat and must not reach Warden's messages")
        return Verdict("INSUFFICIENT", tuple(report), "probe")

class Raises:
    requires_contract = "{contract}"
    def decide(self, evidence):
        raise ValueError("the seat broke")

class Hangs:
    requires_contract = "{contract}"
    def decide(self, evidence):
        import time
        time.sleep(60)

class NoContract:
    def decide(self, evidence):
        return Verdict("ACCEPT", (), "x")

class OldContract:
    requires_contract = "0"
    def decide(self, evidence):
        return Verdict("ACCEPT", (), "x")

class Answers:
    requires_contract = "{contract}"
    def decide(self, evidence):
        return "not a verdict"
'''


@pytest.fixture
def world(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    (target / "a.txt").write_text("hello\n", encoding="utf-8")
    seats = tmp_path / "seats"
    seats.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("do not read\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere.txt"
    (seats / "iso_seats.py").write_text(PROBE.format(contract=CONTRACT, secret=secret, elsewhere=elsewhere),
                                        encoding="utf-8")
    w = type("World", (), {})()
    w.target, w.seats, w.secret, w.elsewhere = target, seats, secret, elsewhere
    w.path = [str(seats), *[p for p in sys.path if p]]

    def start(name, timeout=30, tgt=None):
        seat = seatproc.IsolatedSeat(f"iso_seats:{name}", "The Judge", timeout)
        try:
            return seat.start(target=Path(tgt or target), sys_path=w.path, contract=CONTRACT)
        except BaseException:
            seat.close()
            raise

    w.start = start
    return w


@needs_limits
def test_the_seat_can_read_the_target_and_write_only_its_scratch_and_cannot_reach_the_network(world):
    seat = world.start("Probe")
    try:
        verdict = seat.decide(make_evidence(str(world.target)))
    finally:
        seat.close()
    assert isinstance(verdict, Verdict)
    assert set(verdict.reasons) == {
        "read_target:allowed", "write_target:blocked", "delete_target:blocked", "write_scratch:allowed",
        "read_elsewhere:blocked", "write_elsewhere:blocked", "network:blocked", "local_socket:blocked"}
    assert (world.target / "a.txt").read_text(encoding="utf-8") == "hello\n"
    assert not (world.target / "planted.txt").exists() and not world.elsewhere.exists()


@needs_limits
def test_the_scratch_folder_is_gone_when_the_seat_is_closed(world):
    seat = world.start("Probe")
    scratch = seat._scratch
    assert os.path.isdir(scratch)
    seat.close()
    assert not os.path.exists(scratch)
    seat.close()  # closing twice is harmless


@needs_limits
def test_a_seat_that_prints_cannot_corrupt_the_messages(world):
    seat = world.start("Probe")
    try:
        assert seat.decide(make_evidence(str(world.target))).judge == "probe"
        assert seat.decide(make_evidence(str(world.target))).judge == "probe"  # and it answers again
    finally:
        seat.close()


@needs_limits
def test_a_seat_that_raises_is_named_and_a_wrong_answer_is_not_accepted(world):
    seat = world.start("Raises")
    try:
        with pytest.raises(seatproc.SeatFailed, match="ValueError: the seat broke"):
            seat.decide(make_evidence(str(world.target)))
    finally:
        seat.close()
    seat = world.start("Answers")
    try:
        assert seat.decide(make_evidence(str(world.target))) == "not a verdict"  # tagteam's own check refuses it
    finally:
        seat.close()


@needs_limits
def test_a_seat_that_does_not_answer_is_killed_with_what_it_started(world):
    seat = world.start("Hangs", timeout=2)
    pid = seat._proc.pid
    with pytest.raises(runstate.SeatTimedOut):
        seat.decide(make_evidence(str(world.target)))
    seat.close()
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)


@needs_limits
def test_a_seat_with_no_contract_or_the_wrong_one_is_refused(world):
    for name, text in (("NoContract", "does not say which Warden contract"), ("OldContract", "contract '0'")):
        with pytest.raises(seatproc.SeatRefused, match=text):
            world.start(name)


@needs_limits
def test_a_seat_whose_code_is_inside_the_target_is_refused(world):
    shadow = world.target / "shadow_seats.py"
    shadow.write_text((world.seats / "iso_seats.py").read_text(encoding="utf-8"), encoding="utf-8")
    seat = seatproc.IsolatedSeat("shadow_seats:Probe", "The Judge", 30)
    try:
        with pytest.raises(seatproc.SeatRefused, match="inside the folder being governed"):
            seat.start(target=world.target, sys_path=[str(world.target), *world.path], contract=CONTRACT)
    finally:
        seat.close()


@needs_limits
def test_a_seat_that_will_not_build_is_a_failure_not_a_traceback(world):
    with pytest.raises(seatproc.SeatFailed, match="could not be loaded"):
        world.start("DoesNotExist")


def test_where_the_limits_cannot_be_given_the_seat_is_refused_not_run_unprotected(world, monkeypatch):
    monkeypatch.setattr(sandbox, "unavailable", lambda: "seat isolation needs Linux, and this is test-os")
    seat = seatproc.IsolatedSeat("iso_seats:Probe", "The Judge", 30)
    with pytest.raises(seatproc.SeatRefused, match="will not run a seat unprotected"):
        seat.start(target=world.target, sys_path=world.path, contract=CONTRACT)
    assert seat._proc is None


# -- through the command line ---------------------------------------------------------------------------

def _cli(world, tmp_path, *extra, judge="iso_seats:Probe"):
    findings = tmp_path / "findings.json"
    findings.write_text("[]", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    args = [sys.executable, "-m", "warden.cli", "tagteam", str(world.target), "--from-ghost", str(findings),
            "--judge", judge, "--authorize", "william", "--reason", "isolation test", "--scope", "documentation"]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT), str(world.seats)]), HOME=str(home),
               XDG_STATE_HOME=str(home / "state"))
    done = subprocess.run(args + list(extra), cwd=str(tmp_path), capture_output=True, text=True, timeout=300, env=env)
    return done.returncode, json.loads(done.stdout), done.stderr


@needs_limits
def test_the_command_line_runs_the_judge_isolated_and_the_record_says_so(world, tmp_path):
    (world.target / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (world.target / "tests").mkdir()
    (world.target / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    commit_all(world.target)
    code, payload, stderr = _cli(world, tmp_path, "--isolate-seats")
    assert "covers the Judge only in this release" in stderr
    assert payload["versions"]["seats"]["judge"]["isolated"] is True
    code_plain, plain, _ = _cli(world, tmp_path)
    assert "isolated" not in (plain["versions"]["seats"]["judge"] or {})
    assert not (world.target / "planted.txt").exists()


def test_the_command_line_refuses_where_the_limits_cannot_be_given(world, tmp_path, monkeypatch):
    # Run the real command with the limit check forced to fail, by a sitecustomize on the seat's path.
    (world.seats / "sitecustomize.py").write_text(
        "from warden import sandbox\nsandbox.unavailable = lambda: 'seat isolation needs Linux, and this is test-os'\n",
        encoding="utf-8")
    commit_all(world.target)
    code, payload, stderr = _cli(world, tmp_path, "--isolate-seats")
    assert payload["decision"] == "SEAT_NOT_LOADED" and code == 2
    assert "will not run a seat unprotected" in stderr
