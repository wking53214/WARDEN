"""The CNS check is check only: it writes notes about records that do not meet their rows, and
decides nothing. A clean record adds no note, so a clean run's record reads as it did before."""

from pathlib import Path

import warden.tagteam as tagteam
from warden import cns_check
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge
from test_judge_seat import _repo, _auth


def _finding(**over):
    base = {"id": "ghost-1", "detector": "list_membership_in_loop", "severity": "minor",
            "status": "confirmed", "summary": "list used for membership", "detail": "",
            "evidence": {"file": "app.py", "line_start": 3}, "attributes": {}}
    base.update(over)
    return base


def test_clean_findings_and_attacks_add_no_note():
    assert cns_check.finding_notes([_finding(), _finding(id="ghost-2")]) == []
    assert cns_check.attack_notes([{"scenario": "a", "severity": "high", "status": "held"}]) == []


def test_a_finding_that_does_not_meet_the_row_is_named_and_counted():
    notes = cns_check.finding_notes([_finding(), _finding(summary=None)])
    assert notes == ["CNS check (nothing decided on it): 1 of 2 Ghost Tools findings do not meet cns.finding/1: "
                     "summary is missing or null, not text"]


def test_a_finding_that_is_not_an_object_is_named_too():
    notes = cns_check.finding_notes(["ghost-1"])
    assert "1 of 1 Ghost Tools findings" in notes[0] and "a finding is an object, not str" in notes[0]


def test_more_than_three_problems_are_summarised_with_a_count():
    notes = cns_check.finding_notes([_finding(id="") for _ in range(5)])
    assert notes[0].endswith("id is empty; id is empty; id is empty; and 2 more")


def test_an_attack_result_that_does_not_meet_the_row_is_named():
    notes = cns_check.attack_notes([{"scenario": "a", "severity": "high", "status": "held"},
                                    {"scenario": "b", "severity": None, "status": "held"}])
    assert notes == ["CNS check (nothing decided on it): 1 of 2 SWIZZLE attack results do not meet "
                     "cns.attack/1: severity is missing or null, not text"]


def _run(root: Path, findings):
    root.mkdir(parents=True, exist_ok=True)
    _repo(root)
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=FakeJudge("ACCEPT"), ghost_tools_root=Path("."))
    return team.run(root, findings=findings, authorization=_auth(root))


def test_a_drifted_finding_is_noted_and_the_decision_is_the_same(tmp_path, monkeypatch):
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    clean = _run(tmp_path / "clean", [_finding()])
    drifted = _run(tmp_path / "drifted", [_finding(summary="")])
    assert drifted.decision == clean.decision
    assert not any("CNS check" in n for n in clean.notes)
    assert any("CNS check (nothing decided on it): 1 of 1 Ghost Tools findings" in n for n in drifted.notes)
