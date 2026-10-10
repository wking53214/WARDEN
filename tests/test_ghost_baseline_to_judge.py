"""Ghost's baseline report (findings it was told to ignore) reaches the Judge, at the start and at the end.

Before this, Evidence had no place for it, so a real Judge always said the baseline was unknown and every
full-gate run ended ACCEPT_UNVERIFIED. The real Judge is used where it is installed.
"""

from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.ghost import Findings
from warden.roles import Evidence
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge
from test_judge_seat import _auth, _repo


def _found(baseline, rows=()):
    out = Findings(list(rows))
    out.baseline = baseline
    return out


@pytest.fixture
def stubs(monkeypatch):
    """Everything measured and clean except Ghost, which the test scripts one scan at a time."""
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))

    def script(*scans):
        queue = list(scans)
        monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: queue.pop(0) if len(queue) > 1 else queue[0])
    return script


def _run(judge):
    def go(tmp_path):
        _repo(tmp_path)
        team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge, ghost_tools_root=Path("."),
                       swizzle_root=Path("."), assay_root=Path("."), assay_floor=3)
        return team.run(tmp_path, authorization=_auth(tmp_path))
    return go


def test_evidence_carries_both_baseline_reports_and_they_are_optional():
    assert Evidence.__dataclass_fields__["ghost_baseline_before"].default is None
    assert Evidence.__dataclass_fields__["ghost_baseline_after"].default is None


def test_warden_hands_the_judge_the_first_and_the_last_baseline_report(tmp_path, stubs):
    stubs(_found({"path": None, "suppressed": 0}), _found({"path": ".ghost_baseline.json", "suppressed": 2}))
    judge = FakeJudge()
    result = _run(judge)(tmp_path)
    assert judge.evidence.ghost_baseline_before == {"path": None, "suppressed": 0}
    assert judge.evidence.ghost_baseline_after == {"path": ".ghost_baseline.json", "suppressed": 2}
    assert result.ghost_baseline == {"before": judge.evidence.ghost_baseline_before,
                                     "after": judge.evidence.ghost_baseline_after}


def test_old_ghost_or_an_unusable_count_is_passed_as_none_not_as_zero(tmp_path, stubs):
    for n, baseline in enumerate((None, {"path": None, "suppressed": None}, {"path": None, "suppressed": True},
                                  {"path": 7, "suppressed": 1}, "garbage")):
        stubs(_found(baseline))
        judge = FakeJudge()
        folder = tmp_path / f"r{n}"
        folder.mkdir()
        _run(judge)(folder)
        assert judge.evidence.ghost_baseline_before is None and judge.evidence.ghost_baseline_after is None


def test_hidden_findings_are_a_gap_once_and_the_judge_still_gets_the_numbers(tmp_path, stubs):
    found = _found({"path": None, "suppressed": 3})
    found.status, found.scan_counts = "ok", {"files_scanned": 2, "files_skipped": 0, "files_unparsable": 0}
    found.gaps = ("baseline: 3 finding(s) were hidden by Ghost's baseline file, so the scan did not show everything",)
    stubs(found)
    judge = FakeJudge()
    result = _run(judge)(tmp_path)
    assert judge.evidence.ghost_baseline_before == {"path": None, "suppressed": 3}
    assert result.unmeasured.count("ghost_partial") == 1
    assert result.ghost_scan["baseline"] == {"path": None, "suppressed": 3}
    assert len(result.ghost_scan["gaps"]) == 1


# -- with the real Judge ----------------------------------------------------------------------------

@pytest.fixture
def real_judge():
    seat = pytest.importorskip("judge.seat")
    return seat.Judge()


def test_clean_run_with_a_stub_ghost_reporting_no_baseline_is_a_plain_accept(tmp_path, stubs, real_judge):
    clean = {"path": None, "suppressed": 0}
    stubs(_found(clean), _found(clean))
    result = _run(real_judge)(tmp_path)
    assert result.verdict.decision == "ACCEPT", result.verdict.reasons
    assert result.decision == "ACCEPT"


def test_a_baseline_that_grows_during_the_run_is_rejected_by_the_real_judge(tmp_path, stubs, real_judge):
    stubs(_found({"path": ".ghost_baseline.json", "suppressed": 1}),
          _found({"path": ".ghost_baseline.json", "suppressed": 4}))
    result = _run(real_judge)(tmp_path)
    assert result.decision == "JUDGE_REJECTED"
    assert any("ignores more findings" in r for r in result.verdict.reasons)


def test_an_old_ghost_gives_accept_unverified_with_the_judges_unknown_reason(tmp_path, stubs, real_judge):
    stubs(())  # a bare list: old Ghost
    result = _run(real_judge)(tmp_path)
    assert result.decision == "ACCEPT_UNVERIFIED"
    assert result.verdict.decision == "INSUFFICIENT"
    assert any("baseline report" in r and "unknown" in r for r in result.verdict.reasons)
