"""The CNS rows are enforced where Warden reads Ghost findings and SWIZZLE attack results.

A record that does not meet its row is not read: a Ghost finding stops the observation as
unreadable (UNKNOWN), and a SWIZZLE attack result leaves the attacks not measured. Neither
becomes a decision by itself; both reach the existing unmeasured and inconclusive paths."""

import json
import subprocess
from pathlib import Path

import pytest

import warden.swizzle as swizzle
import warden.tagteam as tagteam
from warden.tagteam import GhostUnavailable, TagTeam, _defects

from fakes import FakeDrafter, FakeJudge
from test_judge_seat import _repo, _auth


def _finding(**over):
    base = {"id": "ghost-1", "detector": "list_membership_in_loop", "severity": "minor",
            "status": "confirmed", "summary": "list used for membership", "detail": "",
            "evidence": {"file": "app.py", "line_start": 3}, "attributes": {}}
    base.update(over)
    return base


def _proc(out):
    return subprocess.CompletedProcess(["x"], 0, out, "")


def test_a_finding_that_meets_the_row_is_read():
    assert len(_defects([_finding()])) == 1


def test_a_finding_that_does_not_meet_the_row_is_refused_with_the_reason():
    with pytest.raises(GhostUnavailable, match="does not meet cns.finding/1: summary is empty"):
        _defects([_finding(summary="")])


def test_an_attack_that_does_not_meet_the_row_is_not_measured(monkeypatch):
    report = [{"scenario": "a", "severity": "high", "status": "held"},
              {"scenario": "", "severity": "high", "status": "held"}]
    monkeypatch.setattr(swizzle, "run_instrument", lambda *a, **k: _proc(json.dumps(report)))
    note = []
    assert swizzle.governor_attacks(swizzle_root=Path("."), warden_root=Path("."), python="python3", note=note) is None
    assert note == ["SWIZZLE attacks on the governor not measured: an item in its report does not meet "
                    "cns.attack/1 (scenario is empty)"]


def test_attacks_that_meet_the_row_are_measured(monkeypatch):
    report = [{"scenario": "a", "severity": "high", "status": "held"}]
    monkeypatch.setattr(swizzle, "run_instrument", lambda *a, **k: _proc(json.dumps(report)))
    assert swizzle.governor_attacks(swizzle_root=Path("."), warden_root=Path("."), python="python3") == (
        {"scenario": "a", "severity": "high", "status": "held"},)


def _run(root: Path, findings):
    root.mkdir(parents=True, exist_ok=True)
    _repo(root)
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=FakeJudge("ACCEPT"), ghost_tools_root=Path("."))
    return team.run(root, findings=findings, authorization=_auth(root))


def test_a_drifted_finding_stops_the_run_and_a_clean_one_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    drifted = _run(tmp_path / "drifted", [_finding(summary="")])
    clean = _run(tmp_path / "clean", [_finding()])
    assert drifted.decision == "INCONCLUSIVE"
    assert "does not meet cns.finding/1" in " ".join(drifted.notes)
    assert "cns.finding/1" not in " ".join(clean.notes)
    assert clean.decision != "INCONCLUSIVE"
