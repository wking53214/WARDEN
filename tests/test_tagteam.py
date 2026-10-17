"""The governor: a loop that cycles until converged, then hands off once."""

from pathlib import Path

from warden.authorization import grant
from warden.tagteam import TagTeam

from fakes import FakeFinisher, FakeDrafter, StuckDrafter
from heldutil import keep_held


def _tree(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text(
        "from pkg import VALUE\n\ndef test_a():\n    assert VALUE == 1\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old note\n", encoding="utf-8")


def _auth(root: Path):
    return grant("william", "transform", str(root.resolve()), "code", "test")


def _read(root: Path, name: str) -> str:
    return (root / name).read_text(encoding="utf-8")


def test_missing_auth_does_not_write(tmp_path: Path):
    _tree(tmp_path)
    result = TagTeam(drafter=FakeDrafter()).run(tmp_path, findings=[], authorization=None)
    assert result.decision == "REFUSED" and result.applied is False
    assert _read(tmp_path, "NOTE.md") == "old note\n"
    assert result.cycles[0].proposal is not None and result.cycles[0].proposal.edits


def test_no_drafter_means_observe_only(tmp_path: Path):
    _tree(tmp_path)
    result = TagTeam().run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "INCONCLUSIVE" and not result.applied and result.cycles == ()
    assert _read(tmp_path, "NOTE.md") == "old note\n"


def test_loop_cycles_until_the_drafter_runs_dry(tmp_path: Path):
    _tree(tmp_path)
    drafter = FakeDrafter(steps=("one\n", "two\n", "three\n"))
    result = TagTeam(drafter=drafter).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    keep_held(result, tmp_path)
    assert result.converged and result.decision.startswith("ACCEPT")
    assert [c.outcome for c in result.cycles] == ["APPLIED"] * 3 + ["NOTHING_TO_PROPOSE"]
    assert _read(tmp_path, "NOTE.md") == "three\n"


def test_finisher_runs_once_and_only_after_the_loop(tmp_path: Path):
    _tree(tmp_path)
    finisher = FakeFinisher()
    result = TagTeam(drafter=FakeDrafter(steps=("a\n", "b\n")), finisher=finisher).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    keep_held(result, tmp_path)
    assert finisher.calls == 1 and result.finished and result.decision.startswith("ACCEPT")
    assert _read(tmp_path, "README.md") == "final\n" and _read(tmp_path, "NOTE.md") == "b\n"


def test_finisher_is_not_called_when_the_loop_does_not_converge(tmp_path: Path):
    _tree(tmp_path)
    finisher = FakeFinisher()
    result = TagTeam(drafter=StuckDrafter(), finisher=finisher, max_cycles=3).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "NOT_CONVERGED" and finisher.calls == 0 and not result.finished


def test_max_cycles_stops_a_drafter_that_never_runs_dry(tmp_path: Path):
    _tree(tmp_path)
    drafter = FakeDrafter(steps=[f"v{i}\n" for i in range(9)])
    result = TagTeam(drafter=drafter, max_cycles=2).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "NOT_CONVERGED" and len(result.cycles) == 2


def test_a_cycle_that_breaks_the_suite_is_put_back_and_stops_the_loop(tmp_path: Path):
    _tree(tmp_path)
    drafter = FakeDrafter(steps=("VALUE = 2\n",), path="pkg/__init__.py")
    result = TagTeam(drafter=drafter).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and result.cycles[-1].outcome == "PUT_BACK"
    assert _read(tmp_path, "pkg/__init__.py") == "VALUE = 1\n"


def test_a_finisher_that_breaks_the_suite_is_put_back_and_so_is_the_unfinished_loop_result(tmp_path: Path):
    _tree(tmp_path)
    breaking = FakeFinisher(path="pkg/__init__.py", new_text="VALUE = 2\n")
    result = TagTeam(drafter=FakeDrafter(steps=("kept\n",)), finisher=breaking).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "FINISH_REJECTED" and result.converged and not result.finished
    assert _read(tmp_path, "pkg/__init__.py") == "VALUE = 1\n"
    # A rejected finish is not an accepted run, so the loop's edit is put back too (it used to stand).
    assert _read(tmp_path, "NOTE.md") == "old note\n" and result.put_back


def test_the_finisher_is_handed_the_measured_facts(tmp_path: Path):
    _tree(tmp_path)
    finisher = FakeFinisher()
    findings = [{"id": "ghost-1", "detector": "unused_code", "severity": "minor", "status": "confirmed", "summary": "left over"}]
    TagTeam(drafter=FakeDrafter(steps=()), finisher=finisher).run(
        tmp_path, findings=findings, authorization=_auth(tmp_path))
    assert finisher.facts.suite.green and finisher.facts.suite.passed == 1
    assert [d.ghost_id for d in finisher.facts.remaining] == ["ghost-1"]
    assert finisher.facts.cycles == 0
