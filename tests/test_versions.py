"""`versions` reads commits and version strings from files, and says None when it cannot."""

import subprocess

from warden import versions


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(cwd)})


def _repo(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "one")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True,
                          check=True).stdout.strip()


def test_the_commit_and_version_of_a_checkout_are_read_without_running_git(tmp_path):
    sha = _repo(tmp_path)
    got = versions.instrument(tmp_path)
    assert got == {"path": str(tmp_path.resolve()), "commit": sha, "version": "1.2.3", "dirty": False}


def test_a_commit_is_found_from_packed_refs_and_from_a_subfolder(tmp_path):
    sha = _repo(tmp_path)
    _git(tmp_path, "pack-refs", "--all")
    (tmp_path / "sub").mkdir()
    assert versions.git_commit(tmp_path / "sub") == sha


def test_a_detached_head_is_read(tmp_path):
    sha = _repo(tmp_path)
    _git(tmp_path, "checkout", "-q", "--detach")
    assert versions.git_commit(tmp_path) == sha


def test_a_folder_that_is_not_a_checkout_reports_none_not_a_guess(tmp_path):
    got = versions.instrument(tmp_path)
    assert got["commit"] is None and got["version"] is None


def test_nothing_given_is_none():
    assert versions.instrument(None) is None
    assert versions.seat(None, object()) is None


def test_a_broken_pyproject_is_none(tmp_path):
    (tmp_path / "pyproject.toml").write_text("not [ toml", encoding="utf-8")
    assert versions.project_version(tmp_path) is None


# -- round 3: a root's own commit only, a dirty flag, and nothing borrowed from the target ----------

def test_a_folder_inside_someone_elses_repo_does_not_borrow_that_repos_commit(tmp_path):
    sha = _repo(tmp_path)
    inner = tmp_path / "vendored_instrument"
    inner.mkdir()
    (inner / "pyproject.toml").write_text('[project]\nname = "i"\nversion = "9.9.9"\n', encoding="utf-8")
    got = versions.instrument(inner)
    assert got["commit"] is None and got["dirty"] is None and got["version"] == "9.9.9"
    assert versions.instrument(tmp_path)["commit"] == sha


def test_dirty_is_true_when_the_checkout_has_uncommitted_work(tmp_path):
    _repo(tmp_path)
    (tmp_path / "scratch.txt").write_text("x", encoding="utf-8")
    assert versions.instrument(tmp_path)["dirty"] is True


def test_a_seat_in_the_target_never_reports_the_targets_commit(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "judgeseat_t.py").write_text("class J: requires_contract = '1'\n", encoding="utf-8")
    (target / "pyproject.toml").write_text('[project]\nname = "t"\nversion = "1.0.0"\n', encoding="utf-8")
    sha = _repo(target)
    import sys
    sys.path.insert(0, str(target))
    try:
        got = versions.seat("judgeseat_t:J", object(), target)
    finally:
        sys.path.remove(str(target))
        sys.modules.pop("judgeseat_t", None)
    assert sha and got["commit"] is None and got["dirty"] is None
