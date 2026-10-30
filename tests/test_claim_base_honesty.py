"""The claim row says whether the whole target stood at the parent, not only the touched files.

`check_base` compares only the files the change touches with the parent, so a target that differs elsewhere is accepted
although the help said it "must stand at the parent". The row now records `target_tree_digest` (Warden's fingerprint of the
target before the run) and `base_matches_parent`: true iff that fingerprint equals the fingerprint of the parent's tree
as materialised from the claimed repository, false otherwise, null when it cannot be computed (a `--claim-diff` has no
parent tree). Record only: nothing new is refused.
"""

import json
import subprocess
from pathlib import Path

from warden import claim
from warden.claimrow import KEYS
from warden.cli import main
from warden.tagteam import _fingerprint

_GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.org", "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
                          env=dict(_GIT_ENV, HOME=str(cwd)))
    return done.stdout.strip()


def _reference(root: Path):
    (root / "pkg").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (root / "NOTE.md").write_text("old note\n", encoding="utf-8")
    (root / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "run.sh").chmod(0o755)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    parent = _git(root, "rev-parse", "HEAD")
    (root / "NOTE.md").write_text("new note\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "Step 1: the note")
    return parent, _git(root, "rev-parse", "HEAD")


def _govern(target, reference, commit, capsys):
    code = main(["tagteam", str(target), "--claim-commit", commit, "--claim-repo", str(reference), "--authorize",
                 "william", "--reason", "govern", "--scope", "documentation"])
    return code, json.loads(capsys.readouterr().out)


def test_the_keys_end_with_the_two_new_ones():
    assert KEYS[-3:] == ("removals", "target_tree_digest", "base_matches_parent")


def test_a_target_that_stands_exactly_at_the_parent_says_true(tmp_path, capsys):
    reference = tmp_path / "reference"
    parent, commit = _reference(reference)
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", parent)
    expected = _fingerprint(target)
    code, payload = _govern(target, reference, commit, capsys)
    assert code == 3, payload["reason"]
    row = payload["claim"]
    assert tuple(row) == KEYS
    assert row["target_tree_digest"] == expected == row["base_tree_digest"]
    assert row["base_matches_parent"] is True


def test_a_target_that_differs_elsewhere_is_still_accepted_and_the_row_says_false(tmp_path, capsys):
    reference = tmp_path / "reference"
    parent, commit = _reference(reference)
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", parent)
    (target / "extra.md").write_text("a file the parent does not have\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "an unrelated local commit")
    code, payload = _govern(target, reference, commit, capsys)
    assert code == 3, payload["reason"]          # record only: nothing new is refused
    row = payload["claim"]
    assert row["base_matches_parent"] is False
    assert row["target_tree_digest"] == row["base_tree_digest"] and len(row["target_tree_digest"]) == 16


def test_a_target_whose_executable_bit_differs_says_false(tmp_path, capsys):
    reference = tmp_path / "reference"
    parent, commit = _reference(reference)
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", parent)
    (target / "run.sh").chmod(0o644)
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "drop the executable bit")
    code, payload = _govern(target, reference, commit, capsys)
    assert code == 3, payload["reason"]
    assert payload["claim"]["base_matches_parent"] is False


def test_a_claim_diff_has_no_parent_tree_so_the_answer_is_null(tmp_path, capsys):
    reference = tmp_path / "reference"
    parent, commit = _reference(reference)
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", parent)
    diff = tmp_path / "change.diff"
    diff.write_bytes(subprocess.run(["git", "diff", parent, commit], cwd=str(reference), check=True,
                                    capture_output=True).stdout)
    code = main(["tagteam", str(target), "--claim-diff", str(diff), "--claim-subject", "the note", "--claim-author",
                 "Ada", "--authorize", "william", "--reason", "govern", "--scope", "documentation"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 3, payload["reason"]
    assert payload["claim"]["base_matches_parent"] is None
    assert payload["claim"]["target_tree_digest"] == payload["claim"]["base_tree_digest"]


def test_a_parent_tree_that_cannot_be_read_says_null(tmp_path):
    reference = tmp_path / "reference"
    parent, commit = _reference(reference)
    read = claim.from_commit(reference, commit)
    assert claim.parent_tree_digest(read) is not None
    broken = claim.Claim(subject=read.subject, author=read.author, diff=read.diff, files=read.files, commit=read.commit,
                         parent="0" * 40, tree=read.tree, date=read.date, repo=read.repo)
    assert claim.parent_tree_digest(broken) is None
    assert claim.parent_tree_digest(claim.Claim(subject="s", author="a", diff=b"", files=())) is None


def test_an_ordinary_drafter_run_has_null_for_the_comparison(tmp_path):
    from warden.authorization import grant
    from warden.claimrow import claim_row
    from warden.tagteam import TagTeam
    from fakes import FakeDrafter

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("from pkg import VALUE\n\n\ndef test_v():\n    assert VALUE == 1\n",
                                                  encoding="utf-8")
    (tmp_path / "NOTE.md").write_text("old note\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    auth = grant("william", "transform", str(tmp_path.resolve()), "documentation", "row test")
    result = TagTeam(drafter=FakeDrafter(steps=("new note\n",))).run(tmp_path, findings=[], authorization=auth)
    row = claim_row(result, auth)
    assert tuple(row) == KEYS and row["base_matches_parent"] is None
    assert row["target_tree_digest"] == result.baseline
