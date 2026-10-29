"""`Evidence.ghost_severity`: Ghost's own severity word beside each finding id, when the Evidence shape has the field.

CNS 2.1.0 adds `ghost_severity: Optional[Mapping[str, str]]` to `cns.seat.Evidence`. Warden fills it with the word
Ghost itself used (critical, major, minor, informational), taken from the Ghost JSON and not from
`models.ghost_severity_to_warden` (whose remap to critical/high/medium/low stays for Warden's own `Defect.severity`).
`ghost_before` and `ghost_after` stay bare ids. Under CNS 2.0.0 the field is absent and nothing changes. Both are
checked here with a stand-in Evidence class, so the test does not depend on which CNS is installed.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.roles import Evidence as PlainEvidence
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge


@dataclass(frozen=True)
class EvidenceWithSeverity(PlainEvidence):
    """What cns.seat.Evidence looks like from CNS 2.1.0 on."""

    ghost_severity: Optional[Mapping[str, str]] = None


@dataclass(frozen=True)
class EvidenceWithout(PlainEvidence):
    """The 2.0.0 shape, by another name, so the test does not depend on the installed CNS either way."""


def _finding(ident: str, severity: str) -> dict:
    return {"id": ident, "detector": "long_function", "severity": severity, "status": "confirmed",
            "summary": f"{ident} summary", "evidence": {"file": "pkg/__init__.py", "line_start": 1}}


BEFORE = [_finding("ghost-aaa", "minor"), _finding("ghost-bbb", "critical")]
AFTER = BEFORE + [_finding("ghost-ccc", "informational")]


def _repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: tuple(AFTER))
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _run(tmp_path, judge):
    _repo(tmp_path)
    auth = grant("william", "transform", str(tmp_path.resolve()), "documentation", "severity test")
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge, ghost_tools_root=Path("."),
                   swizzle_root=Path("."), assay_root=Path("."))
    return team.run(tmp_path, findings=BEFORE, authorization=auth)


def test_with_the_field_the_judge_gets_ghosts_own_words_and_bare_ids(tmp_path, monkeypatch, measured):
    monkeypatch.setattr(tagteam, "Evidence", EvidenceWithSeverity)
    judge = FakeJudge("INSUFFICIENT", ("held",))
    result = _run(tmp_path, judge)
    e = judge.evidence
    assert isinstance(e, EvidenceWithSeverity) and result.decision == "ACCEPT_UNVERIFIED"
    assert e.ghost_before == ("ghost-aaa", "ghost-bbb") and e.ghost_after == ("ghost-aaa", "ghost-bbb", "ghost-ccc")
    assert e.ghost_severity == {"ghost-aaa": "minor", "ghost-bbb": "critical", "ghost-ccc": "informational"}
    # Warden's own Defect keeps the remapped scale; the Judge is told the scanner's word, not the translation.
    assert {d.identity: d.severity.value for d in result.reobserved} == {
        "ghost-aaa": "medium", "ghost-bbb": "critical", "ghost-ccc": "low"}


def test_without_the_field_nothing_changes(tmp_path, monkeypatch, measured):
    monkeypatch.setattr(tagteam, "Evidence", EvidenceWithout)
    judge = FakeJudge("INSUFFICIENT", ("held",))
    _run(tmp_path, judge)
    e = judge.evidence
    assert isinstance(e, EvidenceWithout) and not hasattr(e, "ghost_severity")
    assert e.ghost_before == ("ghost-aaa", "ghost-bbb") and e.ghost_after == ("ghost-aaa", "ghost-bbb", "ghost-ccc")


def test_without_ghost_the_field_is_left_as_the_shape_defaults_it(tmp_path, monkeypatch):
    monkeypatch.setattr(tagteam, "Evidence", EvidenceWithSeverity)
    _repo(tmp_path)
    judge = FakeJudge("INSUFFICIENT", ("held",))
    auth = grant("william", "transform", str(tmp_path.resolve()), "documentation", "severity test")
    TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge).run(tmp_path, findings=[], authorization=auth)
    assert judge.evidence.ghost_before is None and judge.evidence.ghost_severity is None


@pytest.mark.parametrize("shape", [EvidenceWithSeverity, EvidenceWithout])
@pytest.mark.parametrize("word, remapped", [("critical", "critical"), ("major", "high"), ("minor", "medium"),
                                            ("informational", "low")])
def test_the_claim_rows_new_finding_carries_ghosts_word_and_the_judge_sees_the_same_word(
        tmp_path, monkeypatch, measured, shape, word, remapped):
    """The proof run found the row saying "medium" where the Judge saw "minor". `severity` is now Ghost's own word,
    the word `evidence.ghost_severity` holds; Warden's remapped word moves to `warden_severity`."""
    from warden.claimrow import claim_row
    new = _finding("ghost-new", word)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: (new,))
    monkeypatch.setattr(tagteam, "Evidence", shape)
    judge = FakeJudge("INSUFFICIENT", ("held",))
    _repo(tmp_path)
    auth = grant("william", "transform", str(tmp_path.resolve()), "documentation", "severity test")
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge, ghost_tools_root=Path("."),
                   swizzle_root=Path("."), assay_root=Path("."))
    result = team.run(tmp_path, findings=[], authorization=auth)
    entry, = claim_row(result, auth)["new_findings"]
    assert entry["id"] == "ghost-new" and entry["severity"] == word and entry["warden_severity"] == remapped
    if shape is EvidenceWithSeverity:
        assert judge.evidence.ghost_severity["ghost-new"] == entry["severity"]
