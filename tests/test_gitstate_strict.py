"""The dirty check cannot be talked out of an answer by the asker's git configuration or by index flags.

`git status` honours the user's own configuration and two per-file index flags, and each of them can make an
edited or planted file invisible: `git update-index --assume-unchanged`, `--skip-worktree`, a global
`status.showUntrackedFiles=no`, a global `core.excludesFile`, and `core.fileMode=false`. The check backs a trust
decision (a stack checkout that is about to be imported or read as an instrument), so it must give the same answer
whoever asks. User configuration is simulated here with HOME and XDG_CONFIG_HOME pointing at a temporary folder.
Nothing is written outside tmp dirs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from gitutil import commit_all, git
from warden import gitstate
from warden.gitstate import tree_state


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home folder for the user's git configuration; Warden's own git calls inherit it."""
    folder = tmp_path / "home"
    folder.mkdir()
    for var in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(folder))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(folder))
    return folder


def _repo(root: Path) -> Path:
    root.mkdir()
    (root / "seat.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "other.py").write_text("OTHER = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n*.log\n", encoding="utf-8")
    commit_all(root)
    return root


def _users_git_says(repo: Path, home: Path) -> str:
    """`git status --porcelain` as the user's own git, with the fake home's configuration, answers."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home))
    return subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), env=env, capture_output=True, text=True,
                          check=True).stdout.strip()


def _config(home: Path, text: str) -> None:
    (home / ".gitconfig").write_text(text, encoding="utf-8")


def test_a_clean_repository_is_clean_with_or_without_user_configuration(tmp_path, home):
    repo = _repo(tmp_path / "r")
    assert tree_state(repo).kind == "clean"
    _config(home, "[status]\n\tshowUntrackedFiles = no\n[core]\n\tfileMode = false\n")
    assert tree_state(repo).kind == "clean"


def test_assume_unchanged_hides_an_edit_from_git_and_not_from_warden(tmp_path, home):
    repo = _repo(tmp_path / "r")
    (repo / "seat.py").write_text("VALUE = 'tampered'\n", encoding="utf-8")
    git(repo, "update-index", "--assume-unchanged", "seat.py")
    assert _users_git_says(repo, home) == ""          # the bypass is real: git status says nothing
    state = tree_state(repo)
    assert state.kind == "dirty" and state.hidden == 1 and state.changed == 1
    assert "assume-unchanged" in state.detail and "seat.py" in state.detail


def test_skip_worktree_hides_an_edit_from_git_and_not_from_warden(tmp_path, home):
    repo = _repo(tmp_path / "r")
    (repo / "seat.py").write_text("VALUE = 'tampered'\n", encoding="utf-8")
    git(repo, "update-index", "--skip-worktree", "seat.py")
    assert _users_git_says(repo, home) == ""
    state = tree_state(repo)
    assert state.kind == "dirty" and state.hidden == 1 and "skip-worktree" in state.detail


def test_an_index_flag_on_an_unmodified_file_is_refused_too(tmp_path, home):
    """The flag itself is the problem: the next edit to that file would not show."""
    repo = _repo(tmp_path / "r")
    git(repo, "update-index", "--assume-unchanged", "other.py")
    assert _users_git_says(repo, home) == ""
    assert tree_state(repo).kind == "dirty"


def test_index_flags_are_found_from_a_subfolder_and_counted_with_other_changes(tmp_path, home):
    repo = _repo(tmp_path / "r")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "inner.py").write_text("X = 1\n", encoding="utf-8")
    commit_all(repo, "pkg")
    git(repo, "update-index", "--skip-worktree", "seat.py")
    (repo / "stray.txt").write_text("x\n", encoding="utf-8")
    state = tree_state(repo / "pkg")
    assert state.kind == "dirty" and state.changed == 2 and state.hidden == 1


def test_a_global_show_untracked_files_no_does_not_hide_a_planted_file(tmp_path, home):
    repo = _repo(tmp_path / "r")
    _config(home, "[status]\n\tshowUntrackedFiles = no\n")
    (repo / "planted.py").write_text("print('planted')\n", encoding="utf-8")
    assert _users_git_says(repo, home) == ""
    state = tree_state(repo)
    assert state.kind == "dirty" and state.changed == 1


def test_a_global_excludes_file_does_not_hide_a_planted_file(tmp_path, home):
    repo = _repo(tmp_path / "r")
    (home / "ignore").write_text("planted.py\n", encoding="utf-8")
    _config(home, f"[core]\n\texcludesFile = {home / 'ignore'}\n")
    (repo / "planted.py").write_text("print('planted')\n", encoding="utf-8")
    assert _users_git_says(repo, home) == ""
    state = tree_state(repo)
    assert state.kind == "dirty" and state.changed == 1


def test_the_default_global_ignore_file_does_not_hide_a_planted_file(tmp_path, home):
    """With no core.excludesFile set, git reads $XDG_CONFIG_HOME/git/ignore."""
    repo = _repo(tmp_path / "r")
    (home / "git").mkdir()
    (home / "git" / "ignore").write_text("planted.py\n", encoding="utf-8")
    (repo / "planted.py").write_text("print('planted')\n", encoding="utf-8")
    assert _users_git_says(repo, home) == ""
    assert tree_state(repo).kind == "dirty"


@pytest.mark.parametrize("where", ["global", "repository"])
def test_file_mode_false_does_not_hide_a_chmod(tmp_path, home, where):
    repo = _repo(tmp_path / "r")
    if where == "global":
        # git init records core.fileMode in the repository on a normal filesystem, which beats the global file;
        # take it out so the user's setting is the one that applies, as on a repository that never recorded one.
        git(repo, "config", "--unset", "core.fileMode")
        _config(home, "[core]\n\tfileMode = false\n")
    else:
        git(repo, "config", "core.fileMode", "false")
    (repo / "seat.py").chmod(0o755)
    assert _users_git_says(repo, home) == ""
    state = tree_state(repo)
    assert state.kind == "dirty" and state.changed == 1


def test_a_nested_untracked_folder_is_counted_file_by_file(tmp_path, home):
    repo = _repo(tmp_path / "r")
    (repo / "newdir").mkdir()
    (repo / "newdir" / "a.py").write_text("a\n", encoding="utf-8")
    (repo / "newdir" / "b.py").write_text("b\n", encoding="utf-8")
    state = tree_state(repo)
    assert state.kind == "dirty" and state.changed == 2


def test_files_ignored_by_the_repositorys_own_gitignore_are_still_accepted(tmp_path, home):
    repo = _repo(tmp_path / "r")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "seat.cpython-312.pyc").write_bytes(b"x")
    (repo / "run.log").write_text("log\n", encoding="utf-8")
    assert tree_state(repo).kind == "clean"


def test_the_allowed_file_is_not_counted_even_when_flagged(tmp_path, home):
    repo = _repo(tmp_path / "r")
    (repo / "WARDEN_AUDIT.md").write_text("audit\n", encoding="utf-8")
    commit_all(repo, "audit")
    git(repo, "update-index", "--assume-unchanged", "WARDEN_AUDIT.md")
    (repo / "WARDEN_AUDIT.md").write_text("audit, edited\n", encoding="utf-8")
    assert tree_state(repo, allow=("WARDEN_AUDIT.md",)).kind == "clean"
    assert tree_state(repo).kind == "dirty"


def test_warden_does_not_use_the_users_git_aliases_or_settings(tmp_path, home):
    """Neutral means neutral: an alias or a setting in the user's file does not reach Warden's git calls."""
    repo = _repo(tmp_path / "r")
    _config(home, "[alias]\n\tstatus = !echo hijacked\n[status]\n\tshort = true\n")
    assert tree_state(repo).kind == "clean"
    (repo / "x.txt").write_text("x\n", encoding="utf-8")
    assert tree_state(repo).kind == "dirty"


# -- the refusals that already held keep holding ----------------------------------------------------------

def test_a_stray_index_lock_is_still_unknown(tmp_path, home):
    repo = _repo(tmp_path / "r")
    (repo / ".git" / "index.lock").write_text("", encoding="utf-8")
    state = tree_state(repo)
    assert state.kind == "unknown" and "index.lock" in state.detail


def test_a_corrupt_index_is_still_unknown(tmp_path, home):
    repo = _repo(tmp_path / "r")
    (repo / ".git" / "index").write_bytes(b"not an index at all")
    assert tree_state(repo).kind == "unknown"


def test_missing_objects_are_still_unknown(tmp_path, home):
    repo = _repo(tmp_path / "r")
    objects = repo / ".git" / "objects"
    for entry in objects.iterdir():
        if len(entry.name) == 2:
            for blob in entry.iterdir():
                blob.chmod(0o644)
                blob.unlink()
    assert tree_state(repo).kind == "unknown"


def test_a_folder_that_is_not_a_repository_is_still_not_git(tmp_path, home):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert tree_state(plain).kind == "not_git"


def test_git_that_cannot_be_run_is_unknown_inside_a_repository(tmp_path, home, monkeypatch):
    repo = _repo(tmp_path / "r")
    monkeypatch.setattr(gitstate, "_neutral_env", lambda: (_ for _ in ()).throw(OSError("no temp folder")))
    assert tree_state(repo).kind == "unknown"


def test_the_empty_config_lives_in_one_temp_folder_per_process(tmp_path, home):
    first = gitstate._empty_config()
    assert gitstate._empty_config() == first
    assert (first / "gitconfig").read_text(encoding="utf-8") == ""
