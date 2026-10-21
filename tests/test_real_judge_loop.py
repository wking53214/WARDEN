"""The real Judge reads the evidence of the real Warden loop, in every shape the loop produces it.

JUDGE 0.4.2 turns away evidence that contradicts itself (a cycle outcome it does not know, two cycles with one
number, more applied cycles than listed edits, listed edits nothing applied, declined removals with no declined
cycle). Its own tests build that evidence by hand. These tests build it with Warden: a real `TagTeam` loop on a
real target with a real suite, a fully measured run (the instruments are stood in for, as in the other
Judge-seat tests), and the real `judge.seat.Judge` deciding. Every honest shape of loop must be a plain ACCEPT,
so a Judge that rejected evidence Warden really produces would turn red here.

Needs the Judge installed (CI installs the pinned one); a run without it skips these, and CI fails on a skip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.ghost import Findings
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeFinisher, RemovingDrafter

CLEAN_BASELINE = {"path": None, "suppressed": 0}
DEAD = {"id": "ghost-dead1", "detector": "unused_code", "severity": "minor", "summary": "unused", "status": "confirmed"}
DEAD_PY = "def unused():\n    return 1\n"


@pytest.fixture
def real_judge():
    return pytest.importorskip("judge.seat").Judge()


def _repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pkg" / "dead.py").write_text(DEAD_PY, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_pkg.py").write_text("from pkg import VALUE\n\ndef test_value():\n    assert VALUE == 1\n",
                                                encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _auth(root: Path, scope: str):
    return grant("william", "transform", str(root.resolve()), scope, "real judge loop test")


def _found(rows=()) -> Findings:
    found = Findings(list(rows))
    found.baseline = dict(CLEAN_BASELINE)
    found.status = "ok"
    found.scan_counts = {"files_scanned": 3, "files_skipped": 0, "files_unparsable": 0}
    return found


@pytest.fixture
def measured(monkeypatch):
    """Everything measured and sound except the target's suite, which really runs; Ghost reports dead code until
    it is commented out (a removal then passes the comment-out test)."""
    def scan(target, **kw):
        text = (Path(target) / "pkg" / "dead.py").read_text(encoding="utf-8")
        return _found(() if "WARDEN COMMENTED OUT" in text else (DEAD,))

    monkeypatch.setattr(tagteam, "ghost_scan", scan)
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _team(judge, drafter, finisher=None):
    return TagTeam(drafter=drafter, finisher=finisher, judge=judge, ghost_tools_root=Path("."),
                   swizzle_root=Path("."), assay_root=Path("."), assay_floor=3)


class TwoEdits:
    """One proposal that edits two files."""

    def __init__(self):
        self.done = False

    def propose(self, target, observed, baseline):
        if self.done:
            return None
        self.done = True
        return Transformation(
            target=str(Path(target).resolve()), intent="two files", architectural_reason="test",
            affected_files=("NOTE.md", "README.md"), expected_behavior="none", preservation_requirements=(),
            known_defects=(), transformation_scope="documentation", baseline_reference=baseline, evidence=(),
            edits=(FileEdit(path="NOTE.md", kind="write", new="two a\n", old="old\n"),
                   FileEdit(path="README.md", kind="write", new="two b\n", old="# demo\n")),
            status=TransformationStatus.PROPOSED)


class OutOfScopeThenNote:
    """First asks to change code under a documentation grant (declined, nothing written), then edits the note."""

    def __init__(self):
        self.calls = 0

    def propose(self, target, observed, baseline):
        self.calls += 1
        if self.calls == 1:
            old = (Path(target) / "pkg" / "__init__.py").read_text(encoding="utf-8")
            return Transformation(
                target=str(Path(target).resolve()), intent="code under a documentation grant",
                architectural_reason="test", affected_files=("pkg/__init__.py",), expected_behavior="none",
                preservation_requirements=(), known_defects=(), transformation_scope="code",
                baseline_reference=baseline, evidence=(),
                edits=(FileEdit(path="pkg/__init__.py", kind="write", new="VALUE = 1  # tidied\n", old=old),),
                status=TransformationStatus.PROPOSED)
        if self.calls == 2:
            return FakeDrafter(steps=("note after a declined proposal\n",)).propose(target, observed, baseline)
        return None


def _shapes():
    return {
        "nothing_to_propose": (lambda: FakeDrafter(steps=()), None, "documentation"),
        "one_applied_cycle": (lambda: FakeDrafter(steps=("one\n",)), None, "documentation"),
        "two_applied_cycles": (lambda: FakeDrafter(steps=("one\n", "two\n")), None, "documentation"),
        "one_cycle_with_two_edits": (TwoEdits, None, "documentation"),
        "finisher_only_after_a_converged_loop": (lambda: FakeDrafter(steps=()), FakeFinisher, "documentation"),
        "applied_cycle_then_finisher": (lambda: FakeDrafter(steps=("one\n",)), FakeFinisher, "documentation"),
        "declined_proposal_then_applied_cycle": (OutOfScopeThenNote, None, "documentation"),
        "removal_commented_out": (RemovingDrafter, None, "code"),
        "removal_commented_out_then_finisher": (RemovingDrafter, FakeFinisher, "code"),
    }


@pytest.mark.parametrize("shape", sorted(_shapes()))
def test_every_honest_loop_shape_is_a_plain_accept_from_the_real_judge(tmp_path, measured, real_judge, shape):
    make_drafter, make_finisher, scope = _shapes()[shape]
    _repo(tmp_path)
    team = _team(real_judge, make_drafter(), make_finisher() if make_finisher else None)
    result = team.run(tmp_path, authorization=_auth(tmp_path, scope), findings=_found((DEAD,)))
    reasons = tuple(result.verdict.reasons) if result.verdict else ()
    assert result.decision == "ACCEPT", (result.decision, result.reason, reasons)
    assert result.verdict.decision == "ACCEPT", reasons
    assert not any("contradict" in r or "trustworthy" in r or "cannot tell" in r for r in reasons), reasons


def test_the_shapes_cover_each_cycle_outcome_the_loop_can_end_a_good_run_with(tmp_path, measured, real_judge):
    """Guard on the guard: the declined shapes really produced DECLINED cycles and the applied ones APPLIED."""
    _repo(tmp_path)
    result = _team(real_judge, OutOfScopeThenNote()).run(tmp_path, authorization=_auth(tmp_path, "documentation"),
                                                         findings=_found((DEAD,)))
    assert [c.outcome for c in result.cycles] == ["DECLINED", "APPLIED", "NOTHING_TO_PROPOSE"]
    assert (tmp_path / "pkg" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_the_real_judge_really_checks_contradictions_in_this_setup(tmp_path, measured, real_judge):
    """Guard on the other side: the same loop, with the evidence made to contradict itself on its way to the
    Judge, is not an ACCEPT. So the ACCEPTs above are the Judge finding nothing wrong, not the Judge not looking."""
    import dataclasses

    class Corrupting:
        def decide(self, evidence):
            return real_judge.decide(dataclasses.replace(evidence, cycles=evidence.cycles + ((1, "APPLIED"),)))

    _repo(tmp_path)
    result = _team(Corrupting(), FakeDrafter(steps=("one\n",))).run(
        tmp_path, authorization=_auth(tmp_path, "documentation"), findings=_found((DEAD,)))
    assert result.verdict.decision == "INSUFFICIENT"
    assert any("share one number" in r for r in result.verdict.reasons), result.verdict.reasons
