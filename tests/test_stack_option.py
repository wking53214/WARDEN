"""`--stack DIR`: the whole circuit from one folder of checkouts, and the grant's scope told to the seats.

Before these, running the circuit meant naming six paths and three module specs by hand, and the
maker seats never learned the grant's scope: Burnish left code untidied under a `code` grant, and
a Drafter proposed code under a `documentation` grant only to have it declined.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.cli import main
from warden.tagteam import TagTeam

from fakes import FakeFinisher, FakeJudge

SEAT = '''
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.roles import Verdict


def _t(target, baseline, path, new):
    note = Path(target) / path
    old = note.read_text(encoding="utf-8") if note.is_file() else ""
    return Transformation(
        target=str(Path(target).resolve()), intent="stack test", architectural_reason="test",
        affected_files=(path,), expected_behavior="none", preservation_requirements=(),
        known_defects=(), transformation_scope="documentation", baseline_reference=baseline,
        evidence=(), edits=(FileEdit(path=path, kind="write", new=new, old=old),),
        status=TransformationStatus.PROPOSED)


class Drafter:
    requires_contract = "1"
    scope = None
    def __init__(self): self.done = False
    def propose(self, target, observed, baseline):
        if self.done: return None
        self.done = True
        return _t(target, baseline, "NOTE.md", f"scope={self.scope}\\n")


class Judge:
    requires_contract = "1"
    def decide(self, evidence): return Verdict("ACCEPT", ("ok",), "stack judge")


class Burnish:
    requires_contract = "1"
    scope = "documentation"
    def finish(self, target, baseline, facts):
        return _t(target, baseline, "README.md", f"finished under {self.scope}\\n")
'''

_MODULES = ("drafter", "drafter.seat", "judge", "judge.seat", "burnish", "burnish.finisher")


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                                encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "README.md").write_text("# d\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _stack(root: Path, names=("GHOST_TOOLS", "Swizzle", "assay", "DRAFTER", "Judge", "burnish")) -> Path:
    """A folder of checkouts whose names differ in case from the canonical ones, each with a seat package."""
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).mkdir()
    packages = {"drafter": "seat.py", "judge": "seat.py", "burnish": "finisher.py"}
    for name in names:
        module = packages.get(name.lower())
        if module:
            (root / name / name.lower()).mkdir()
            (root / name / name.lower() / "__init__.py").write_text("", encoding="utf-8")
            (root / name / name.lower() / module).write_text(SEAT, encoding="utf-8")
    return root


@pytest.fixture
def measured(monkeypatch):
    for m in _MODULES:
        sys.modules.pop(m, None)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))
    yield
    for m in _MODULES:
        sys.modules.pop(m, None)


def _run(capsys, *args):
    code = main(["tagteam", *map(str, args)])
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err


def test_the_stack_folder_must_exist(tmp_path, capsys):
    target = _repo(tmp_path / "t")
    code, payload, _ = _run(capsys, target, "--stack", tmp_path / "nowhere")
    assert code == 2 and payload["decision"] == "USAGE_ERROR" and "nowhere" in payload["reason"]


def test_a_stack_with_parts_missing_names_them_and_runs_nothing(tmp_path, capsys):
    target = _repo(tmp_path / "t")
    stack = _stack(tmp_path / "stack", names=("ghost_tools", "SWIZZLE"))
    code, payload, _ = _run(capsys, target, "--stack", stack, "--authorize", "william", "--reason", "r")
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert "assay, drafter, judge, burnish" in payload["reason"]
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_two_folders_differing_only_by_case_are_refused(tmp_path, capsys):
    target = _repo(tmp_path / "t")
    stack = _stack(tmp_path / "stack", names=("ghost_tools", "SWIZZLE", "assay", "DRAFTER", "Judge", "burnish",
                                                "Assay"))
    code, payload, _ = _run(capsys, target, "--stack", stack)
    assert code == 2 and "assay" in payload["reason"] and "differing only by case" in payload["reason"]


def test_the_stack_seats_everyone_with_names_matched_case_blind(tmp_path, capsys, measured):
    target = _repo(tmp_path / "t")
    stack = _stack(tmp_path / "stack")
    code, payload, err = _run(capsys, target, "--stack", stack, "--authorize", "william", "--reason", "r",
                              "--scope", "code")
    assert code == 0 and payload["decision"] == "ACCEPT", (payload["reason"], err)
    versions = payload["versions"]
    assert versions["ghost_tools"]["path"] == str(stack / "GHOST_TOOLS")
    assert versions["swizzle"]["path"] == str(stack / "Swizzle")
    assert versions["assay"]["path"] == str(stack / "assay")
    assert versions["seats"]["drafter"]["spec"] == "drafter.seat:Drafter"
    assert versions["seats"]["judge"]["spec"] == "judge.seat:Judge"
    assert versions["seats"]["finisher"]["spec"] == "burnish.finisher:Burnish"
    assert payload["verdict"]["judge"] == "stack judge"
    # The seats were told the grant's scope before they were asked.
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "scope=code\n"
    assert (target / "README.md").read_text(encoding="utf-8") == "finished under code\n"


def test_an_explicit_option_wins_over_the_stacks_copy(tmp_path, capsys, measured):
    target = _repo(tmp_path / "t")
    stack = _stack(tmp_path / "stack")
    other = tmp_path / "other_swizzle"
    other.mkdir()
    code, payload, _ = _run(capsys, target, "--stack", stack, "--swizzle-root", other,
                            "--authorize", "william", "--reason", "r")
    assert code == 0
    assert payload["versions"]["swizzle"]["path"] == str(other)
    assert payload["versions"]["ghost_tools"]["path"] == str(stack / "GHOST_TOOLS")


def test_a_seat_inside_the_target_is_still_refused_when_the_stack_names_it(tmp_path, capsys, measured):
    target = _repo(tmp_path / "t")
    stack = _stack(target / "vendored_stack")
    code, payload, _ = _run(capsys, target, "--stack", stack, "--authorize", "william", "--reason", "r")
    assert code == 2 and payload["decision"] == "SEAT_NOT_LOADED"
    assert "inside the folder being governed" in payload["reason"]


# -- the grant's scope reaches the seats, with or without --stack -----------------------------------

class ScopedDrafter:
    requires_contract = "1"

    def __init__(self):
        self.scope = None
        self.seen = []

    def propose(self, target, observed, baseline):
        self.seen.append(self.scope)
        return None


class Stubborn:
    """A Finisher whose scope is read-only."""
    requires_contract = "1"

    @property
    def scope(self):
        return "documentation"

    def finish(self, target, baseline, facts):
        return None


def _auth(root, scope):
    return grant("william", "transform", str(root.resolve()), scope, "scope test")


@pytest.mark.parametrize("scope", ["documentation", "code"])
def test_the_drafter_learns_the_grants_scope_before_its_first_call(tmp_path, measured, scope):
    _repo(tmp_path)
    drafter = ScopedDrafter()
    TagTeam(drafter=drafter, judge=FakeJudge()).run(tmp_path, findings=[], authorization=_auth(tmp_path, scope))
    assert drafter.seen == [scope]


def test_the_finisher_learns_the_grants_scope_too(tmp_path, measured):
    _repo(tmp_path)
    finisher = FakeFinisher()
    finisher.scope = "documentation"   # built with its own idea; the grant corrects it
    TagTeam(drafter=ScopedDrafter(), finisher=finisher, judge=FakeJudge()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "code"))
    assert finisher.scope == "code" and finisher.calls == 1


def test_a_seat_without_a_scope_attribute_is_left_alone(tmp_path, measured):
    _repo(tmp_path)
    finisher = FakeFinisher()
    TagTeam(drafter=ScopedDrafter(), finisher=finisher, judge=FakeJudge()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "code"))
    assert not hasattr(finisher, "scope") and finisher.calls == 1


def test_a_seat_that_will_not_take_the_scope_is_noted_not_crashed(tmp_path, measured):
    _repo(tmp_path)
    result = TagTeam(drafter=ScopedDrafter(), finisher=Stubborn(), judge=FakeJudge()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "code"))
    assert result.decision != "ERROR"
    assert any("The Finisher keeps a scope of its own" in n for n in result.notes)


def test_without_a_grant_no_scope_is_told(tmp_path, measured):
    _repo(tmp_path)
    drafter = ScopedDrafter()
    result = TagTeam(drafter=drafter).run(tmp_path, findings=[])
    assert result.decision == "REFUSED" and drafter.seen == [None]
