"""The origin a run records never carries a credential.

`origin_of` recorded the raw `remote.origin.url`, so `https://user:ghp_...@host/...` appeared in `claim.origin`, the held
file, the receipt and the chronicle's file name and lines, even on an observe-only run. Userinfo (and a token-like query or
fragment parameter) is stripped before anything is recorded or slugged; a URL without a secret is unchanged.
"""

import json
import subprocess
from pathlib import Path

import pytest

from warden import chronicle
from warden.claimrow import origin_of, strip_credentials
from warden.cli import main

SECRET = "ghp_Sup3rS3cretT0ken0123456789"

_GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.org", "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
                          env=dict(_GIT_ENV, HOME=str(cwd)))
    return done.stdout.strip()


CASES = {
    "https with user and token": (f"https://octocat:{SECRET}@github.com/acme/widget.git", "https://github.com/acme/widget.git"),
    "https with a token as the user": (f"https://{SECRET}@github.com/acme/widget.git", "https://github.com/acme/widget.git"),
    "https with an @ in the password": (f"https://u:p@ss{SECRET}@example.org/r.git", "https://example.org/r.git"),
    "ssh with a user": ("ssh://git@example.org:2222/acme/widget.git", "ssh://example.org:2222/acme/widget.git"),
    "scp style with a user": ("git@github.com:acme/widget.git", "github.com:acme/widget.git"),
    "https with a token in the query": (f"https://example.org/r.git?private_token={SECRET}&ref=main",
                                        "https://example.org/r.git?ref=main"),
    "https with a token in the fragment": (f"https://example.org/r.git#access_token={SECRET}", "https://example.org/r.git"),
    "https with userinfo and a query token": (f"https://u:{SECRET}@example.org/r.git?token={SECRET}",
                                              "https://example.org/r.git"),
    "no userinfo": ("https://github.com/acme/widget.git", "https://github.com/acme/widget.git"),
    "scp style without a user": ("example.org:acme/widget.git", "example.org:acme/widget.git"),
    "a local path": ("/srv/git/widget.git", "/srv/git/widget.git"),
    "a file url": ("file:///srv/git/widget.git", "file:///srv/git/widget.git"),
    "a harmless query is kept": ("https://example.org/r.git?ref=main", "https://example.org/r.git?ref=main"),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_credentials_are_stripped_and_everything_else_is_unchanged(name):
    raw, expected = CASES[name]
    assert strip_credentials(raw) == expected
    assert SECRET not in strip_credentials(raw)


@pytest.mark.parametrize("name", sorted(CASES))
def test_origin_of_reads_the_remote_and_strips_it(tmp_path, name):
    raw, expected = CASES[name]
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "remote", "add", "origin", raw)
    assert origin_of(tmp_path) == expected


def test_a_repository_with_no_remote_has_no_origin(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    assert origin_of(tmp_path) is None


def _scene(tmp_path: Path):
    reference = tmp_path / "reference"
    (reference / "pkg").mkdir(parents=True)
    _git(reference, "init", "-q", "-b", "main")
    (reference / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (reference / "tests").mkdir()
    (reference / "tests" / "test_x.py").write_text("from pkg import VALUE\n\n\ndef test_v():\n    assert VALUE == 1\n",
                                                   encoding="utf-8")
    (reference / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (reference / "NOTE.md").write_text("old note\n", encoding="utf-8")
    _git(reference, "add", "-A")
    _git(reference, "commit", "-q", "-m", "base")
    parent = _git(reference, "rev-parse", "HEAD")
    (reference / "NOTE.md").write_text("new note\n", encoding="utf-8")
    _git(reference, "add", "-A")
    _git(reference, "commit", "-q", "-m", "Step 1: the note")
    commit = _git(reference, "rev-parse", "HEAD")
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", parent)
    _git(target, "remote", "set-url", "origin", f"https://octocat:{SECRET}@github.com/acme/widget.git")
    return reference, target, commit


def test_no_output_of_a_run_holds_the_secret(tmp_path, capsys):
    reference, target, commit = _scene(tmp_path)
    chron = tmp_path / "chronicle"
    receipt = tmp_path / "receipt.json"
    code = main(["tagteam", str(target), "--claim-commit", commit, "--claim-repo", str(reference),
                 "--authorize", "william", "--reason", "govern", "--scope", "documentation", "--chronicle", str(chron),
                 "--receipt", str(receipt)])
    out, err = capsys.readouterr()
    assert code == 3, out
    payload = json.loads(out)
    assert payload["claim"]["origin"] == "https://github.com/acme/widget.git"
    assert SECRET not in out and SECRET not in err
    outputs = [p for folder in (chron, tmp_path) for p in folder.rglob("*") if p.is_file()]
    outputs = [p for p in outputs if target not in p.parents and reference not in p.parents]
    assert receipt in outputs and any(p.parent == chron for p in outputs)
    names = [p.name for p in chron.iterdir()]
    assert names and all(SECRET not in n for n in names)
    for path in outputs:
        assert SECRET.encode() not in path.read_bytes(), f"{path} holds the secret"


def test_the_chronicle_reader_finds_the_chain_when_asked_for_the_origin_with_its_secret(tmp_path, capsys):
    reference, target, commit = _scene(tmp_path)
    chron = tmp_path / "chronicle"
    main(["tagteam", str(target), "--claim-commit", commit, "--claim-repo", str(reference), "--authorize", "william",
          "--reason", "govern", "--scope", "documentation", "--chronicle", str(chron)])
    capsys.readouterr()
    code = main(["chronicle", str(chron), "--origin", f"https://octocat:{SECRET}@github.com/acme/widget.git"])
    out, err = capsys.readouterr()
    assert code == 0 and SECRET not in out + err
    assert "no readable line" not in err
    assert chronicle.slug("https://github.com/acme/widget.git") in " ".join(p.name for p in chron.iterdir())
