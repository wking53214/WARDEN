"""A held deletion of an executable file leaves the tree exactly as found, executable bit included.

The snapshot restore wrote a deleted file back with the default mode (644), so after a claimed `git rm run.sh` of a
mode-755 file `git status` showed `M run.sh`, `warden keep` was refused (the tree fingerprint includes the executable
bit) and the next run was refused as dirty. The snapshot now records each file's mode and gives it back: the file is
created with the recorded mode and chmod-ed after it is written.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

from warden.cli import main
from warden.guard import Snapshot
from warden.tagteam import _fingerprint, _restore, _snapshot

_GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.org", "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
                          env=dict(_GIT_ENV, HOME=str(cwd)))
    return done.stdout.strip()


def _scene(tmp_path: Path):
    """A reference repository whose second commit deletes the mode-755 run.sh, and a clone at the first commit."""
    reference = tmp_path / "reference"
    (reference / "pkg").mkdir(parents=True)
    _git(reference, "init", "-q", "-b", "main")
    (reference / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (reference / "tests").mkdir()
    (reference / "tests" / "test_x.py").write_text("from pkg import VALUE\n\n\ndef test_v():\n    assert VALUE == 1\n",
                                                   encoding="utf-8")
    (reference / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    script = reference / "run.sh"
    script.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
    script.chmod(0o755)
    _git(reference, "add", "-A")
    _git(reference, "commit", "-q", "-m", "base")
    parent = _git(reference, "rev-parse", "HEAD")
    _git(reference, "rm", "-q", "run.sh")
    _git(reference, "commit", "-q", "-m", "Step 1: drop the script")
    commit = _git(reference, "rev-parse", "HEAD")
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", parent)
    return reference, target, commit


def test_a_held_claimed_deletion_of_an_executable_leaves_a_clean_tree_and_keep_succeeds(tmp_path, capsys):
    reference, target, commit = _scene(tmp_path)
    assert stat.S_IMODE((target / "run.sh").stat().st_mode) & 0o111, "the fixture needs an executable run.sh"
    fingerprint = _fingerprint(target)
    code = main(["tagteam", str(target), "--claim-commit", commit, "--claim-repo", str(reference),
                 "--authorize", "william", "--reason", "govern the deletion", "--scope", "code"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED", payload["reason"]
    digest = payload["held_digest"]
    assert digest and (target / "run.sh").is_file()
    assert os.access(target / "run.sh", os.X_OK) and stat.S_IMODE((target / "run.sh").stat().st_mode) == 0o755
    assert _git(target, "status", "--porcelain") == "", "the tree must be clean: no `M run.sh`"
    assert _fingerprint(target) == fingerprint
    code = main(["keep", str(target), "--digest", digest, "--authorize", "william", "--reason", "reviewed"])
    kept = json.loads(capsys.readouterr().out)
    assert code == 0 and kept["decision"] == "KEPT", kept
    assert not (target / "run.sh").exists()


def test_the_snapshot_gives_back_each_files_mode(tmp_path):
    (tmp_path / "a.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "a.sh").chmod(0o755)
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    (tmp_path / "b.txt").chmod(0o600)
    snap = Snapshot(tmp_path)
    (tmp_path / "a.sh").unlink()
    (tmp_path / "b.txt").unlink()
    snap.restore()
    assert stat.S_IMODE((tmp_path / "a.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE((tmp_path / "b.txt").stat().st_mode) == 0o600


def test_the_proposal_snapshot_gives_back_a_deleted_executable_too(tmp_path):
    from warden.models import FileEdit, Transformation, TransformationStatus

    (tmp_path / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "run.sh").chmod(0o755)
    proposal = Transformation(
        target=str(tmp_path), intent="x", architectural_reason="x", affected_files=("run.sh",), expected_behavior="x",
        preservation_requirements=(), known_defects=(), transformation_scope="code", baseline_reference="fp",
        evidence=(), edits=(FileEdit(path="run.sh", kind="delete", new=""),), status=TransformationStatus.PROPOSED)
    snapshot = _snapshot(tmp_path, proposal)
    (tmp_path / "run.sh").unlink()
    _restore(tmp_path, snapshot)
    assert stat.S_IMODE((tmp_path / "run.sh").stat().st_mode) == 0o755
