"""The claim seat: a real change named by the operator is governed as a proposal, once, and nothing is guessed.

`--claim-commit SHA` reads the diff of SHA against its first parent (from the target's git or `--claim-repo`);
`--claim-diff FILE` reads a unified diff. Either takes the Drafter seat, so `--drafter` beside it is a usage error.
A binary file, a symbolic link, a submodule, a rename header, a mode change, or a target that is not at the change's
base is refused with a reason before anything runs.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from gitutil import commit_all, git

from warden import claim
from warden.cli import main
from warden.models import Transformation

_GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.org", "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> str:
    env = dict(_GIT_ENV, HOME=str(cwd))
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip()


def _repo_with_a_change(root: Path, remove: bool = True) -> tuple[str, str]:
    """A repository with a base commit and one commit on top that modifies, adds and (unless `remove` is off)
    deletes a text file. Returns (parent, commit)."""
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (root / "NOTE.md").write_text("old note\n", encoding="utf-8")
    (root / "gone.txt").write_text("to be removed\n", encoding="utf-8")
    commit_all(root, "base")
    parent = git(root, "rev-parse", "HEAD")
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\nNAME = 'demo'\n", encoding="utf-8")
    (root / "NEW.md").write_text("a new file\n", encoding="utf-8")
    if remove:
        (root / "gone.txt").unlink()
    git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "Step 1: name the package\n\nA body line.")
    return parent, git(root, "rev-parse", "HEAD")


def _git_diff_sha(root: Path, parent: str, commit: str) -> str:
    out = subprocess.run(["git", "diff", "--no-ext-diff", "--no-color", "--no-renames", "--src-prefix=a/",
                          "--dst-prefix=b/", parent, commit], cwd=str(root), check=True, capture_output=True).stdout
    return hashlib.sha256(out).hexdigest()


# -- reading a commit -------------------------------------------------------------------------------------

def test_a_commit_is_read_as_files_with_their_bytes_before_and_after(tmp_path):
    parent, commit = _repo_with_a_change(tmp_path)
    read = claim.from_commit(tmp_path, commit)
    assert (read.commit, read.parent) == (commit, parent)
    assert read.subject == "Step 1: name the package" and read.author == "Ada <ada@example.org>"
    assert read.tree == git(tmp_path, "rev-parse", f"{commit}^{{tree}}") and read.date.startswith("20")
    by_path = {f.path: f for f in read.files}
    assert {p: f.status for p, f in by_path.items()} == {"pkg/__init__.py": "M", "NEW.md": "A", "gone.txt": "D"}
    assert by_path["pkg/__init__.py"].before == b"VALUE = 1\n" and by_path["pkg/__init__.py"].after == b"VALUE = 1\nNAME = 'demo'\n"
    assert by_path["NEW.md"].before is None and by_path["gone.txt"].after is None
    assert read.diff_sha256 == _git_diff_sha(tmp_path, parent, commit) and len(read.diff) > 100
    row = read.to_dict()
    assert row["files"][0]["before_sha256"] is None or len(row["files"][0]["before_sha256"]) == 64
    assert json.loads(json.dumps(row)) == row


def test_a_short_sha_is_read_and_the_commit_is_recorded_in_full(tmp_path):
    _, commit = _repo_with_a_change(tmp_path)
    assert claim.from_commit(tmp_path, commit[:8]).commit == commit


def test_a_commit_is_read_from_a_reference_repository_the_target_does_not_hold(tmp_path):
    reference = tmp_path / "reference"
    parent, commit = _repo_with_a_change(reference)
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", parent)
    _git(target, "update-ref", "-d", "refs/remotes/origin/main")
    _git(target, "update-ref", "-d", "refs/heads/main")
    _git(target, "reflog", "expire", "--expire=now", "--all")
    _git(target, "gc", "-q", "--prune=now")
    with pytest.raises(claim.ClaimError):
        claim.from_commit(target, commit)  # the clone no longer holds the commit
    read = claim.from_commit(target, commit, repo=reference)
    assert read.commit == commit
    claim.check_base(target, read)  # the target stands at the parent


def test_a_root_commit_has_no_parent_and_is_refused(tmp_path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    commit_all(tmp_path)
    with pytest.raises(claim.ClaimError, match="no parent"):
        claim.from_commit(tmp_path, git(tmp_path, "rev-parse", "HEAD"))


def test_a_binary_file_in_the_commit_is_refused_not_guessed(tmp_path):
    _repo_with_a_change(tmp_path)
    (tmp_path / "logo.bin").write_bytes(b"\x89PNG\x00\x01\xff\xfe")
    git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "binary")
    with pytest.raises(claim.ClaimError, match="not UTF-8 text"):
        claim.from_commit(tmp_path, git(tmp_path, "rev-parse", "HEAD"))


def test_a_symbolic_link_in_the_commit_is_refused(tmp_path):
    _repo_with_a_change(tmp_path)
    (tmp_path / "alias.md").symlink_to("NOTE.md")
    git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "link")
    with pytest.raises(claim.ClaimError, match="symbolic link"):
        claim.from_commit(tmp_path, git(tmp_path, "rev-parse", "HEAD"))


def test_a_commit_that_is_not_in_the_repository_is_refused_with_gits_words(tmp_path):
    _repo_with_a_change(tmp_path)
    with pytest.raises(claim.ClaimError, match="rev-parse failed"):
        claim.from_commit(tmp_path, "0" * 40)


# -- reading a diff file ----------------------------------------------------------------------------------

def test_a_git_diff_file_applied_to_the_base_gives_the_commits_files(tmp_path):
    parent, commit = _repo_with_a_change(tmp_path)
    diff = subprocess.run(["git", "diff", "--no-renames", parent, commit], cwd=str(tmp_path), check=True,
                          capture_output=True).stdout
    patch = tmp_path.parent / "change.diff"
    patch.write_bytes(diff)
    _git(tmp_path, "checkout", "-q", parent)
    read = claim.from_diff(tmp_path, patch, "the change", "Ada")
    expected = {f.path: (f.status, f.after) for f in claim.from_commit(tmp_path, commit).files}
    assert {f.path: (f.status, f.after) for f in read.files} == expected
    assert read.commit is None and read.subject == "the change" and read.diff_sha256 == hashlib.sha256(diff).hexdigest()
    claim.check_base(tmp_path, read)


def test_a_plain_unified_diff_without_git_headers_is_read(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    patch = tmp_path.parent / "plain.diff"
    patch.write_text("--- a.txt\t2026-10-28\n+++ a.txt\t2026-10-28\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n",
                     encoding="utf-8")
    read = claim.from_diff(tmp_path, patch, "s", "a")
    assert [(f.path, f.status, f.after) for f in read.files] == [("a.txt", "M", b"one\nTWO\nthree\n")]


def test_a_diff_that_removes_the_last_newline_is_applied_exactly(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
    patch = tmp_path.parent / "nl.diff"
    patch.write_text("--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n one\n-two\n+two!\n\\ No newline at end of file\n",
                     encoding="utf-8")
    assert claim.from_diff(tmp_path, patch, "s", "a").files[0].after == b"one\ntwo!"


@pytest.mark.parametrize("header,why", [
    ("diff --git a/x.txt b/y.txt\nsimilarity index 100%\nrename from x.txt\nrename to y.txt\n", "rename"),
    ("diff --git a/x.txt b/x.txt\nindex 0000..1111 100644\nBinary files a/x.txt and b/x.txt differ\n", "binary"),
    ("diff --git a/x.txt b/x.txt\nold mode 100644\nnew mode 100755\n", "no hunks"),
])
def test_a_rename_a_binary_patch_and_a_mode_change_are_refused(tmp_path, header, why):
    (tmp_path / "x.txt").write_text("x\n", encoding="utf-8")
    patch = tmp_path.parent / "odd.diff"
    patch.write_text(header, encoding="utf-8")
    with pytest.raises(claim.ClaimError):
        claim.from_diff(tmp_path, patch, "s", "a")


def test_a_hunk_that_does_not_match_the_file_is_refused_not_fuzzed(tmp_path):
    (tmp_path / "a.txt").write_text("one\nTWO\nthree\n", encoding="utf-8")
    patch = tmp_path.parent / "stale.diff"
    patch.write_text("--- a/a.txt\n+++ b/a.txt\n@@ -1,3 +1,3 @@\n one\n-two\n+2\n three\n", encoding="utf-8")
    with pytest.raises(claim.ClaimError, match="does not match the file as it stands"):
        claim.from_diff(tmp_path, patch, "s", "a")


def test_a_target_that_is_not_at_the_changes_base_is_refused(tmp_path):
    parent, commit = _repo_with_a_change(tmp_path)
    read = claim.from_commit(tmp_path, commit)
    with pytest.raises(claim.ClaimError, match="not at the parent|not at the change's base"):
        claim.check_base(tmp_path, read)  # the target stands at the commit itself, not its parent
    _git(tmp_path, "checkout", "-q", parent)
    claim.check_base(tmp_path, read)


# -- the seat ----------------------------------------------------------------------------------------------

def test_the_seat_proposes_the_change_once_with_its_facts_as_evidence_and_then_nothing(tmp_path):
    parent, commit = _repo_with_a_change(tmp_path)
    _git(tmp_path, "checkout", "-q", parent)
    seat = claim.ClaimDrafter(claim.from_commit(tmp_path, commit))
    assert seat.requires_contract == "1" and hasattr(seat, "scope")
    proposal = seat.propose(tmp_path, (), "fp")
    assert isinstance(proposal, Transformation) and proposal.transformation_scope == "code"
    kinds = {e.path: e.kind for e in proposal.edits}
    assert kinds == {"pkg/__init__.py": "write", "NEW.md": "write", "gone.txt": "delete"}
    assert f"commit:{commit}" in proposal.evidence and f"parent:{parent}" in proposal.evidence
    assert any(e.startswith("diff_sha256:") for e in proposal.evidence)
    assert any(e.startswith("file:D:") and e.endswith(":gone.txt") for e in proposal.evidence)
    assert proposal.claim["commit"] == commit and proposal.claim["files"][0]["after_sha256"]
    assert seat.propose(tmp_path, (), "fp") is None


# -- the command line ----------------------------------------------------------------------------------------

def _payload(capsys):
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("extra", [
    ["--claim-commit", "abc", "--drafter", "x:Y"],
    ["--claim-commit", "abc", "--claim-diff", "d.diff"],
    ["--claim-diff", "d.diff"],
    ["--claim-diff", "d.diff", "--claim-subject", "s"],
    ["--claim-repo", "."],
    ["--claim-commit", "abc", "--claim-subject", "s"],
    ["--claim-diff", "d.diff", "--claim-subject", "s", "--claim-author", "a", "--claim-repo", "."],
])
def test_claim_options_that_contradict_each_other_or_the_drafter_are_a_usage_error(tmp_path, capsys, extra):
    _repo_with_a_change(tmp_path)
    code = main(["tagteam", str(tmp_path), *extra, "--authorize", "william", "--reason", "t"])
    payload = _payload(capsys)
    assert code == 2 and payload["decision"] == "USAGE_ERROR" and "Nothing was run" in payload["reason"]


def test_a_change_that_cannot_be_expressed_is_a_usage_error_before_anything_runs(tmp_path, capsys):
    _repo_with_a_change(tmp_path)
    (tmp_path / "logo.bin").write_bytes(b"\x00\xff\xfe")
    git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "binary")
    code = main(["tagteam", str(tmp_path), "--claim-commit", "HEAD", "--authorize", "william", "--reason", "t",
                 "--scope", "code"])
    payload = _payload(capsys)
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert "not UTF-8 text" in payload["reason"] and "Nothing was run" in payload["reason"]


def test_a_claimed_commit_is_governed_once_and_the_seat_is_named_in_the_record(tmp_path, capsys):
    """A commit that only adds (a deletion or a shrinking code file meets the removal gate like any proposal)."""
    reference = tmp_path / "reference"
    parent, commit = _repo_with_a_change(reference, remove=False)
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
    payload = _payload(capsys)
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED", payload["reason"]
    assert [c["outcome"] for c in payload["cycles"]] == ["APPLIED", "NOTHING_TO_PROPOSE"]
    assert payload["versions"]["seats"]["drafter"]["spec"] == "warden.claim:ClaimDrafter"
    assert payload["held_digest"] and not (target / "NEW.md").exists()  # held, so the tree was put back
