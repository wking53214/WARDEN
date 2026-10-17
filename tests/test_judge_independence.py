"""Warden enforces what a Judge cannot waive: the ASSAY floor, the unmeasured list, and a readable verdict.

A rubber-stamp Judge (it says ACCEPT whatever the evidence) must not be able to turn an unmeasured or
under-floor run into a plain ACCEPT, and a verdict that is not a verdict is an ERROR.
"""

from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.roles import Verdict
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge
from test_judge_seat import _auth, _repo


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _team(judge, **kw):
    return TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge, ghost_tools_root=Path("."),
                   swizzle_root=Path("."), assay_root=Path("."), **kw)


def _note(root: Path) -> str:
    return (root / "NOTE.md").read_text(encoding="utf-8")


class RubberStamp:
    """Says ACCEPT with a reason, to everything."""
    calls = 0

    def decide(self, evidence):
        self.calls += 1
        return Verdict("ACCEPT", ("looks fine",), "stub")


def test_a_floor_the_score_does_not_meet_is_enforced_by_warden_not_the_judge(tmp_path, measured):
    _repo(tmp_path)
    judge = RubberStamp()
    result = _team(judge, assay_floor=7).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert judge.calls == 1, "the Judge is still asked; its ACCEPT just cannot waive the floor"
    assert result.decision == "REJECT" and "floor" in result.reason and "3 of" in result.reason
    assert result.put_back and _note(tmp_path) == "old\n"


def test_a_score_that_meets_the_floor_still_accepts(tmp_path, measured):
    _repo(tmp_path)
    result = _team(RubberStamp(), assay_floor=3).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT" and _note(tmp_path) == "new\n"


def test_floor_zero_is_the_one_explicit_way_to_skip_it(tmp_path, measured):
    _repo(tmp_path)
    result = _team(RubberStamp(), assay_floor=0).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT"


def test_the_floor_binds_even_when_no_judge_is_seated(tmp_path, measured):
    _repo(tmp_path)
    result = _team(None, assay_floor=7).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT"


def test_a_rubber_stamp_cannot_waive_an_unmeasured_check(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    # No ASSAY root: grading never ran. The Judge says ACCEPT anyway.
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=RubberStamp(), ghost_tools_root=Path("."),
                   swizzle_root=Path("."))
    result = team.run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT_UNVERIFIED" and "assay" in result.unmeasured
    assert _note(tmp_path) == "old\n"


def test_with_swizzle_absent_the_run_is_never_a_plain_accept_even_under_a_code_grant(tmp_path, monkeypatch):
    """Pins the documented behavior: no SWIZZLE means ACCEPT_UNVERIFIED (exit 3), whatever the Judge says."""
    _repo(tmp_path)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=RubberStamp(), ghost_tools_root=Path("."))
    result = team.run(tmp_path, findings=[], authorization=_auth(tmp_path, scope="code"))
    assert result.decision == "ACCEPT_UNVERIFIED" and "swizzle" in result.unmeasured
    assert any("SWIZZLE proofs NOT RUN" in n for n in result.notes)
    assert _note(tmp_path) == "old\n"


def test_attacks_on_the_governor_that_did_not_run_hold_the_run(tmp_path, measured, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: None)
    result = _team(RubberStamp()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT_UNVERIFIED" and "swizzle_attacks" in result.unmeasured
    assert _note(tmp_path) == "old\n"


@pytest.mark.parametrize("label", ["ACCEPT", "REJECT", "INSUFFICIENT"])
@pytest.mark.parametrize("reasons", [(), ("",), ("   ",)])
def test_a_verdict_with_no_reasons_is_an_error_whatever_its_label(tmp_path, measured, label, reasons):
    _repo(tmp_path)
    result = _team(FakeJudge(label, reasons)).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ERROR" and "no reasons" in result.reason
    assert result.put_back and _note(tmp_path) == "old\n"


@pytest.mark.parametrize("answer", ["ACCEPT", True, None, 1, ("ACCEPT", ("ok",))])
def test_a_judge_that_returns_the_wrong_kind_of_thing_is_an_error(tmp_path, measured, answer):
    _repo(tmp_path)

    class Odd:
        def decide(self, evidence):
            return answer

    result = _team(Odd()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ERROR" and _note(tmp_path) == "old\n"


def test_a_judge_with_reasons_in_a_list_is_still_read(tmp_path, measured):
    _repo(tmp_path)

    class Listy:
        def decide(self, evidence):
            return Verdict("ACCEPT", ["fine"], "stub")  # type: ignore[arg-type]

    result = _team(Listy()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT"
