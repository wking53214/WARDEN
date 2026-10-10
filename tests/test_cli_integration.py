"""The real `warden` command, run as a separate process on a scratch git repository.

Each test starts a fresh interpreter (`python -m warden.cli`), so what is checked is what a user
or a CI job would see: the exit code, the JSON on stdout, and the files left on disk. No Ghost,
SWIZZLE or ASSAY is installed here, so the best a run can end is ACCEPT_UNVERIFIED (exit 3); what
these tests pin is that nothing is written when it must not be, and that the tree comes back when a
run is cut short.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from gitutil import commit_all, git

REPO_ROOT = Path(__file__).resolve().parents[1]

SEATS = '''
import os, signal, sys, time
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.roles import Verdict

MARK = Path(os.environ.get("SEAT_MARK", "/nonexistent")) if os.environ.get("SEAT_MARK") else None


def _t(target, observed, baseline, path, new, scope="documentation"):
    target = Path(target)
    old = (target / path).read_text(encoding="utf-8") if (target / path).is_file() else ""
    return Transformation(
        target=str(target.resolve()), intent="integration test", architectural_reason="test",
        affected_files=(path,), expected_behavior="none", preservation_requirements=(),
        known_defects=(), transformation_scope=scope, baseline_reference=baseline, evidence=(),
        edits=(FileEdit(path=path, kind="write", new=new, old=old),), status=TransformationStatus.PROPOSED)


class Doc:
    requires_contract = "1"
    n = 0
    def propose(self, target, observed, baseline):
        self.n += 1
        if self.n > 1:
            return None
        return _t(target, observed, baseline, "NOTE.md", "changed by the drafter\\n")


class Noisy(Doc):
    """Writes straight to file descriptor 1 and prints, as a careless seat might."""
    def propose(self, target, observed, baseline):
        os.write(1, b"STRAY BYTES ON FD 1\\n")
        print("stray print")
        return super().propose(target, observed, baseline)


class Hang(Doc):
    def propose(self, target, observed, baseline):
        time.sleep(60)


class LockMaker(Doc):
    """A seat that must not write, leaving a git lock file behind."""
    def propose(self, target, observed, baseline):
        (Path(target) / ".git" / "index.lock").write_text("", encoding="utf-8")
        return super().propose(target, observed, baseline)


class Judge:
    requires_contract = "1"
    def decide(self, evidence):
        return Verdict("ACCEPT", ("ok",), "judge")


class Signaller:
    requires_contract = "1"
    sig = signal.SIGTERM
    def decide(self, evidence):
        os.kill(os.getpid(), self.sig)
        time.sleep(5)
        return Verdict("ACCEPT", ("ok",), "judge")


class HupJudge(Signaller):
    sig = signal.SIGHUP


class IntJudge(Signaller):
    sig = signal.SIGINT


class Raiser:
    requires_contract = "1"
    def decide(self, evidence):
        raise RuntimeError("judge exploded")


class BadLabel:
    requires_contract = "1"
    def decide(self, evidence):
        return Verdict("MAYBE", ("hm",), "judge")


class WrongType:
    requires_contract = "1"
    def decide(self, evidence):
        return "ACCEPT"


class Rejecter:
    requires_contract = "1"
    def decide(self, evidence):
        return Verdict("REJECT", ("no",), "judge")
'''


@pytest.fixture
def rig(tmp_path):
    """A committed scratch repository and a folder holding the seats, with a runner for the real CLI."""
    target = tmp_path / "proj"
    target.mkdir()
    (target / "pkg").mkdir()
    (target / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (target / "tests").mkdir()
    (target / "tests" / "test_pkg.py").write_text(
        "from pkg import VALUE\n\ndef test_value():\n    assert VALUE == 1\n", encoding="utf-8")
    (target / "NOTE.md").write_text("old note\n", encoding="utf-8")
    (target / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (target / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    commit_all(target)
    seats = tmp_path / "seats"
    seats.mkdir()
    (seats / "it_seats.py").write_text(SEATS, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()

    class Rig:
        pass

    r = Rig()
    r.target, r.seats, r.tmp, r.home = target, seats, tmp_path, home

    def run(*extra, drafter="it_seats:Doc", judge="it_seats:Judge", authorize=True, scope="documentation",
            cwd=None, env=None, path=None, timeout=300):
        args = [sys.executable, "-m", "warden.cli", "tagteam", str(path or target), "--from-ghost", str(findings)]
        if drafter:
            args += ["--drafter", drafter]
        if judge:
            args += ["--judge", judge]
        if authorize:
            args += ["--authorize", "william", "--reason", "integration test", "--scope", scope]
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT), str(seats)]),
                           HOME=str(home), XDG_STATE_HOME=str(home / "state"))
        environment.update(env or {})
        done = subprocess.run(args + list(extra), cwd=str(cwd or tmp_path), capture_output=True, text=True,
                              timeout=timeout, env=environment)
        try:
            payload = json.loads(done.stdout)
        except ValueError:
            pytest.fail(f"stdout was not valid JSON:\n{done.stdout!r}\nstderr:\n{done.stderr[-800:]}")
        return done.returncode, payload, done.stderr

    findings = tmp_path / "findings.json"
    findings.write_text("[]", encoding="utf-8")
    r.run = run
    return r


def _note(rig) -> str:
    return (rig.target / "NOTE.md").read_text(encoding="utf-8")


def _status(rig) -> str:
    return git(rig.target, "status", "--porcelain")


# -- the happy path, so the failures below mean something -------------------------------------------

def test_a_clean_repository_is_changed_and_left_with_only_the_drafters_edit(rig):
    code, payload, _ = rig.run()
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED", payload["reason"]
    assert _note(rig) == "changed by the drafter\n"
    assert _status(rig) == "M NOTE.md"
    assert payload["contract"] == "1"


# -- A. the dirty-folder policy ----------------------------------------------------------------------

@pytest.mark.parametrize("how", ["untracked", "modified", "staged"])
def test_a_dirty_git_folder_is_refused_with_exit_5_and_nothing_written(rig, how):
    if how == "untracked":
        (rig.target / "mine.txt").write_text("my work", encoding="utf-8")
    elif how == "modified":
        (rig.target / "NOTE.md").write_text("my edit\n", encoding="utf-8")
    else:
        (rig.target / "staged.txt").write_text("x", encoding="utf-8")
        git(rig.target, "add", "staged.txt")
    before = _status(rig)
    code, payload, err = rig.run()
    assert code == 5 and payload["decision"] == "REFUSED"
    assert "commit or stash" in payload["reason"].lower()
    assert _status(rig) == before
    assert (rig.target / "NOTE.md").read_text(encoding="utf-8") in {"old note\n", "my edit\n"}


def test_ignored_files_do_not_make_a_folder_dirty(rig):
    (rig.target / "pkg" / "__pycache__").mkdir()
    (rig.target / "pkg" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    code, payload, _ = rig.run()
    assert code == 3, payload["reason"]


def test_a_folder_that_is_not_a_git_repository_is_allowed_with_a_note(rig):
    plain = rig.tmp / "plain"
    plain.mkdir()
    for p in rig.target.rglob("*"):
        if ".git" in p.parts or not p.is_file():
            continue
        dest = plain / p.relative_to(rig.target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.read_bytes())
    code, payload, _ = rig.run(path=plain)
    assert code == 3, payload["reason"]
    assert any("not inside a git repository" in n for n in payload["notes"])
    assert (plain / "NOTE.md").read_text(encoding="utf-8") == "changed by the drafter\n"


# -- D. a run cut short puts the tree back and says so -----------------------------------------------

@pytest.mark.parametrize("seat,name", [("TermJudge", "SIGTERM"), ("HupJudge", "SIGHUP"), ("IntJudge", "SIGINT")])
def test_a_signal_during_a_run_restores_the_tree_prints_json_and_exits_7(rig, seat, name):
    if seat == "TermJudge":
        seat = "Signaller"
    code, payload, _ = rig.run(judge=f"it_seats:{seat}")
    assert code == 7 and payload["decision"] == "INTERRUPTED"
    assert name in payload["reason"]
    assert _note(rig) == "old note\n" and _status(rig) == ""
    assert payload["put_back"] is True


# -- E. a Judge that fails does not leave the changes standing ----------------------------------------

@pytest.mark.parametrize("judge", ["Raiser", "BadLabel", "WrongType"])
def test_a_judge_that_fails_or_answers_wrongly_ends_error_and_the_tree_is_restored(rig, judge):
    code, payload, _ = rig.run(judge=f"it_seats:{judge}")
    assert code == 4 and payload["decision"] == "ERROR", payload["reason"]
    assert _note(rig) == "old note\n" and _status(rig) == ""
    assert payload["put_back"] is True


def test_a_judge_reject_reports_that_the_tree_was_put_back(rig):
    code, payload, _ = rig.run(judge="it_seats:Rejecter")
    assert code == 1 and payload["decision"] == "JUDGE_REJECTED"
    assert payload["put_back"] is True and _note(rig) == "old note\n"


# -- G. seats: no shadowing, no stray bytes, no stray git locks ---------------------------------------

def test_a_seat_module_planted_in_the_target_cannot_shadow_the_installed_one(rig):
    (rig.target / "it_seats.py").write_text(
        "raise SystemExit('the planted seat was imported')\n", encoding="utf-8")
    commit_all(rig.target, "plant")
    code, payload, err = rig.run(cwd=rig.target)
    assert code == 3, (payload["reason"], err[-300:])
    assert "planted" not in err


def test_a_seat_that_only_exists_inside_the_target_is_not_loaded(rig):
    (rig.target / "onlyhere.py").write_text(
        "class Judge:\n    requires_contract = '1'\n    def decide(self, e):\n        raise SystemExit(9)\n",
        encoding="utf-8")
    commit_all(rig.target, "plant")
    code, payload, _ = rig.run(judge="onlyhere:Judge", cwd=rig.target,
                               env={"PYTHONPATH": os.pathsep.join([str(REPO_ROOT), str(rig.target)])})
    assert code == 2 and payload["decision"] == "SEAT_NOT_LOADED"
    assert _note(rig) == "old note\n"


def test_writes_to_file_descriptor_1_by_a_seat_cannot_corrupt_the_json(rig):
    code, payload, err = rig.run(drafter="it_seats:Noisy")
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED"
    assert "STRAY BYTES ON FD 1" in err


def test_a_git_lock_file_left_by_a_seat_is_removed_and_the_run_is_rejected(rig):
    code, payload, _ = rig.run(drafter="it_seats:LockMaker")
    assert code == 1 and payload["decision"] == "REJECT"
    assert not (rig.target / ".git" / "index.lock").exists()
    assert _status(rig) == ""


# -- H. argparse errors and option checks come out as JSON --------------------------------------------

@pytest.mark.parametrize("flag", [["--assay-floor", "-1"], ["--assay-floor", "x"], ["--max-cycles", "0"],
                                  ["--suite-timeout", "0"], ["--seat-timeout", "-5"]])
def test_bad_options_exit_2_with_json(rig, flag):
    code, payload, _ = rig.run(*flag)
    assert code == 2 and payload["decision"] == "USAGE_ERROR" and payload["reason"]
    assert _note(rig) == "old note\n"


def test_an_unknown_option_and_no_command_are_json_too(rig):
    done = subprocess.run([sys.executable, "-m", "warden.cli", "tagteam", str(rig.target), "--nope"],
                          capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(REPO_ROOT)))
    assert done.returncode == 2 and json.loads(done.stdout)["decision"] == "USAGE_ERROR"
    done = subprocess.run([sys.executable, "-m", "warden.cli"], capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=str(REPO_ROOT)))
    assert done.returncode == 2 and json.loads(done.stdout)["decision"] == "USAGE_ERROR"


def test_assay_floor_zero_is_the_documented_way_to_skip(rig):
    code, payload, _ = rig.run("--assay-floor", "0")
    assert code == 3, payload["reason"]


@pytest.mark.parametrize("actor", ["Drafter", "BURNISH", "Gh​ost", "Ｓwizzle", "j u d g e", "Warden"])
def test_a_seat_or_tool_name_cannot_authorize(rig, actor):
    done = subprocess.run(
        [sys.executable, "-m", "warden.cli", "tagteam", str(rig.target), "--authorize", actor, "--reason", "x"],
        capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=str(REPO_ROOT)))
    payload = json.loads(done.stdout)
    assert done.returncode == 5 and payload["decision"] == "REFUSED"
    assert _note(rig) == "old note\n"


# -- J. a hung seat cannot hang the run -----------------------------------------------------------------

def test_a_hung_seat_is_stopped_by_the_seat_timeout(rig):
    code, payload, _ = rig.run("--seat-timeout", "2", drafter="it_seats:Hang", timeout=60)
    assert code == 4 and payload["decision"] == "ERROR"
    assert "did not answer within 2" in payload["reason"]
    assert _status(rig) == ""
