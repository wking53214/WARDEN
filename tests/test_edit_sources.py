"""`Evidence.edit_sources`: where each listed edit came from, which CNS 4.2.0 adds and Warden fills.

`changed` lists every applied edit, the cycles' first and then the Finisher's. Without a label per edit, a run with one
applied cycle and two listed edits reads the same whether the second came from the Finisher or was padded in, so the
Judge cannot catch a padded list (JUDGE 0.8.0, KNOWN DEFECTS 1). Warden knows the answer when it builds the list, so it
says it: the cycle's number, or "finish".

Under a CNS that does not declare the field, Evidence has no such attribute and nothing else changes. Each test asserts
the branch that applies to the installed CNS, so it is never skipped.
"""

import dataclasses
from pathlib import Path

import pytest
from cns.seat import Evidence

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeFinisher, FakeJudge

DECLARED = "edit_sources" in {f.name for f in dataclasses.fields(Evidence)}


def _repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text(
        "from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "OTHER.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _auth(root):
    return grant("william", "transform", str(root.resolve()), "documentation", "edit_sources test")


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


class TwoFiles:
    """Proposes one change that edits two files, once."""

    def __init__(self):
        self.done = False

    def propose(self, target, observed, baseline):
        if self.done:
            return None
        self.done = True
        edits = tuple(FileEdit(path=p, kind="write", new="new\n", old="old\n") for p in ("NOTE.md", "OTHER.md"))
        return Transformation(
            target=str(Path(target).resolve()), intent="two files", architectural_reason="test",
            affected_files=("NOTE.md", "OTHER.md"), expected_behavior="none", preservation_requirements=(),
            known_defects=observed, transformation_scope="documentation", baseline_reference=baseline, evidence=(),
            edits=edits, status=TransformationStatus.PROPOSED)


class NothingToFinish:
    def __init__(self):
        self.calls = 0

    def finish(self, target, baseline, facts):
        self.calls += 1
        return None


def _run(tmp_path, drafter, finisher=None):
    _repo(tmp_path)
    judge = FakeJudge()
    result = TagTeam(drafter=drafter, judge=judge, finisher=finisher, ghost_tools_root=Path("."),
                     swizzle_root=Path("."), assay_root=Path(".")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT" and judge.calls == 1, result.reason
    return judge.evidence


def _says(evidence, expected):
    if DECLARED:
        assert evidence.edit_sources == expected
        assert len(evidence.edit_sources) == len(evidence.changed)
    else:
        assert not hasattr(evidence, "edit_sources")


def test_one_applied_cycle_and_a_finishing_edit_are_told_apart(tmp_path, measured):
    ev = _run(tmp_path, FakeDrafter(steps=("new\n",)), FakeFinisher(path="README.md", new_text="final\n"))
    assert ev.changed == (("NOTE.md", "write"), ("README.md", "write"))
    _says(ev, (1, "finish"))


def test_one_cycle_that_edited_two_files_names_that_cycle_twice(tmp_path, measured):
    """The same `changed` and `cycles` as the run above, and a different answer: this is the case labels settle."""
    ev = _run(tmp_path, TwoFiles())
    assert ev.changed == (("NOTE.md", "write"), ("OTHER.md", "write"))
    assert ev.cycles == ((1, "APPLIED"), (2, "NOTHING_TO_PROPOSE"))
    _says(ev, (1, 1))


def test_two_applied_cycles_each_name_their_own_number(tmp_path, measured):
    ev = _run(tmp_path, FakeDrafter(steps=("one\n", "two\n")))
    assert [o for _, o in ev.cycles] == ["APPLIED", "APPLIED", "NOTHING_TO_PROPOSE"]
    _says(ev, (1, 2))


def test_a_finisher_that_had_nothing_to_finish_adds_no_label(tmp_path, measured):
    ev = _run(tmp_path, FakeDrafter(steps=("new\n",)), NothingToFinish())
    assert ev.finisher_ran is True
    _says(ev, (1,))


def test_only_a_finishing_edit_is_labelled_finish(tmp_path, measured):
    ev = _run(tmp_path, FakeDrafter(steps=()), FakeFinisher(path="README.md", new_text="final\n"))
    assert ev.changed == (("README.md", "write"),)
    _says(ev, ("finish",))


def test_a_run_that_changed_nothing_has_no_labels_not_none(tmp_path, measured):
    ev = _run(tmp_path, FakeDrafter(steps=()))
    assert ev.changed == ()
    _says(ev, ())


def test_the_labels_survive_the_trip_to_an_isolated_judge(tmp_path, measured):
    """A Judge in its own process gets Evidence through the seat wire; the labels must arrive as sent."""
    import json

    from warden import seatwire

    ev = _run(tmp_path, FakeDrafter(steps=("new\n",)), FakeFinisher(path="README.md", new_text="final\n"))
    back = seatwire.from_wire(json.loads(seatwire.dumps({"e": seatwire.to_wire(ev)}))["e"])
    if DECLARED:
        assert back.edit_sources == (1, "finish") and isinstance(back.edit_sources, tuple)
    else:
        assert not hasattr(back, "edit_sources")
