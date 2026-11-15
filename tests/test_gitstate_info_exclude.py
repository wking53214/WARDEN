"""A file hidden by `.git/info/exclude` is uncommitted work, even though `git status` does not list it.

`.git/info/exclude` lives inside the repository, so the neutral git configuration cannot switch it off. A planted file named
there (a conftest.py that turns a failing suite green, say) made a dirty folder look clean. The committed `.gitignore` is a
different matter: it is part of the tree a reader reviews, and what it ignores is still not seen (docs/LIMITS.md).
"""

import subprocess
from pathlib import Path

from warden import gitstate

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _repo(root: Path) -> Path:
    import os
    env = {**os.environ, **ENV}
    (root / "a.py").write_text("A = 1\n", encoding="utf-8")
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", *cmd], cwd=root, env=env, check=True, capture_output=True)
    return root


def test_a_clean_repository_is_clean(tmp_path):
    assert gitstate.tree_state(_repo(tmp_path)).kind == "clean"


def test_an_untracked_file_is_dirty_as_before(tmp_path):
    root = _repo(tmp_path)
    (root / "planted.py").write_text("print('hi')\n", encoding="utf-8")
    assert gitstate.tree_state(root).kind == "dirty"


def test_an_untracked_file_named_in_info_exclude_is_dirty(tmp_path):
    root = _repo(tmp_path)
    (root / ".git" / "info" / "exclude").write_text("planted.py\n", encoding="utf-8")
    (root / "planted.py").write_text("print('hi')\n", encoding="utf-8")
    state = gitstate.tree_state(root)
    assert state.kind == "dirty" and "info/exclude" in state.detail and "planted.py" in state.detail
    assert gitstate.is_dirty(root) is True


def test_a_whole_folder_named_in_info_exclude_is_dirty(tmp_path):
    root = _repo(tmp_path)
    (root / ".git" / "info" / "exclude").write_text("hidden/\n", encoding="utf-8")
    (root / "hidden").mkdir()
    (root / "hidden" / "conftest.py").write_text("", encoding="utf-8")
    assert gitstate.tree_state(root).kind == "dirty"


def test_info_exclude_naming_a_file_that_does_not_exist_changes_nothing(tmp_path):
    root = _repo(tmp_path)
    (root / ".git" / "info" / "exclude").write_text("nothing_here.py\n", encoding="utf-8")
    assert gitstate.tree_state(root).kind == "clean"


def test_a_path_in_allow_is_not_counted(tmp_path):
    root = _repo(tmp_path)
    (root / ".git" / "info" / "exclude").write_text("planted.py\n", encoding="utf-8")
    (root / "planted.py").write_text("print('hi')\n", encoding="utf-8")
    assert gitstate.tree_state(root, allow=("planted.py",)).kind == "clean"


def test_what_a_committed_gitignore_ignores_is_still_not_seen(tmp_path):
    """The known limit, kept as it is: the committed .gitignore is part of the reviewed tree (docs/LIMITS.md)."""
    import os
    env = {**os.environ, **ENV}
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("cache.bin\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, env=env, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "ignore"], cwd=root, env=env, check=True, capture_output=True)
    (root / "cache.bin").write_text("x", encoding="utf-8")
    assert gitstate.tree_state(root).kind == "clean"
