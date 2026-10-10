"""A third party decides. Warden cannot ACCEPT on its own, and a REJECT puts everything back."""

from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeFinisher, FakeJudge


def _repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _auth(root, scope="documentation"):
    return grant("william", "transform", str(root.resolve()), scope, "judge test")


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _team(judge, **kw):
    return TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge, ghost_tools_root=Path("."),
                   swizzle_root=Path("."), assay_root=Path("."), **kw)


def test_without_a_judge_a_run_can_never_be_a_plain_accept(tmp_path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter(steps=("new\n",))).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT_UNVERIFIED" and "judge" in result.unmeasured


def test_the_judge_accepting_makes_the_run_an_accept(tmp_path, measured):
    _repo(tmp_path)
    judge = FakeJudge("ACCEPT", ("everything held",))
    result = _team(judge).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT" and result.verdict.decision == "ACCEPT" and judge.calls == 1
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "new\n"


def test_the_judge_rejecting_puts_the_whole_tree_back(tmp_path, measured):
    _repo(tmp_path)
    result = _team(FakeJudge("REJECT", ("not good enough",))).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "JUDGE_REJECTED" and result.verdict.reasons == ("not good enough",)
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"
    assert any("put back as it was found" in n for n in result.notes)


def test_a_judge_that_cannot_decide_leaves_the_changes_flagged_unjudged(tmp_path, measured):
    _repo(tmp_path)
    result = _team(FakeJudge("INSUFFICIENT", ("no attacks",))).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT_UNVERIFIED" and (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "new\n"


def test_a_judge_that_crashes_has_approved_nothing_and_the_changes_do_not_stand(tmp_path, measured):
    _repo(tmp_path)

    class Broken:
        def decide(self, evidence):
            raise RuntimeError("boom")

    result = _team(Broken()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ERROR" and result.verdict is None and result.put_back
    assert "The Judge failed with RuntimeError" in result.reason
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_a_judge_that_writes_the_tree_is_caught_and_undone(tmp_path, measured):
    _repo(tmp_path)

    class Writes:
        def decide(self, evidence):
            (Path(evidence.target) / "NOTE.md").write_text("judge was here\n", encoding="utf-8")
            from warden.roles import Verdict
            return Verdict("ACCEPT", ("fine",))

    result = _team(Writes()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    # The run did not end accepted, so the drafter's earlier edit is put back too (it used to stand).
    assert result.decision == "REJECT" and (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_the_judge_gets_measured_evidence_not_wardens_opinion(tmp_path, measured):
    _repo(tmp_path)
    judge = FakeJudge()
    _team(judge).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    e = judge.evidence
    assert e.scope == "documentation" and e.changed == (("NOTE.md", "write"),)
    assert e.suite_after.green and e.suite_before.green
    assert e.ghost_before == () and e.ghost_after == () and e.swizzle_proofs is True
    assert e.attacks and e.attacks[0]["status"] == "held" and e.unmeasured == ()


def test_evidence_says_none_when_a_check_never_ran_and_the_run_is_never_a_plain_accept(tmp_path):
    _repo(tmp_path)
    judge = FakeJudge("ACCEPT")
    result = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    e = judge.evidence
    assert e.ghost_before is None and e.ghost_after is None and e.swizzle_proofs is None and e.attacks is None
    assert set(e.unmeasured) == {"ghost", "swizzle", "assay"} and e.assay is None
    assert result.decision == "ACCEPT_UNVERIFIED"


def test_the_judge_is_asked_only_after_the_finisher_has_run(tmp_path, measured):
    _repo(tmp_path)
    judge = FakeJudge()
    _team(judge, finisher=FakeFinisher(path="README.md", new_text="final\n")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert ("README.md", "write") in judge.evidence.changed


def test_judging_files_touched_are_listed_for_the_judge(tmp_path, measured):
    _repo(tmp_path)
    tidy = "from pkg import VALUE\n\n\ndef test_v():\n    assert VALUE == 1  # tidy\n"
    judge = FakeJudge()
    team = TagTeam(drafter=FakeDrafter(steps=(tidy,), path="tests/test_x.py"), judge=judge,
                   ghost_tools_root=Path("."), swizzle_root=Path("."))
    team.run(tmp_path, findings=[], authorization=_auth(tmp_path, "code"))
    assert judge.evidence.judging_files_touched == ("tests/test_x.py",)
