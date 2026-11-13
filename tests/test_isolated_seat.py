"""A seat that runs in its own process (`--isolate-seats`): the messages, the limits, and the failures.

The limit tests are real: a seat is started, asked to try things it must not do, and reports what happened.
They are skipped on a machine that cannot give the limits (not Linux, or no Landlock), where Warden refuses
the mode instead; one test checks that refusal.
"""

import json
import tempfile
import os
import subprocess
import sys
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
    assert "does not cover" not in stderr and "had no effect" not in stderr
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


# -- the Drafter and the Finisher ---------------------------------------------------------------------------

from cns.defect import Defect, DefectSeverity  # noqa: E402
from cns.seat import Facts  # noqa: E402
from test_cli_integration import rig  # noqa: E402,F401  (the real-CLI rig and its seats)

MAKERS = '''
import os
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus

def _t(target, baseline, defects=()):
    return Transformation(
        target=str(Path(target).resolve()), intent="isolated", architectural_reason="test",
        affected_files=("NOTE.md",), expected_behavior="none", preservation_requirements=("keep",),
        known_defects=tuple(defects), transformation_scope="documentation", baseline_reference=baseline,
        evidence=("e",), edits=(FileEdit(path="NOTE.md", kind="write", new="new\\n", old="old\\n"),),
        status=TransformationStatus.PROPOSED)

class Maker:
    requires_contract = "{contract}"
    scope = None
    def __init__(self):
        self.calls = 0
    def propose(self, target, observed, baseline):
        self.calls += 1
        assert isinstance(target, Path), type(target)
        return _t(target, baseline, observed) if self.calls == 1 else None
    def finish(self, target, baseline, facts):
        return _t(target, baseline) if facts.cycles == 2 and self.scope == "documentation" else None
    def describe_skipped(self):
        return ("left alone: x",)

class Plain:
    requires_contract = "{contract}"
    def propose(self, target, observed, baseline):
        return None
'''


@needs_limits
def test_a_drafter_and_a_finisher_answer_through_messages_with_their_own_parts_intact(world):
    (world.seats / "maker_seats.py").write_text(MAKERS.format(contract=CONTRACT), encoding="utf-8")

    def start(name):
        seat = seatproc.IsolatedSeat(f"maker_seats:{name}", "The Drafter", 30)
        return seat.start(target=world.target, sys_path=world.path, contract=CONTRACT)

    maker = start("Maker")
    try:
        assert hasattr(maker, "scope") and callable(getattr(maker, "describe_skipped", None))
        maker.scope = "documentation"
        assert maker.scope == "documentation"
        defect = Defect(summary="s", severity=DefectSeverity.HIGH, ghost_id="d1")
        proposal = maker.propose(world.target, (defect,), "base")
        assert type(proposal).__name__ == "Transformation" and proposal.edits[0].path == "NOTE.md"
        assert proposal.known_defects[0].identity == "d1" and proposal.known_defects[0].epistemic == defect.epistemic
        assert proposal.known_defects[0].lifecycle.value == defect.lifecycle.value
        assert maker.propose(world.target, (), "base") is None
        assert maker.describe_skipped() == ("left alone: x",)
        finish = maker.finish(world.target, "base", Facts(suite=None, remaining=(defect,), cycles=2))
        assert finish is not None and finish.edits[0].new == "new\n"  # it saw the scope Warden set
    finally:
        maker.close()
    plain = start("Plain")
    try:
        assert not hasattr(plain, "scope") and getattr(plain, "describe_skipped", None) is None
    finally:
        plain.close()


@needs_limits
def test_the_same_run_gives_the_same_result_with_and_without_isolation(rig):
    plain_code, plain, _ = rig.run()
    # put the tree back so the second run starts from the same state
    subprocess.run(["git", "checkout", "--", "."], cwd=str(rig.target), check=True, capture_output=True)
    code, isolated, stderr = rig.run("--isolate-seats")
    assert (code, isolated["decision"]) == (plain_code, plain["decision"])
    assert isolated["reason"] == plain["reason"]  # the proposal was made, judged and held the same way
    for who in ("drafter", "judge"):
        assert isolated["versions"]["seats"][who]["isolated"] is True
    assert "covers" not in stderr  # every named seat is covered, so no warning


