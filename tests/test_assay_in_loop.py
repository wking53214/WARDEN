"""ASSAY in the loop: Ghost is graded against the answer key before anything is written."""

from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge
from test_judge_seat import _repo, _auth

SCORE = {"key_proven": True, "failure_modes": 5, "caught": 3, "escaped": 0, "misnamed": 2, "proof": "29/29"}


@pytest.fixture
def instruments(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _team(judge=None, **kw):
    return TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge, ghost_tools_root=Path("."),
                   swizzle_root=Path("."), assay_root=Path("."), **kw)


def test_the_score_reaches_the_judge_with_the_floor(tmp_path, instruments, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (True, dict(SCORE), "scored"))
    judge = FakeJudge()
    result = _team(judge, assay_floor=3).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert judge.evidence.assay["caught"] == 3 and judge.evidence.assay["floor"] == 3
    assert result.decision == "ACCEPT" and "assay" not in result.unmeasured


def test_an_unproven_key_stops_the_run_before_any_write(tmp_path, instruments, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (False, {}, "key unproven"))
    result = _team(FakeJudge()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "INCONCLUSIVE" and result.cycles == ()
    assert (tmp_path / "NOTE.md").read_text() == "old\n"
    assert "assay" in result.unmeasured


def test_grading_that_cannot_run_is_not_measured_and_never_a_plain_accept(tmp_path, instruments, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (None, {}, "no grader"))
    judge = FakeJudge("ACCEPT")
    result = _team(judge).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert judge.evidence.assay is None and "assay" in result.unmeasured
    assert result.decision == "ACCEPT_UNVERIFIED"


def test_no_assay_root_says_so(tmp_path, instruments):
    _repo(tmp_path)
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=FakeJudge("ACCEPT"),
                   ghost_tools_root=Path("."), swizzle_root=Path("."))
    result = team.run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert "assay" in result.unmeasured and result.decision == "ACCEPT_UNVERIFIED"
    assert any("ASSAY grading NOT RUN" in n for n in result.notes)


def test_grading_needs_swizzle(tmp_path, instruments):
    _repo(tmp_path)
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), ghost_tools_root=Path("."), assay_root=Path("."))
    result = team.run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert "assay" in result.unmeasured
    assert any("done by SWIZZLE" in n for n in result.notes)


def test_warden_stays_out_of_the_answer_key():
    src = (Path(tagteam.__file__).parent / "swizzle.py").read_text()
    assert "import assay" not in src and "registry.json" not in src
