"""A `git replace` ref must not change what Warden sees.

`git replace <pin> <new>` then `git checkout <pin>` makes a checkout report the pinned commit and a clean status
while holding other content, and a claimed commit read through a replace ref gives the bytes of another commit. Before
0.16.6 Warden's git calls honoured replace refs. Every git call goes through `warden.gitstate._env`, which now sets
GIT_NO_REPLACE_OBJECTS=1.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from test_claim_landed import _GIT_ENV, _govern, _scene
from test_stack_option import measured  # noqa: F401 - a fixture
from test_stack_roster import _go, _roster_stack

from warden import gitstate


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
                          env=dict(_GIT_ENV, HOME=str(cwd)))
    return done.stdout.strip()


def _replace_head_with_other_content(repo: Path, name: str) -> str:
    """Commit B (other content) on top of the pinned commit A, `git replace A B`, `git checkout A`. Returns A."""
    pinned = _git(repo, "rev-parse", "HEAD")
    (repo / name).write_text("content that is not the pinned content\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "B")
    other = _git(repo, "rev-parse", "HEAD")
    _git(repo, "replace", pinned, other)
    _git(repo, "checkout", "-q", pinned)
    return pinned


def test_the_central_git_environment_ignores_replace_refs():
    assert gitstate._env()["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert gitstate._neutral_env()["GIT_NO_REPLACE_OBJECTS"] == "1"


def test_a_replace_ref_does_not_make_a_checkout_look_clean(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("pinned\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "A")
    pinned = _replace_head_with_other_content(repo, "a.txt")
    assert (repo / "a.txt").read_text(encoding="utf-8") != "pinned\n"   # the replace ref is in force for git itself
    assert gitstate.tree_state(repo).kind == "dirty"
    assert _git(repo, "rev-parse", "HEAD") == pinned


def test_a_stack_member_with_a_replace_ref_is_refused_naming_the_checkout(tmp_path, capsys, measured):  # noqa: F811
    stack, manifest = _roster_stack(tmp_path)
    _replace_head_with_other_content(stack / "judge", "MARK.md")
    code, payload, err, _target = _go(tmp_path, capsys, stack, manifest)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", (payload["reason"], err)
    assert "judge" in payload["reason"].lower() and payload["reason"].endswith("Nothing was run.")


def test_a_claimed_commit_is_read_without_its_replace_ref(tmp_path, capsys):
    reference, target, _parent, commit = _scene(tmp_path, b"A = 1\n", b"A = 2\n")
    (reference / "pkg" / "mod.py").write_bytes(b"A = 666\n")
    _git(reference, "add", "-A")
    _git(reference, "commit", "-q", "-m", "other")
    other = _git(reference, "rev-parse", "HEAD")
    _git(reference, "replace", commit, other)
    code, payload = _govern(target, reference, commit, capsys)
    row = payload["claim"]
    assert row["claimed_commit"] == commit
    (entry,) = row["files"]
    assert entry["after_sha256"] == hashlib.sha256(b"A = 2\n").hexdigest(), "the row names one SHA, the bytes must be its own"
