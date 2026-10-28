"""A protected path (tests, test or build configuration, CI, dependency lists, git hooks) is applied, measured, named
and held, not refused at the guard. The owner's ruling of 2026-10-28, borderline, reviewed by the author.

What stays refused as before: test material (fixtures, specimens, golden files), Ghost's own `.ghost_*` files, and
anything outside the project or inside version control and environments.
"""

from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.claimrow import claim_row
from warden.guard import violation
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge


def _repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "tests" / "fixtures").mkdir()
    (root / "tests" / "fixtures" / "golden.txt").write_text("golden\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    (root / ".ghost_baseline.json").write_text("{}\n", encoding="utf-8")
    return root


def _auth(root: Path, scope: str = "code"):
    return grant("william", "transform", str(root.resolve()), scope, "protected hold test")


def _proposal(root: Path, path: str, text: str) -> Transformation:
    return Transformation(
        target=str(root.resolve()), intent="t", architectural_reason="t", affected_files=(path,),
        expected_behavior="", preservation_requirements=(), known_defects=(), transformation_scope="code",
        baseline_reference="", evidence=(), edits=(FileEdit(path=path, kind="write", new=text, old=""),),
        status=TransformationStatus.PROPOSED)


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


WIDER = "from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n\ndef test_w():\n    assert VALUE > 0\n"


def test_a_protected_edit_under_a_grant_is_applied_measured_and_held_with_the_path_in_the_row(tmp_path, measured):
    _repo(tmp_path)
    judge = FakeJudge("INSUFFICIENT", ("tests or test settings were changed (tests/test_x.py); a named human keeps or "
                                      "drops the held result",))
    team = TagTeam(drafter=FakeDrafter(steps=(WIDER,), path="tests/test_x.py"), judge=judge,
                   ghost_tools_root=Path("."), swizzle_root=Path("."), assay_root=Path("."))
    result = team.run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.cycles[0].outcome == "APPLIED" and result.cycles[0].suite_after.passed == 2  # measured, wider
    assert judge.evidence.judging_files_touched == ("tests/test_x.py",)
    assert result.decision == "ACCEPT_UNVERIFIED" and result.held_digest and result.put_back
    assert (tmp_path / "tests" / "test_x.py").read_text(encoding="utf-8").count("def test_") == 1  # held, not standing
    row = claim_row(result, _auth(tmp_path))
    assert row["files"] == [{"path": "tests/test_x.py", "status": "M", "before_sha256": row["files"][0]["before_sha256"],
                             "after_sha256": row["files"][0]["after_sha256"], "protected": True}]
    assert row["rules_fired"] == list(judge.reasons) and row["decision"] == "ACCEPT_UNVERIFIED"


def test_a_protected_edit_that_breaks_the_suite_is_still_put_back_by_rule_7(tmp_path):
    _repo(tmp_path)
    broken = "from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 2\n"
    result = TagTeam(drafter=FakeDrafter(steps=(broken,), path="tests/test_x.py")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and result.cycles[0].outcome == "PUT_BACK"
    assert "assert VALUE == 1" in (tmp_path / "tests" / "test_x.py").read_text(encoding="utf-8")


def test_a_protected_edit_under_a_documentation_grant_is_out_of_scope_and_nothing_is_written(tmp_path):
    _repo(tmp_path)
    got = violation(tmp_path, _proposal(tmp_path, "tests/test_x.py", WIDER), _auth(tmp_path, "documentation"))
    assert got is not None and got[0] == "scope"
    assert violation(tmp_path, _proposal(tmp_path, "pyproject.toml", "[project]\n"), _auth(tmp_path)) is None


@pytest.mark.parametrize("path,kind,words", [
    ("tests/fixtures/golden.txt", "refused", "test material"),
    (".ghost_baseline.json", "refused", "Ghost's own bookkeeping"),
    (".ghost_ledger/x.json", "refused", "Ghost's own bookkeeping"),
    ("../outside.py", "escape", "outside the authorized target"),
    (".git/hooks/pre-commit", "escape", "version control"),
])
def test_what_stays_refused_stays_refused(tmp_path, path, kind, words):
    _repo(tmp_path)
    got = violation(tmp_path, _proposal(tmp_path, path, "x\n"), _auth(tmp_path))
    assert got is not None and got[0] == kind and words in got[1], got
