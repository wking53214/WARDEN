"""For the claim seat the actor's bytes are the thing governed: they are written exactly, and the row names what landed.

Writes used to keep a pure-CRLF file's line endings (`textio.encode_like`), so a claimed commit that turned CRLF into LF
left the file CRLF on disk while `claim.files[].after_sha256` reported the commit's blob, and the run ended on the claimed
digest. Now the claim seat writes the claimed blob exactly, the row's `after_sha256` is the digest of the bytes that
landed, and a landed digest that still differs from the claimed blob refuses the run (usage error, exit 2) before the
after-suite is measured, with everything put back. Drafter and Finisher edits keep `encode_like`.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from warden import held
from warden.cli import main
from warden.guard import Snapshot
from warden.models import Transformation

_GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.org", "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1"}

BASE = {"pkg/__init__.py": b"VALUE = 1\n",
        "tests/test_x.py": b"from pkg import VALUE\n\n\ndef test_v():\n    assert VALUE == 1\n",
        "pyproject.toml": b'[project]\nname = "demo"\nversion = "0.0.1"\n'}

#: name -> (the file before, the file in the claimed commit)
CASES = {
    "crlf_to_lf_with_a_content_change": (b"A = 1\r\nB = 2\r\n", b"A = 1\nB = 3\n"),
    "lf_to_crlf_with_a_content_change": (b"A = 1\nB = 2\n", b"A = 1\r\nB = 3\r\n"),
    "lf_to_crlf": (b"A = 1\nB = 2\n", b"A = 1\r\nB = 2\r\n"),
    "crlf_to_lf": (b"A = 1\r\nB = 2\r\n", b"A = 1\nB = 2\n"),
    "crlf_file_gets_mixed_endings": (b"A = 1\r\nB = 2\r\n", b"A = 1\r\nB = 2\nC = 3\r\n"),
    "lf_file_gets_mixed_endings": (b"A = 1\nB = 2\n", b"A = 1\r\nB = 2\nC = 3\r\n"),
    "binary_looking_but_utf8": (b"A = 1\n", b"A = 1\n# \x00\x01\x02 \xc3\xa9\n"),
    "no_final_newline_in_a_crlf_file": (b"A = 1\r\n", b"A = 1\r\nB = 2"),
    "final_newline_removed_from_lf_file": (b"A = 1\nB = 2\n", b"A = 1\nB = 2"),
    "byte_order_mark_added": (b"A = 1\r\n", b"\xef\xbb\xbfA = 1\r\n"),
}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
                          env=dict(_GIT_ENV, HOME=str(cwd)))
    return done.stdout.strip()


def _write(root: Path, files: dict) -> None:
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)


def _scene(tmp_path: Path, before: bytes, after: bytes):
    """A reference repository with a parent and a claimed commit that changes pkg/mod.py, and a clone at the parent."""
    reference = tmp_path / "reference"
    reference.mkdir()
    _git(reference, "init", "-q", "-b", "main")
    _write(reference, dict(BASE, **{"pkg/mod.py": before}))
    _git(reference, "add", "-A")
    _git(reference, "commit", "-q", "-m", "base")
    parent = _git(reference, "rev-parse", "HEAD")
    (reference / "pkg" / "mod.py").write_bytes(after)
    _git(reference, "add", "-A")
    _git(reference, "commit", "-q", "-m", "Step 1: change mod")
    commit = _git(reference, "rev-parse", "HEAD")
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", parent)
    return reference, target, parent, commit


def _govern(target: Path, reference: Path, commit: str, capsys):
    code = main(["tagteam", str(target), "--claim-commit", commit, "--claim-repo", str(reference),
                 "--authorize", "william", "--reason", "govern the real commit", "--scope", "code"])
    return code, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_claimed_bytes_land_exactly_and_the_row_digest_is_the_landed_digest(tmp_path, capsys, name):
    before, after = CASES[name]
    reference, target, _parent, commit = _scene(tmp_path, before, after)
    code, payload = _govern(target, reference, commit, capsys)
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED", payload["reason"]
    row = payload["claim"]
    (entry,) = row["files"]
    assert entry["path"] == "pkg/mod.py" and entry["before_sha256"] == hashlib.sha256(before).hexdigest()
    record = held.load(target, row["held_digest"])
    landed = held._unb64(record["files"])["pkg/mod.py"]
    assert landed == after, "the held tree must hold the claimed bytes, not an adaptation of them"
    assert entry["after_sha256"] == hashlib.sha256(landed).hexdigest() == hashlib.sha256(after).hexdigest()


def test_a_commit_that_turns_crlf_into_lf_does_not_leave_the_file_crlf(tmp_path, capsys):
    """The case the audit reproduced: the row said LF, the disk said CRLF, the run ended on the claimed digest."""
    before, after = CASES["crlf_to_lf_with_a_content_change"]
    reference, target, _parent, commit = _scene(tmp_path, before, after)
    code, payload = _govern(target, reference, commit, capsys)
    landed = held._unb64(held.load(target, payload["claim"]["held_digest"])["files"])["pkg/mod.py"]
    assert b"\r" not in landed and landed == after
    assert (target / "pkg" / "mod.py").read_bytes() == before   # the tree was put back byte for byte


def test_a_landed_digest_that_differs_from_the_claimed_blob_refuses_the_run_and_puts_everything_back(
        tmp_path, capsys, monkeypatch):
    before, after = CASES["lf_to_crlf_with_a_content_change"]
    reference, target, _parent, commit = _scene(tmp_path, before, after)
    original = Transformation.apply

    def altered(self, root):
        done = original(self, root)
        if self.claim is not None:
            with (Path(root) / "pkg" / "mod.py").open("ab") as fh:
                fh.write(b"# something else landed\n")
        return done

    monkeypatch.setattr(Transformation, "apply", altered)
    start = Snapshot(target).files
    code, payload = _govern(target, reference, commit, capsys)
    assert code == 2 and payload["decision"] == "USAGE_ERROR", payload
    reason = payload["reason"]
    assert "pkg/mod.py" in reason
    assert hashlib.sha256(after).hexdigest() in reason
    assert hashlib.sha256(after + b"# something else landed\n").hexdigest() in reason
    assert Snapshot(target).files == start, "everything must be put back"
    assert _git(target, "status", "--porcelain") == ""
    assert not payload.get("held_digest")


def test_a_drafter_edit_still_keeps_the_line_endings_of_the_file_it_replaces(tmp_path):
    """Only the claim seat is exact: a Drafter's or Finisher's write keeps a pure CRLF file CRLF."""
    from warden.authorization import grant
    from warden.models import FileEdit, TransformationStatus

    root = tmp_path / "t"
    root.mkdir()
    (root / "NOTE.md").write_bytes(b"one\r\ntwo\r\n")
    auth = grant("william", "transform", str(root.resolve()), "documentation", "line endings")
    proposal = Transformation(
        target=str(root.resolve()), intent="x", architectural_reason="x", affected_files=("NOTE.md",),
        expected_behavior="x", preservation_requirements=(), known_defects=(), transformation_scope="documentation",
        baseline_reference="fp", evidence=(),
        edits=(FileEdit(path="NOTE.md", kind="write", new="one\ntwo\nthree\n", old="one\ntwo\n"),),
        status=TransformationStatus.PROPOSED)
    proposal.authorize(auth)
    proposal.apply(root)
    assert (root / "NOTE.md").read_bytes() == b"one\r\ntwo\r\nthree\r\n"
