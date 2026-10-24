"""A seat's record names the code that ran. When the module sits in its own git checkout (the `--stack` case) that
checkout's version and commit are reported, not those of an older copy pip also installed.

Found by the 2026-10-23 self-hosting runs: JUDGE 0.4.8 was pip-installed beside a stack checkout of 0.4.10, the checkout's
code ran, and `versions.seats.judge` said 0.4.8. The same happened to the finisher (Burnish 0.3.12 ran, the record said
0.3.11).
"""

import importlib
import json
import subprocess
import sys

import pytest

from warden import versions

INSTALLED_COMMIT = "a" * 40


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(cwd)}).stdout.strip()


def _checkout(root, package, version):
    (root / package).mkdir(parents=True)
    (root / package / "__init__.py").write_text("", encoding="utf-8")
    (root / package / "seat.py").write_text("class Seat:\n    requires_contract = '1'\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(f'[project]\nname = "{package}"\nversion = "{version}"\n', encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "one")
    return _git(root, "rev-parse", "HEAD")


def _installed_dist(site, package, version):
    """A distribution as pip records it: metadata, the top-level name and a direct_url.json with a commit. The package
    files are not there; the record alone is what `_installed` reads."""
    info = site / f"{package}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {package}\nVersion: {version}\n", encoding="utf-8")
    (info / "top_level.txt").write_text(package + "\n", encoding="utf-8")
    (info / "direct_url.json").write_text(json.dumps(
        {"url": "https://example.invalid/x.git", "vcs_info": {"vcs": "git", "commit_id": INSTALLED_COMMIT}}),
        encoding="utf-8")


@pytest.fixture
def paths(monkeypatch):
    """Put folders on sys.path for one test and forget the seat module afterwards."""
    added = []

    def add(folder):
        monkeypatch.syspath_prepend(str(folder))
        added.append(folder)
        importlib.invalidate_caches()
    yield add
    for name in [n for n in sys.modules if n.split(".")[0].startswith("zseat_")]:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("kind", ["drafter", "finisher", "judge"])
def test_a_seat_in_a_stack_checkout_reports_the_checkout_not_the_older_installed_copy(tmp_path, paths, kind):
    package = f"zseat_{kind}"
    site, stack = tmp_path / "site", tmp_path / "stack" / kind.upper()
    site.mkdir()
    _installed_dist(site, package, "0.4.8")
    sha = _checkout(stack, package, "0.4.10")
    paths(site)
    paths(stack)  # prepended last: the stack checkout is imported first, as `--stack` arranges
    got = versions.seat(f"{package}.seat:Seat", object(), tmp_path / "target")
    assert got["version"] == "0.4.10" and got["commit"] == sha, got
    assert got["dirty"] is False


def test_a_seat_with_only_an_install_record_still_reports_that_record(tmp_path, paths):
    """No checkout of its own (an ordinary pip install): the install record is the only source and is used."""
    site = tmp_path / "site"
    site.mkdir()
    _installed_dist(site, "zseat_plain", "1.2.3")
    (site / "zseat_plain").mkdir()
    (site / "zseat_plain" / "__init__.py").write_text("", encoding="utf-8")
    paths(site)
    got = versions.seat("zseat_plain:Seat", object(), tmp_path / "target")
    assert got["version"] == "1.2.3" and got["commit"] == INSTALLED_COMMIT


def test_a_checkout_whose_version_cannot_be_read_does_not_borrow_the_installed_copys(tmp_path, paths):
    package = "zseat_noversion"
    site, stack = tmp_path / "site", tmp_path / "stack"
    site.mkdir()
    _installed_dist(site, package, "0.4.8")
    sha = _checkout(stack, package, "0.4.10")
    (stack / "pyproject.toml").write_text('[project]\nname = "x"\ndynamic = ["version"]\n', encoding="utf-8")
    _git(stack, "commit", "-q", "-am", "dynamic")
    paths(site)
    paths(stack)
    got = versions.seat(f"{package}:Seat", object(), tmp_path / "target")
    assert got["version"] is None and got["commit"] == _git(stack, "rev-parse", "HEAD") != sha


def test_an_instrument_root_reports_its_own_checkout_whatever_is_installed(tmp_path, paths):
    site, root = tmp_path / "site", tmp_path / "stack" / "SWIZZLE"
    site.mkdir()
    _installed_dist(site, "zseat_inst", "0.8.1")
    sha = _checkout(root, "zseat_inst", "0.8.8")
    paths(site)
    got = versions.instrument(root, "zseat_inst")
    assert got["version"] == "0.8.8" and got["commit"] == sha and got["dirty"] is False
