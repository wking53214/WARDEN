"""Warden reads SWIZZLE's output only from a SWIZZLE that declares the contract Warden supports.

`swizzle --contract` (SWIZZLE's docs/CONTRACT.md) prints a JSON document. A SWIZZLE with no such flag, a
different contract number, or another tool answering as SWIZZLE is not believed: the proof gate counts as
unmeasured, nothing is written, and the record says why. A matching SWIZZLE changes nothing.
"""

import json
import subprocess
from pathlib import Path

import pytest

import warden.swizzle as swizzle
import warden.tagteam as tagteam
from warden.authorization import grant
from warden.tagteam import TagTeam

from fakes import FakeDrafter
from gitutil import commit_all

GOOD = {"name": "swizzle", "contract": 1, "swizzle_version": "0.8.0", "invocation": ["python", "-m", "swizzle.cli"]}
HOLDS = "12 of 12 proofs hold.\n"


def _proc(out="", err="", code=0):
    return subprocess.CompletedProcess([], code, stdout=out, stderr=err)


def _swizzle(monkeypatch, contract=None, contract_code=0, contract_err=""):
    """A SWIZZLE whose `--contract` answers as given and whose `prove` holds. Records every command run."""
    seen = []

    def fake(cmd, **kw):
        seen.append(list(cmd))
        if "--contract" in cmd:
            out = contract if isinstance(contract, str) else json.dumps(contract)
            return _proc(out, contract_err, contract_code)
        return _proc(HOLDS)
    monkeypatch.setattr(swizzle, "run_instrument", fake)
    return seen


def test_a_swizzle_that_declares_the_supported_contract_is_confirmed(monkeypatch):
    seen = _swizzle(monkeypatch, GOOD)
    assert swizzle.swizzle_contract_holds(swizzle_root=Path("/x")) == (True, "SWIZZLE contract 1 confirmed.")
    assert seen[0][-3:] == ["-m", "swizzle.cli", "--contract"]


def test_a_matching_swizzle_runs_the_proofs_as_before(monkeypatch):
    seen = _swizzle(monkeypatch, GOOD)
    assert swizzle.swizzle_proofs_hold(swizzle_root=Path("/x")) == (True, "SWIZZLE proofs: 12 of 12 proofs hold.")
    assert [c[-1] for c in seen] == ["--contract", "prove"]


def test_an_older_swizzle_with_no_contract_flag_is_not_confirmed(monkeypatch):
    seen = _swizzle(monkeypatch, "", contract_code=2, contract_err="error: unrecognized arguments: --contract")
    holds, why = swizzle.swizzle_proofs_hold(swizzle_root=Path("/x"))
    assert holds is False and "contract not confirmed" in why and "older than 0.8.0" in why
    assert all("prove" not in c for c in seen)


@pytest.mark.parametrize("answer", [
    {**GOOD, "contract": 2},
    {**GOOD, "contract": 0},
    {**GOOD, "contract": "1"},
    {**GOOD, "contract": True},
    {**GOOD, "contract": 1.0},
    {**GOOD, "name": "not-swizzle"},
    {"contract": 1},
    {"name": "swizzle"},
    [GOOD],
    "not json at all",
    "",
])
def test_a_different_or_unreadable_contract_is_not_confirmed(monkeypatch, answer):
    seen = _swizzle(monkeypatch, answer)
    holds, why = swizzle.swizzle_proofs_hold(swizzle_root=Path("/x"))
    assert holds is False and "SWIZZLE contract" in why
    assert all("prove" not in c for c in seen)


def test_a_different_contract_number_is_named_in_the_reason(monkeypatch):
    _swizzle(monkeypatch, {**GOOD, "contract": 2})
    assert swizzle.swizzle_contract_holds(swizzle_root=Path("/x")) == (
        False, "SWIZZLE contract 2 is not supported: Warden reads contract 1")


@pytest.mark.parametrize("exc", [OSError("no python"), subprocess.TimeoutExpired("x", 1)])
def test_a_contract_check_that_cannot_run_is_not_confirmed(monkeypatch, exc):
    def boom(*a, **kw):
        raise exc
    monkeypatch.setattr(swizzle, "run_instrument", boom)
    holds, why = swizzle.swizzle_contract_holds(swizzle_root=Path("/x"))
    assert holds is False and "could not run" in why


# --- the run: an unconfirmed SWIZZLE never backs an ACCEPT -------------------------------------------

def _tree(root: Path) -> Path:
    root.mkdir()
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text(
        "from pkg import VALUE\n\ndef test_a():\n    assert VALUE == 1\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    commit_all(root)
    return root


def _run(tmp_path, monkeypatch, contract):
    target = _tree(tmp_path / "t")
    _swizzle(monkeypatch, contract, contract_code=0 if contract is not None else 2)
    graded = []
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: graded.append(1) or (True, {"caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), ghost_tools_root=tmp_path, swizzle_root=tmp_path,
                   assay_root=tmp_path)
    auth = grant("william", "transform", str(target.resolve()), "documentation", "test")
    return target, team.run(target, findings=[], authorization=auth), graded


@pytest.mark.parametrize("contract", [None, {**GOOD, "contract": 2}, {**GOOD, "name": "other"}],
                         ids=["absent", "different", "other-tool"])
def test_a_run_against_an_unconfirmed_swizzle_writes_nothing_and_says_why(tmp_path, monkeypatch, contract):
    target, result, graded = _run(tmp_path, monkeypatch, contract)
    assert result.decision == "INCONCLUSIVE" and not result.applied
    assert result.swizzle_sound is False and "swizzle" in result.unmeasured
    assert "SWIZZLE contract" in result.reason and "nothing was written" in result.reason
    assert any("SWIZZLE contract" in n for n in result.notes)
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "old\n"
    assert graded == []          # ASSAY grading runs through SWIZZLE, so it is not run either


def test_a_run_against_a_matching_swizzle_is_unchanged(tmp_path, monkeypatch):
    target, result, graded = _run(tmp_path, monkeypatch, GOOD)
    assert result.swizzle_sound is True and "swizzle" not in result.unmeasured
    # Everything SWIZZLE-side was measured; only the unseated Judge keeps this from a plain ACCEPT.
    assert result.decision == "ACCEPT_UNVERIFIED" and result.unmeasured == ("judge",) and graded == [1]
    assert not any("contract" in n for n in result.notes)       # a matching SWIZZLE adds nothing to the record
