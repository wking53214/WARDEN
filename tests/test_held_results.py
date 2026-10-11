"""An unverified run is held, put back, and kept only under a human grant for its exact digest."""

import json
from pathlib import Path

import pytest

from warden import held
from warden.authorization import Authorization, grant
from warden.cli import main
from warden.tagteam import TagTeam

from fakes import FakeDrafter
from heldutil import keep_digest


def _repo(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (root / "NOTE.md").write_text("old note\n", encoding="utf-8")


def _run_unverified(root: Path):
    """A documentation change with no Judge: decided ACCEPT_UNVERIFIED, so it is held."""
    _repo(root)
    auth = grant("william", "transform", str(root.resolve()), "documentation", "held test")
    result = TagTeam(drafter=FakeDrafter(steps=("new note\n",))).run(root, findings=[], authorization=auth)
    assert result.decision == "ACCEPT_UNVERIFIED"
    assert result.put_back is True
    assert result.held_digest and len(result.held_digest) == 64
    return result


def test_unverified_change_is_put_back_and_its_digest_reported(tmp_path):
    result = _run_unverified(tmp_path)
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old note\n"
    assert any(result.held_digest in n for n in result.notes)


def test_nothing_is_kept_without_a_grant(tmp_path):
    result = _run_unverified(tmp_path)
    with pytest.raises(held.HeldError, match="No granted authorization"):
        held.keep(tmp_path, result.held_digest, None)
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old note\n"


def test_a_grant_for_a_different_digest_is_refused(tmp_path):
    result = _run_unverified(tmp_path)
    wrong = "0" * 64
    auth = grant("william", held.KEEP_OPERATION, f"{tmp_path.resolve()}@{wrong}", "held-result", "x")
    with pytest.raises(held.HeldError):
        held.keep(tmp_path, result.held_digest, auth)
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old note\n"


def test_an_ordinary_write_grant_cannot_keep_a_result(tmp_path):
    result = _run_unverified(tmp_path)
    auth = grant("william", "transform", f"{tmp_path.resolve()}@{result.held_digest}", "documentation", "x")
    with pytest.raises(held.HeldError, match="not 'keep_unverified'"):
        held.keep(tmp_path, result.held_digest, auth)


def test_a_part_of_the_stack_cannot_approve_even_if_it_claims_to(tmp_path):
    result = _run_unverified(tmp_path)
    forged = Authorization(actor="Drafter", operation=held.KEEP_OPERATION,
                           subject=f"{tmp_path.resolve()}@{result.held_digest}", scope="held-result",
                           reason="x", granted=True, at="now")
    with pytest.raises(held.HeldError, match="part of the stack"):
        held.keep(tmp_path, result.held_digest, forged)
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old note\n"


def test_a_folder_changed_after_the_run_is_not_overwritten(tmp_path):
    result = _run_unverified(tmp_path)
    (tmp_path / "NOTE.md").write_text("someone else edited this\n", encoding="utf-8")
    with pytest.raises(held.HeldError, match="not in the state the run started from"):
        keep_digest(tmp_path, result.held_digest)
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "someone else edited this\n"


def test_a_tampered_saved_result_is_refused(tmp_path):
    result = _run_unverified(tmp_path)
    path = held._dir(tmp_path) / f"{result.held_digest}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["files"]["NOTE.md"] = held._b64({"NOTE.md": b"tampered\n"})["NOTE.md"]
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(held.HeldError, match="does not match its digest"):
        keep_digest(tmp_path, result.held_digest)
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old note\n"


def test_an_approved_result_applies_exactly_once(tmp_path):
    result = _run_unverified(tmp_path)
    outcome = keep_digest(tmp_path, result.held_digest)
    assert outcome["decision"] == "KEPT"
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "new note\n"
    with pytest.raises(held.HeldError, match="not in the state the run started from"):
        keep_digest(tmp_path, result.held_digest)


def test_the_keep_command_refuses_without_a_person_and_applies_with_one(tmp_path, capsys):
    result = _run_unverified(tmp_path)
    assert main(["keep", str(tmp_path), "--digest", result.held_digest]) == 5  # REFUSED: nobody named
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old note\n"
    capsys.readouterr()
    code = main(["keep", str(tmp_path), "--digest", result.held_digest,
                 "--authorize", "William King", "--reason", "reviewed the diff"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "KEPT"
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "new note\n"
