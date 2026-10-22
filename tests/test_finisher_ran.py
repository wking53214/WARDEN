"""`Evidence.finisher_ran`: the field CNS 2.0.0 added so a Judge can tell whether the finisher was called.

True: `finisher.finish(...)` was called after the loop converged (whether or not it had anything to finish; the
`changed` field says what was written). False: no finisher was seated, so none was called. None: the governor does
not say, which Warden never does: it builds Evidence only on a path where it knows. A run that ends before the
finishing step (refused, not converged, SWIZZLE failing after the loop, a rejected finish) hands the Judge no
Evidence at all, so there is no value to get wrong.

Before this field was filled, every one of these runs handed the Judge `finisher_ran=None`.
"""

from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeFinisher, FakeJudge, StuckDrafter


def _repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text(
        "from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _auth(root):
    return grant("william", "transform", str(root.resolve()), "documentation", "finisher_ran test")


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _team(judge, drafter=None, **kw):
    return TagTeam(drafter=drafter or FakeDrafter(steps=("new\n",)), judge=judge, ghost_tools_root=Path("."),
                   swizzle_root=Path("."), assay_root=Path("."), **kw)


class NothingToFinish:
    """A finisher that is called and has nothing to change."""

    def __init__(self):
        self.calls = 0

    def finish(self, target, baseline, facts):
        self.calls += 1
        return None


def test_the_judge_is_told_the_finisher_ran_when_it_finished_something(tmp_path, measured):
    _repo(tmp_path)
    judge, finisher = FakeJudge(), FakeFinisher(path="README.md", new_text="final\n")
    result = _team(judge, finisher=finisher).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT" and result.finished and finisher.calls == 1
    assert judge.evidence.finisher_ran is True
    assert ("README.md", "write") in judge.evidence.changed


def test_the_judge_is_told_the_finisher_ran_when_it_was_called_and_had_nothing_to_finish(tmp_path, measured):
    _repo(tmp_path)
    judge, finisher = FakeJudge(), NothingToFinish()
    result = _team(judge, finisher=finisher).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT" and not result.finished and finisher.calls == 1
    assert judge.evidence.finisher_ran is True
    assert judge.evidence.changed == (("NOTE.md", "write"),)  # called, and wrote nothing of its own


def test_the_judge_is_told_the_finisher_did_not_run_when_none_was_seated(tmp_path, measured):
    _repo(tmp_path)
    judge = FakeJudge()
    result = _team(judge).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT" and judge.calls == 1
    assert judge.evidence.finisher_ran is False  # False, not None: Warden knows


def test_a_run_with_no_loop_edits_and_no_finisher_still_says_false(tmp_path, measured):
    _repo(tmp_path)
    judge = FakeJudge()
    _team(judge, drafter=FakeDrafter(steps=())).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert judge.calls == 1 and judge.evidence.changed == () and judge.evidence.finisher_ran is False


def test_a_run_with_no_loop_edits_and_a_finisher_says_true(tmp_path, measured):
    _repo(tmp_path)
    judge, finisher = FakeJudge(), NothingToFinish()
    _team(judge, drafter=FakeDrafter(steps=()), finisher=finisher).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert judge.calls == 1 and judge.evidence.changed == () and judge.evidence.finisher_ran is True


def test_a_refused_run_reaches_neither_the_finisher_nor_the_judge(tmp_path, measured):
    _repo(tmp_path)
    judge, finisher = FakeJudge(), FakeFinisher()
    result = _team(judge, finisher=finisher).run(tmp_path, findings=[], authorization=None)
    assert result.decision == "REFUSED"
    assert finisher.calls == 0 and judge.calls == 0 and judge.evidence is None


def test_a_loop_that_does_not_converge_reaches_neither_the_finisher_nor_the_judge(tmp_path, measured):
    _repo(tmp_path)
    judge, finisher = FakeJudge(), FakeFinisher()
    result = _team(judge, drafter=StuckDrafter(), finisher=finisher, max_cycles=3).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "NOT_CONVERGED"
    assert finisher.calls == 0 and judge.calls == 0 and judge.evidence is None


def test_a_finish_that_is_rejected_never_reaches_the_judge(tmp_path, measured):
    """The finisher was called, but the run ended FINISH_REJECTED, so no Evidence is built to carry the answer."""
    _repo(tmp_path)
    judge = FakeJudge()
    breaking = FakeFinisher(path="pkg/__init__.py", new_text="VALUE = 2\n")
    result = TagTeam(drafter=FakeDrafter(steps=("kept\n",)), judge=judge, finisher=breaking,
                     ghost_tools_root=Path("."), swizzle_root=Path("."), assay_root=Path(".")).run(
        tmp_path, findings=[], authorization=grant("william", "transform", str(tmp_path.resolve()), "code", "t"))
    assert result.decision == "FINISH_REJECTED" and breaking.calls == 1
    assert judge.calls == 0 and judge.evidence is None


def test_swizzle_failing_after_the_loop_skips_the_finisher_and_the_judge(tmp_path, monkeypatch):
    _repo(tmp_path)
    answers = iter([True, False])
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: next(answers))
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    judge, finisher = FakeJudge(), FakeFinisher()
    result = _team(judge, finisher=finisher).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "INCONCLUSIVE" and "finishing was not attempted" in result.reason
    assert finisher.calls == 0 and judge.calls == 0 and judge.evidence is None


def test_the_answer_does_not_leak_from_one_run_to_the_next(tmp_path, measured):
    """The same TagTeam object run twice: the second run has its own answer."""
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir(), second.mkdir()
    _repo(first), _repo(second)
    judge = FakeJudge()
    team = _team(judge, finisher=NothingToFinish())
    team.run(first, findings=[], authorization=_auth(first))
    assert judge.evidence.finisher_ran is True
    team.finisher = None
    team.drafter = FakeDrafter(steps=("new\n",))
    team.run(second, findings=[], authorization=_auth(second))
    assert judge.evidence.finisher_ran is False
