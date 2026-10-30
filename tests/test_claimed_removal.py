"""A claimed commit that deletes a file or shrinks a code file is governed, not gated (the owner's ruling of 2026-10-30,
borderline, reviewed by the author).

The claim seat names a commit that already exists. Its removals are applied, measured (suite before and after, Ghost
before and after), named in the claim row's `removals`, and the run ends held for a named human, whatever the Judge
says. A removal proposed by a Drafter meets the same gate as before. Test material, Ghost's own `.ghost_*` files and
paths outside the project stay refused for every actor.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden import claim
from warden.authorization import grant
from warden.claimrow import KEYS, claim_row
from warden.cli import main
from warden.held import load
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge

_GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.org", "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1"}

BIG = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(5))  # ten non-blank lines
OLD = "def unused():\n    return 1\n"


def _git(cwd: Path, *args: str) -> str:
    env = dict(_GIT_ENV, HOME=str(cwd))
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip()


def _base(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pkg" / "old.py").write_text(OLD, encoding="utf-8")
    (root / "pkg" / "big.py").write_text(BIG, encoding="utf-8")
    (root / "pkg" / "needed.py").write_text("NEEDED = 2\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old note\nsecond line\n", encoding="utf-8")
    (root / "tests" / "fixtures").mkdir(parents=True)
    (root / "tests" / "fixtures" / "golden.txt").write_text("golden\n", encoding="utf-8")
    (root / "tests" / "test_pkg.py").write_text("from pkg import VALUE\n\n\ndef test_value():\n    assert VALUE == 1\n",
                                                encoding="utf-8")
    (root / "tests" / "test_extra.py").write_text("def test_extra():\n    assert True\n", encoding="utf-8")
    (root / "tests" / "test_needed.py").write_text(
        "from pkg.needed import NEEDED\n\n\ndef test_needed():\n    assert NEEDED == 2\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (root / ".ghost_baseline.json").write_text("{}\n", encoding="utf-8")
    (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")


def _claimed(root: Path, change) -> str:
    """Make `change(root)` as one commit on top of the base, then stand the tree back at the base. Returns the SHA."""
    _base(root)
    parent = _git(root, "rev-parse", "HEAD")
    change(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "Step 1: the claimed change")
    commit = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", parent)
    return commit


def _delete_old(root: Path) -> None:
    (root / "pkg" / "old.py").unlink()


def _shrink_big(root: Path) -> None:
    (root / "pkg" / "big.py").write_text("def f0():\n    return 0\n", encoding="utf-8")


def _add_only(root: Path) -> None:
    (root / "pkg" / "more.py").write_text("MORE = 3\n", encoding="utf-8")


def _auth(root: Path):
    return grant("william", "transform", str(root.resolve()), "code", "claimed removal test")


@pytest.fixture
def measured(monkeypatch):
    """Every instrument reports fine except the suite, which really runs, and Ghost, which finds nothing."""
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _govern(root: Path, commit: str, judge=None):
    judge = judge or FakeJudge()
    seat = claim.ClaimDrafter(claim.from_commit(root, commit))
    team = TagTeam(drafter=seat, judge=judge, ghost_tools_root=Path("."), swizzle_root=Path("."), assay_root=Path("."))
    return team.run(root, findings=[], authorization=_auth(root)), judge


# -- the claimed removal is applied, measured, named and held ---------------------------------------------------

def test_a_claimed_commit_that_only_adds_is_a_plain_accept_so_the_hold_below_is_the_removals(tmp_path, measured):
    commit = _claimed(tmp_path, _add_only)
    result, _ = _govern(tmp_path, commit)
    assert result.decision == "ACCEPT" and result.unmeasured == () and result.removals == ()
    assert claim_row(result, _auth(tmp_path))["removals"] == []


def test_a_claimed_deletion_is_applied_measured_and_held_with_the_row_naming_it(tmp_path, measured):
    commit = _claimed(tmp_path, _delete_old)
    result, judge = _govern(tmp_path, commit)
    assert [c.outcome for c in result.cycles] == ["APPLIED", "NOTHING_TO_PROPOSE"]
    assert result.cycles[0].suite_before.passed == 3 and result.cycles[0].suite_after.passed == 3  # measured both sides
    assert judge.evidence.changed == (("pkg/old.py", "delete"),)
    # Nothing was unmeasured and the Judge said ACCEPT: the hold is the removal and nothing else.
    assert judge.calls == 1 and result.unmeasured == ()
    assert result.decision == "ACCEPT_UNVERIFIED" and result.held_digest and result.put_back
    assert "Held for a named human" in result.reason and "deleted pkg/old.py (2 lines)" in result.reason
    assert (tmp_path / "pkg" / "old.py").read_text(encoding="utf-8") == OLD  # held, not standing
    saved = load(tmp_path, result.held_digest)
    assert "pkg/old.py" not in saved["files"] and "pkg/big.py" in saved["files"]
    row = claim_row(result, _auth(tmp_path))
    assert row["removals"] == [{"path": "pkg/old.py", "kind": "deleted", "lines_before": 2, "lines_after": 0,
                                "protected": False}]
    assert row["decision"] == "ACCEPT_UNVERIFIED" and row["claimed_commit"] == commit
    assert [f["status"] for f in row["files"]] == ["D"] and row["suite_before"]["passed"] == 3


def test_a_claimed_shrink_is_applied_measured_and_held(tmp_path, measured):
    commit = _claimed(tmp_path, _shrink_big)
    result, judge = _govern(tmp_path, commit)
    assert result.cycles[0].outcome == "APPLIED" and judge.evidence.changed == (("pkg/big.py", "write"),)
    assert result.decision == "ACCEPT_UNVERIFIED" and result.unmeasured == () and result.held_digest
    row = claim_row(result, _auth(tmp_path))
    assert row["removals"] == [{"path": "pkg/big.py", "kind": "shrunk", "lines_before": 10, "lines_after": 2,
                                "protected": False}]
    assert (tmp_path / "pkg" / "big.py").read_text(encoding="utf-8") == BIG


def test_a_claimed_removal_of_a_protected_path_is_named_as_protected_and_held(tmp_path, measured):
    commit = _claimed(tmp_path, lambda root: (root / "requirements.txt").unlink())
    result, judge = _govern(tmp_path, commit)
    assert judge.evidence.judging_files_touched == ("requirements.txt",)
    assert result.decision == "ACCEPT_UNVERIFIED" and result.held_digest
    assert claim_row(result, _auth(tmp_path))["removals"] == [
        {"path": "requirements.txt", "kind": "deleted", "lines_before": 1, "lines_after": 0, "protected": True}]


def test_a_claimed_commit_that_deletes_a_test_is_put_back_when_fewer_tests_pass(tmp_path, measured):
    """Rule 7 is unchanged: taking a test away lowers the pass count, which is a put-back, not a hold."""
    commit = _claimed(tmp_path, lambda root: (root / "tests" / "test_extra.py").unlink())
    result, _ = _govern(tmp_path, commit)
    assert result.cycles[0].outcome == "PUT_BACK" and result.decision == "REJECT" and not result.held_digest


def test_a_removal_beside_other_edits_is_named_and_the_other_edits_are_not(tmp_path, measured):
    def change(root):
        _delete_old(root)
        _add_only(root)
        (root / "NOTE.md").write_text("old note\n", encoding="utf-8")  # prose shrinks: not a removal

    commit = _claimed(tmp_path, change)
    result, _ = _govern(tmp_path, commit)
    assert result.decision == "ACCEPT_UNVERIFIED"
    assert [r["path"] for r in result.removals] == ["pkg/old.py"]


def test_the_hold_follows_the_judge_a_reject_stays_a_reject(tmp_path, measured):
    commit = _claimed(tmp_path, _delete_old)
    result, _ = _govern(tmp_path, commit, FakeJudge("REJECT", ("harm",)))
    assert result.decision == "JUDGE_REJECTED" and not result.held_digest and result.removals
    assert (tmp_path / "pkg" / "old.py").exists()


def test_a_claimed_removal_that_breaks_the_suite_is_still_put_back_by_rule_7(tmp_path, measured):
    commit = _claimed(tmp_path, lambda root: (root / "pkg" / "needed.py").unlink())
    result, _ = _govern(tmp_path, commit)
    assert result.cycles[0].outcome == "PUT_BACK" and result.decision == "REJECT" and not result.held_digest
    assert (tmp_path / "pkg" / "needed.py").exists()


def test_a_claimed_removal_that_adds_a_ghost_finding_is_measured_and_judged_not_put_back_by_the_gate(tmp_path, measured,
                                                                                                      monkeypatch):
    new = {"id": "ghost-new1", "detector": "unused_code", "severity": "minor", "summary": "x", "status": "confirmed"}
    monkeypatch.setattr(tagteam, "ghost_scan",
                        lambda target, **kw: () if (Path(target) / "pkg" / "old.py").exists() else (new,))
    commit = _claimed(tmp_path, _delete_old)
    result, judge = _govern(tmp_path, commit)
    assert result.cycles[0].outcome == "APPLIED" and not any("comment-out test failed" in n for n in result.notes)
    assert judge.evidence.ghost_after == ("ghost-new1",) and result.decision == "ACCEPT_UNVERIFIED"


# -- what is not changed ----------------------------------------------------------------------------------------

class _Removing:
    """A Drafter that proposes deleting pkg/old.py, citing nothing, and optionally dresses it as a claim."""

    requires_contract = "1"

    def __init__(self, dressed: bool = False):
        self.dressed, self.done = dressed, False

    def propose(self, target, observed, baseline):
        if self.done:
            return None
        self.done = True
        return Transformation(
            target=str(Path(target).resolve()), intent="remove", architectural_reason="t", affected_files=("pkg/old.py",),
            expected_behavior="", preservation_requirements=(), known_defects=(), transformation_scope="code",
            baseline_reference=baseline, evidence=(), edits=(FileEdit(path="pkg/old.py", kind="delete", new=""),),
            status=TransformationStatus.PROPOSED,
            claim={"commit": "0" * 40, "files": []} if self.dressed else None)


@pytest.mark.parametrize("dressed", [False, True])
def test_the_same_removal_proposed_by_a_drafter_is_refused_as_before(tmp_path, measured, dressed):
    _claimed(tmp_path, _delete_old)  # only for the base tree
    team = TagTeam(drafter=_Removing(dressed), judge=FakeJudge(), ghost_tools_root=Path("."),
                   swizzle_root=Path("."), assay_root=Path("."))
    result = team.run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert (tmp_path / "pkg" / "old.py").read_text(encoding="utf-8") == OLD and not result.applied
    assert result.cycles[0].outcome == "DECLINED" and not result.removals and not result.held_digest
    assert any("removal declined" in n for n in result.notes)


def test_a_drafter_removal_with_no_ghost_is_still_refused_as_systemic(tmp_path):
    _claimed(tmp_path, _delete_old)
    result = TagTeam(drafter=_Removing()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and (tmp_path / "pkg" / "old.py").exists()
    assert "cannot be validated" in result.reason


def _outside_diff(root: Path) -> Path:
    outside = root.parent / "outside.txt"
    outside.write_text("keep me\n", encoding="utf-8")
    patch = root.parent / "outside.diff"
    patch.write_text("--- a/../outside.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-keep me\n", encoding="utf-8")
    return patch


@pytest.mark.parametrize("path", ["tests/fixtures/golden.txt", ".ghost_baseline.json"])
def test_test_material_and_ghosts_own_files_stay_refused_for_the_claim_seat(tmp_path, measured, path):
    commit = _claimed(tmp_path, lambda root: (root / path).unlink())
    result, judge = _govern(tmp_path, commit)
    assert result.decision == "REJECT" and not result.cycles[0].applied and judge.calls == 0
    assert (tmp_path / path).exists() and not result.removals and not result.held_digest


def test_a_path_outside_the_project_stays_refused_for_the_claim_seat(tmp_path, measured):
    target = tmp_path / "project"
    target.mkdir()
    _claimed(target, _add_only)
    patch = _outside_diff(target)
    seat = claim.ClaimDrafter(claim.from_diff(target, patch, "outside", "Ada"))
    claim.check_base(target, seat.claim)
    team = TagTeam(drafter=seat, judge=FakeJudge(), ghost_tools_root=Path("."), swizzle_root=Path("."),
                   assay_root=Path("."))
    result = team.run(target, findings=[], authorization=_auth(target))
    assert result.decision == "REJECT" and "outside the authorized target" in result.reason
    assert (tmp_path / "outside.txt").read_text(encoding="utf-8") == "keep me\n" and not result.removals


def test_the_finishers_removals_still_meet_the_gate(tmp_path, measured):
    commit = _claimed(tmp_path, _add_only)
    seat = claim.ClaimDrafter(claim.from_commit(tmp_path, commit))

    class Finisher:
        requires_contract = "1"

        def finish(self, target, baseline, facts):
            return _Removing().propose(target, (), baseline)

    result = TagTeam(drafter=seat, finisher=Finisher(), judge=FakeJudge(), ghost_tools_root=Path("."),
                     swizzle_root=Path("."), assay_root=Path(".")).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "FINISH_REJECTED" and not result.removals
    assert any("without two loop validations" in n for n in result.notes)


# -- the record -----------------------------------------------------------------------------------------------

def test_the_rows_removals_round_trip_through_json_and_the_key_is_in_the_shared_set(tmp_path, measured):
    commit = _claimed(tmp_path, lambda root: (_delete_old(root), _shrink_big(root)))
    result, _ = _govern(tmp_path, commit)
    row = claim_row(result, _auth(tmp_path))
    assert tuple(row) == KEYS and KEYS[-3] == "removals"   # 0.16.4: two keys follow removals
    assert json.loads(json.dumps(row)) == row
    assert sorted((r["path"], r["kind"]) for r in row["removals"]) == [("pkg/big.py", "shrunk"),
                                                                        ("pkg/old.py", "deleted")]


def test_an_ordinary_drafter_run_has_an_empty_removals_list(tmp_path, measured):
    _claimed(tmp_path, _add_only)
    team = TagTeam(drafter=FakeDrafter(steps=("changed\n",)), judge=FakeJudge(), ghost_tools_root=Path("."),
                   swizzle_root=Path("."), assay_root=Path("."))
    result = team.run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert claim_row(result, _auth(tmp_path))["removals"] == []


def test_the_command_line_governs_a_claimed_deletion_and_prints_the_row(tmp_path, capsys):
    reference = tmp_path / "reference"
    commit = _claimed(reference, _delete_old)
    parent = _git(reference, "rev-parse", "HEAD")
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", parent)
    home = tmp_path / "home"
    home.mkdir()
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        code = main(["tagteam", str(target), "--claim-commit", commit, "--claim-repo", str(reference),
                     "--authorize", "william", "--reason", "govern the real commit", "--scope", "code"])
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home
    payload = json.loads(capsys.readouterr().out)
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED", payload["reason"]
    assert [c["outcome"] for c in payload["cycles"]] == ["APPLIED", "NOTHING_TO_PROPOSE"]
    assert payload["claim"]["removals"] == [{"path": "pkg/old.py", "kind": "deleted", "lines_before": 2,
                                            "lines_after": 0, "protected": False}]
    assert payload["held_digest"] and (target / "pkg" / "old.py").exists()
