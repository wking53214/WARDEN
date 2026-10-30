"""A claimed change may not go through a symbolic link, and a claim diff must be a regular file.

A `--claim-diff` naming `inlink.py` (a link to `pkg/__init__.py`) changed the link's target, because the base check
followed the link. Any claimed path whose own entry or any parent component is a symbolic link is now refused (lstat on
each component) with exit 2 and nothing written. `--claim-diff FIFO` blocked forever on open; the diff must be a regular
file (stat, S_ISREG) before it is opened, and anything else is exit 2.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from warden import claim
from warden.cli import main

_GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.org", "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
                          env=dict(_GIT_ENV, HOME=str(cwd)))
    return done.stdout.strip()


def _target(root: Path) -> Path:
    """A clean repository with a package, a file link to it and a folder link to the package folder."""
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (root / "inlink.py").symlink_to("pkg/__init__.py")
    (root / "pkglink").symlink_to("pkg")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _diff(path: Path, header_path: str) -> Path:
    path.write_text(f"--- a/{header_path}\n+++ b/{header_path}\n@@ -1 +1,2 @@\n VALUE = 1\n+NAME = 'demo'\n",
                    encoding="utf-8")
    return path


def _run(target: Path, diff: Path, capsys):
    code = main(["tagteam", str(target), "--claim-diff", str(diff), "--claim-subject", "name it", "--claim-author", "Ada",
                 "--authorize", "william", "--reason", "t", "--scope", "code"])
    return code, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("named", ["inlink.py", "pkglink/__init__.py"])
def test_a_diff_naming_a_path_through_a_link_is_refused_and_nothing_changes(tmp_path, capsys, named):
    target = _target(tmp_path / "t")
    diff = _diff(tmp_path / "change.diff", named)
    before = (target / "pkg" / "__init__.py").read_bytes()
    code, payload = _run(target, diff, capsys)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", payload
    assert named.split("/")[0] in payload["reason"] and "symbolic link" in payload["reason"]
    assert (target / "pkg" / "__init__.py").read_bytes() == before
    assert (target / "inlink.py").is_symlink() and (target / "pkglink").is_symlink()
    assert _git(target, "status", "--porcelain") == ""


def test_the_check_names_the_component_that_is_the_link(tmp_path):
    target = _target(tmp_path / "t")
    with pytest.raises(claim.ClaimError, match="pkglink"):
        claim.from_diff(target, _diff(tmp_path / "c.diff", "pkglink/__init__.py"), "s", "a")


def test_a_commit_that_adds_a_file_below_a_link_is_refused_by_the_base_check(tmp_path):
    target = _target(tmp_path / "t")
    added = claim.Claim(subject="s", author="a", diff=b"", files=(claim.ClaimedFile("pkglink/new.py", "A", None, b"x\n"),))
    with pytest.raises(claim.ClaimError, match="symbolic link"):
        claim.check_base(target, added)


def test_an_ordinary_path_is_still_accepted(tmp_path):
    target = _target(tmp_path / "t")
    read = claim.from_diff(target, _diff(tmp_path / "c.diff", "pkg/__init__.py"), "s", "a")
    claim.check_base(target, read)
    assert [f.path for f in read.files] == ["pkg/__init__.py"]


def test_a_fifo_as_the_claim_diff_is_exit_2_not_a_hang(tmp_path):
    target = _target(tmp_path / "t")
    fifo = tmp_path / "pipe.diff"
    os.mkfifo(fifo)
    code = ("from warden.cli import main; raise SystemExit(main(['tagteam', %r, '--claim-diff', %r, '--claim-subject', 's', "
            "'--claim-author', 'a', '--authorize', 'william', '--reason', 't', '--scope', 'code']))" % (str(target), str(fifo)))
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
    assert json.loads(done.stdout)["decision"] == "USAGE_ERROR"
    assert "regular file" in done.stderr


def test_a_folder_as_the_claim_diff_is_refused_the_same_way(tmp_path):
    target = _target(tmp_path / "t")
    with pytest.raises(claim.ClaimError, match="regular file"):
        claim.from_diff(target, tmp_path, "s", "a")