@needs_limits
def test_a_seat_that_writes_into_git_is_blocked_and_leaves_no_lock_behind(rig):
    code, payload, _ = rig.run("--isolate-seats", drafter="it_seats:LockMaker")
    assert not (rig.target / ".git" / "index.lock").exists()
    assert payload["decision"] != "ACCEPT"


@needs_limits
def test_a_hung_drafter_in_isolation_is_stopped_at_the_seat_timeout(rig):
    code, payload, _ = rig.run("--isolate-seats", "--seat-timeout", "2", drafter="it_seats:Hang", timeout=120)
    assert payload["decision"] == "ERROR"


# -- the target's own test suite ---------------------------------------------------------------------------

from warden.suite import run_suite  # noqa: E402


def _suite_target(tmp_path, body: str, name="proj"):
    target = tmp_path / name
    (target / "tests").mkdir(parents=True)
    (target / "tests" / "test_probe.py").write_text(body, encoding="utf-8")
    (target / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    return target


SUITE_OK = '''
import os, tempfile, socket, pathlib

def test_reads_the_tree_and_writes_only_where_allowed():
    root = pathlib.Path(__file__).resolve().parents[1]
    assert (root / "pyproject.toml").read_text()
    with tempfile.NamedTemporaryFile() as handle:          # TMPDIR is the scratch folder
        handle.write(b"x")
    (root / ".pytest_cache").mkdir(exist_ok=True)
    (root / ".pytest_cache" / "note").write_text("x")      # a named cache folder

def test_local_socket_pairs_work_but_the_network_does_not():
    a, b = socket.socketpair()
    a.send(b"hi")
    assert b.recv(2) == b"hi"
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return
    raise AssertionError("a network socket was created")
'''


@needs_limits
def test_a_confined_suite_runs_green_and_leaves_the_tree_as_it_found_it(tmp_path):
    target = _suite_target(tmp_path, SUITE_OK)
    run = run_suite(target, sys.executable, 120, "pytest", confine=True)
    assert run.ran and run.green and run.passed == 2, run.describe()
    assert not (target / ".ruff_cache").exists() and not (target / ".mypy_cache").exists()  # made only for the rules
    scratch = [p for p in Path(tempfile.gettempdir()).glob("warden-suite-scratch-*")]
    assert scratch == []


SUITE_WRITES = '''
import pathlib

def test_writes_into_its_own_repo():
    root = pathlib.Path(__file__).resolve().parents[1]
    (root / "src_output.txt").write_text("not allowed")
'''


@needs_limits
def test_a_suite_that_writes_inside_its_repo_goes_red_and_says_why_it_never_passes(tmp_path):
    target = _suite_target(tmp_path, SUITE_WRITES)
    unconfined = run_suite(target, sys.executable, 120, "pytest")
    assert unconfined.green  # without the limits it would have passed
    (target / "src_output.txt").unlink()
    run = run_suite(target, sys.executable, 120, "pytest", confine=True)
    assert run.ran and not run.green and run.failed == 1
    assert "refused write" in run.reason
    assert not (target / "src_output.txt").exists()


@needs_limits
def test_a_suite_cannot_read_what_is_outside_its_folders(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("do not read", encoding="utf-8")
    target = _suite_target(tmp_path, f'def test_reads_secret():\n    open({str(secret)!r}).read()\n')
    run = run_suite(target, sys.executable, 120, "pytest", confine=True)
    assert run.ran and not run.green


def test_a_suite_is_not_run_unconfined_where_confinement_cannot_be_given(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "unavailable", lambda: "seat isolation needs Linux, and this is test-os")
    target = _suite_target(tmp_path, SUITE_OK)
    run = run_suite(target, sys.executable, 120, "pytest", confine=True)
    assert not run.ran and "will not run a suite unconfined" in run.reason


def test_a_cargo_suite_is_refused_when_confinement_is_asked_for(tmp_path):
    target = tmp_path / "rust"
    target.mkdir()
    (target / "Cargo.toml").write_text('[package]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8")
    run = run_suite(target, sys.executable, 120, "cargo", confine=True)
    assert not run.ran and "Cargo" in run.reason


@needs_limits
def test_the_command_line_confines_the_suite_with_the_flag(rig):
    code, payload, _ = rig.run("--isolate-seats")
    assert payload["decision"] != "ERROR"
    assert "did not run" not in json.dumps(payload.get("notes", ""))
