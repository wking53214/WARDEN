"""What a target whose own suite is red from the start actually ends as, and that the documents say so.

The documents once said a red suite from the start is INCONCLUSIVE (exit 6). That is true only when the loop is
about to apply a Drafter's change: the suite is measured before the first write, and a red one stops the run there.
When the Drafter has nothing to propose, no change is attempted in the loop, so the red suite shows up later:
- a Finisher that proposes something is refused at the same measurement, which the finishing path reports as
  FINISH_REJECTED ("Finishing: SUITE_RED"), exit 1;
- with no Finisher change, the Judge reads the suite's final state and rejects (JUDGE_REJECTED, exit 1).
Both are refusals with nothing written. These tests pin the three outcomes, and the README and exit-code page that
describe them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.cli import EXIT_CODES
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeFinisher, FakeJudge

ROOT = Path(__file__).resolve().parents[1]


def _red_repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text(
        "from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 2\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "README.md").write_text("# d\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _run(tmp_path, drafter, finisher=None, judge=None):
    _red_repo(tmp_path)
    auth = grant("william", "transform", str(tmp_path.resolve()), "documentation", "red suite")
    team = TagTeam(drafter=drafter, finisher=finisher, judge=judge or FakeJudge("ACCEPT", ("fine",)),
                   ghost_tools_root=Path("."), swizzle_root=Path("."), assay_root=Path("."))
    return team.run(tmp_path, findings=[], authorization=auth)


def test_a_proposal_against_a_red_suite_is_inconclusive_exit_6(tmp_path, measured):
    result = _run(tmp_path, FakeDrafter(steps=("changed\n",)))
    assert result.decision == "INCONCLUSIVE" and EXIT_CODES[result.decision] == 6
    assert "the suite is not green" in result.reason
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_a_finisher_change_against_a_red_suite_is_finish_rejected_exit_1(tmp_path, measured):
    finisher = FakeFinisher()
    result = _run(tmp_path, FakeDrafter(steps=()), finisher=finisher)
    assert finisher.calls == 1
    assert result.decision == "FINISH_REJECTED" and EXIT_CODES[result.decision] == 1
    assert "Finishing: SUITE_RED" in result.reason
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# d\n"


def test_with_nothing_proposed_by_anyone_the_run_is_never_an_accept_on_a_red_suite(tmp_path, measured):
    """No change is attempted, so nothing measures the suite before one; the final state still reaches the Judge."""
    judge = FakeJudge("REJECT", ("the suite is not green at the end",))
    result = _run(tmp_path, FakeDrafter(steps=()), judge=judge)
    assert judge.calls == 1
    assert result.decision == "JUDGE_REJECTED" and EXIT_CODES[result.decision] == 1
    facts = " ".join(result.notes)
    assert "0 passed, 1 failed" in facts


def test_the_documents_say_what_the_code_does_about_a_red_suite():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    page = (ROOT / "docs" / "EXIT_CODES.md").read_text(encoding="utf-8")
    row = re.search(r"^\| 6 \| `INCONCLUSIVE` \|.*$", readme, re.MULTILINE)
    assert row, "README exit-code table lacks the INCONCLUSIVE row"
    # the table row must not claim a red suite from the start is always exit 6
    assert "red from the start" not in row.group(0)
    for text in (readme, page):
        assert "FINISH_REJECTED" in text and "Finishing: SUITE_RED" in text
    assert "A suite that is red from the start" in page
