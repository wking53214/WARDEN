"""Record honesty: an ACCEPT's reason says what was measured, and a run the suite turned red names the failing tests.

Found by the falsifier's run 07 (a JUDGE_REJECTED on one failed test in the sixth of six passes, and the record
could not say which test) and by self-hosting run 3 (the bytecode control test misplaced under Warden's own
cache prefix; that fix is in tests/test_stale_bytecode.py).
"""

import json
import sys
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.cli import main
from warden.suite import PytestSuiteRun, run_suite
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeFinisher, FakeJudge


def _repo(root: Path, red: bool = False) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    body = "from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n\ndef test_w():\n    assert VALUE == %d\n"
    (root / "tests" / "test_x.py").write_text(body % (2 if red else 1), encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "README.md").write_text("# d\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _auth(root, scope="documentation"):
    return grant("william", "transform", str(root.resolve()), scope, "honesty test")


def test_the_suite_result_names_the_tests_that_failed(tmp_path):
    _repo(tmp_path, red=True)
    run = run_suite(tmp_path, sys.executable)
    assert isinstance(run, PytestSuiteRun) and not run.green
    assert run.failed_ids == ("tests/test_x.py::test_w",)
    assert run.describe().endswith("; failed: tests/test_x.py::test_w")
    green = run_suite(_repo(tmp_path / "g"), sys.executable) if (tmp_path / "g").mkdir() is None else None
    assert green.failed_ids == () and "failed:" not in green.describe()


def test_at_most_ten_failing_ids_are_kept(tmp_path):
    (tmp_path / "tests").mkdir()
    body = "import pytest\n\n@pytest.mark.parametrize('n', range(14))\ndef test_n(n):\n    assert n < 0\n"
    (tmp_path / "tests" / "test_many.py").write_text(body, encoding="utf-8")
    run = run_suite(tmp_path, sys.executable)
    assert run.failed == 14 and len(run.failed_ids) == 10
    assert run.failed_ids[0] == "tests/test_many.py::test_n[0]"


def test_a_red_suite_at_a_proposal_names_the_failing_test_in_the_reason(tmp_path):
    _repo(tmp_path, red=True)
    result = TagTeam(drafter=FakeDrafter(steps=("new\n",))).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "INCONCLUSIVE"
    assert "the suite is not green (" in result.reason and "tests/test_x.py::test_w" in result.reason


def test_a_finishing_change_that_breaks_the_suite_names_the_failing_test(tmp_path):
    _repo(tmp_path)
    breaking = "from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n\ndef test_w():\n    assert VALUE == 3\n"
    finisher = FakeFinisher(path="tests/test_x.py", new_text=breaking)
    result = TagTeam(drafter=FakeDrafter(steps=()), finisher=finisher).run(tmp_path, findings=[],
                                                                         authorization=_auth(tmp_path, "code"))
    assert result.decision == "FINISH_REJECTED"
    assert result.reason.startswith("Finishing: PUT_BACK (") and "tests/test_x.py::test_w" in result.reason


def test_a_red_suite_at_the_finishing_step_names_the_failing_test(tmp_path):
    _repo(tmp_path, red=True)
    result = TagTeam(drafter=FakeDrafter(steps=()), finisher=FakeFinisher()).run(tmp_path, findings=[],
                                                                               authorization=_auth(tmp_path))
    assert result.decision == "FINISH_REJECTED"
    assert "Finishing: SUITE_RED (" in result.reason and "tests/test_x.py::test_w" in result.reason


SEATS = '''
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.roles import Verdict


class Once:
    requires_contract = "1"
    def __init__(self): self.done = False
    def propose(self, target, observed, baseline):
        if self.done: return None
        self.done = True
        old = (Path(target) / "NOTE.md").read_text(encoding="utf-8")
        return Transformation(
            target=str(Path(target).resolve()), intent="t", architectural_reason="t", affected_files=("NOTE.md",),
            expected_behavior="none", preservation_requirements=(), known_defects=(), transformation_scope="documentation",
            baseline_reference=baseline, evidence=(), edits=(FileEdit(path="NOTE.md", kind="write", new="new\\n", old=old),),
            status=TransformationStatus.PROPOSED)


class Judge:
    requires_contract = "1"
    def decide(self, evidence):
        return Verdict("ACCEPT", ("everything held",), "judge")
'''


def test_an_accept_record_says_what_was_measured(tmp_path, monkeypatch, capsys):
    target = _repo(tmp_path / "t") if (tmp_path / "t").mkdir() is None else None
    seats = tmp_path / "seats"
    seats.mkdir()
    (seats / "honest_seats.py").write_text(SEATS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(seats))
    for name in ("ghost", "swizzle", "assay"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")
    code = main(["tagteam", str(target), "--drafter", "honest_seats:Once", "--judge", "honest_seats:Judge",
                 "--from-ghost", str(findings), "--ghost-root", str(tmp_path / "ghost"),
                 "--swizzle-root", str(tmp_path / "swizzle"), "--assay-root", str(tmp_path / "assay"),
                 "--authorize", "william", "--reason", "honesty"])
    payload = json.loads(capsys.readouterr().out)
    assert (code, payload["decision"]) == (0, "ACCEPT"), payload["reason"]
    reason = payload["reason"]
    assert reason.startswith("Loop converged.") and "Judge: ACCEPT (everything held)" in reason
    assert "Measured: the suite 2 passed before and 2 passed after" in reason and "Ghost 0 finding(s) before and 0 after" in reason
    assert reason.endswith(".") and "\n" not in reason


@pytest.mark.parametrize("decision", ["INSUFFICIENT"])
def test_a_non_accept_reason_is_unchanged_by_the_measured_clause(tmp_path, decision):
    _repo(tmp_path)
    judge = FakeJudge(decision, ("held",))
    result = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge).run(tmp_path, findings=[],
                                                                           authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT_UNVERIFIED" and "Measured:" not in result.reason
