"""The horsemen interface used end to end: real adapters, a real workflow, and Warden's own command line.

These tests walk handoffs from a finished governed run through `AssayAdapter`, `GhostToolsAdapter` and
`SwizzleAdapter` into a production receipt, and drive the same path through `warden tagteam --receipt`.
"""

import json
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import Unauthorized, grant
from warden.cli import main
from warden.horsemen import (EpistemicLabel, GhostToolsAdapter, HandoffKind, SwizzleAdapter,
                             SwizzleVerdict, receipt_for_run)
from warden.horsemen.workflow import WorkflowPhase
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge
from gitutil import commit_all, git
from test_assay_link import GOOD, _corpus
from test_honest_exit_codes import SEATS, _repo


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: (
        {"scenario": "forged grant", "severity": "high", "status": "held"},
        {"scenario": "silent pass", "severity": "low", "status": "violated"}))


def _run(target: Path, **kw):
    auth = grant("william", "transform", str(target.resolve()), "documentation", "receipt test")
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=FakeJudge("ACCEPT", ("fine",)),
                   ghost_tools_root=Path("."), swizzle_root=Path("."), assay_root=Path("."), **kw)
    return team.run(target, findings=[], authorization=auth), auth


def test_a_governed_run_becomes_a_receipt_through_every_adapter(tmp_path, measured):
    target = _repo(tmp_path / "t")
    assay_root = tmp_path / "assay"
    _corpus(assay_root, GOOD)
    result, auth = _run(target)
    receipt = receipt_for_run(result=result, target=target, authorization=auth, baseline_sha="a" * 40,
                              assay_root=assay_root)
    data = receipt.to_dict()
    assert data["final_verdict"] == result.decision == "ACCEPT" or data["final_verdict"] == "APPROVED"
    assert data["specimens_used"] == ["a"]                      # AssayAdapter read the answer key
    assert data["adversarial_cases"] == ["swizzle.proofs", "forged grant", "silent pass"]
    assert data["files_changed"] == ["NOTE.md"]
    assert data["actor"] == "william" and data["authority_source"] == "human_operator"
    assert data["before_revision"] == "a" * 40 and data["after_revision"] == "a" * 40 + "+uncommitted"
    assert data["cns_readiness"] == "UNKNOWN"                    # Warden never claims CNS readiness


def test_the_receipt_records_what_the_handoffs_carried(tmp_path, measured, monkeypatch):
    from warden.horsemen import circuit

    seen = {}
    real = circuit.HorsemenWorkflow

    class Spy(real):
        def finalize(self, workflow_id, **kw):
            seen["state"] = self.states[workflow_id]
            return super().finalize(workflow_id, **kw)

    monkeypatch.setattr(circuit, "HorsemenWorkflow", Spy)
    target = _repo(tmp_path / "t")
    assay_root = tmp_path / "assay"
    _corpus(assay_root, GOOD)
    result, auth = _run(target)
    receipt_for_run(result=result, target=target, authorization=auth, baseline_sha="b" * 40,
                    assay_root=assay_root)
    state = seen["state"]
    phases = [p.phase for p in state.phases]
    assert phases == [WorkflowPhase.FREEZE_BASELINE, WorkflowPhase.ASSAY, WorkflowPhase.GHOST_INSPECT,
                      WorkflowPhase.SWIZZLE_ADVERSARIAL, WorkflowPhase.PROPOSE, WorkflowPhase.HUMAN_AUTHORIZE,
                      WorkflowPhase.TRANSFORM, WorkflowPhase.GHOST_REINSPECT, WorkflowPhase.RECEIPT]
    kinds = [h.kind for h in state.handoffs]
    assert kinds == [HandoffKind.SPECIMEN, HandoffKind.FINDING, HandoffKind.VERDICT, HandoffKind.PROPOSAL,
                     HandoffKind.AUTHORIZATION, HandoffKind.TRANSFORMATION, HandoffKind.FINDING]
    adversarial = next(h for h in state.handoffs if h.kind == HandoffKind.VERDICT)
    assert adversarial.result == "FAILED" and adversarial.payload["failed_count"] == 1   # the violated attack
    assert adversarial.epistemic_state == EpistemicLabel.CONFIRMED
    assert all(h.repository_sha == "b" * 40 for h in state.handoffs)


def test_an_unreadable_answer_key_is_unknown_in_the_receipt_never_no_specimens(tmp_path, measured):
    target = _repo(tmp_path / "t")
    result, auth = _run(target)
    missing = tmp_path / "no-assay"
    missing.mkdir()
    receipt = receipt_for_run(result=result, target=target, authorization=auth, baseline_sha="c" * 40,
                              assay_root=missing)
    assert receipt.specimens_used == []
    assert any("answer key could not be read" in u for u in receipt.unknowns)
    none_given = receipt_for_run(result=result, target=target, authorization=auth, baseline_sha="c" * 40)
    assert any("no ASSAY root" in u for u in none_given.unknowns)


def test_a_held_run_is_recorded_as_held_with_what_was_unmeasured(tmp_path, monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    target = _repo(tmp_path / "t")
    auth = grant("william", "transform", str(target.resolve()), "code", "held")
    result = TagTeam(drafter=FakeDrafter(steps=("new\n",)), ghost_tools_root=Path(".")).run(
        target, findings=[], authorization=auth)
    assert result.decision == "ACCEPT_UNVERIFIED"
    receipt = receipt_for_run(result=result, target=target, authorization=auth, baseline_sha="d" * 40)
    assert receipt.final_verdict == "ACCEPT_UNVERIFIED"
    assert receipt.after_revision == "d" * 40                    # put back: nothing stands
    assert any("put back" in u for u in receipt.unknowns)
    assert any("swizzle was not measured" in u for u in receipt.unknowns)


def test_no_receipt_without_a_human_grant(tmp_path, measured):
    target = _repo(tmp_path / "t")
    result, _ = _run(target)
    with pytest.raises(Unauthorized):
        receipt_for_run(result=result, target=target, authorization=None, baseline_sha="e" * 40)


# -- the adapters' own fail-closed rules -------------------------------------------------------------

def test_a_swizzle_result_warden_does_not_know_is_not_a_pass():
    adapter = SwizzleAdapter()
    kw = dict(repository="r", repository_sha="0" * 40, baseline_id="b")
    odd = adapter.handoff_verdicts([SwizzleVerdict("a", "PASSED"), SwizzleVerdict("b", "NOT_RUN")], **kw)
    assert odd.result == "INCONCLUSIVE" and odd.epistemic_state == EpistemicLabel.UNKNOWN
    assert adapter.adversarial_passed(odd) is False
    good = adapter.handoff_verdicts([SwizzleVerdict("a", "PASSED"), SwizzleVerdict("b", "held")], **kw)
    assert good.result == "PASSED" and adapter.adversarial_passed(good) is True
    bad = adapter.handoff_verdicts([SwizzleVerdict("a", "violated")], **kw)
    assert bad.result == "FAILED"


def test_ghost_findings_become_a_handoff_and_an_empty_scan_is_unknown(tmp_path):
    path = tmp_path / "f.json"
    path.write_text(json.dumps({"findings": [{"id": "ghost-1", "summary": "dead", "severity": "low",
                                              "path": "a.py"}]}), encoding="utf-8")
    adapter = GhostToolsAdapter()
    found = adapter.load_findings_json(path)
    hof = adapter.handoff_findings(found, repository="r", repository_sha="0" * 40, baseline_id="b")
    assert hof.result == "OBSERVED" and hof.payload["findings"][0]["finding_id"] == "ghost-1"
    empty = adapter.handoff_findings([], repository="r", repository_sha="0" * 40, baseline_id="b")
    assert empty.result == "NO_FINDINGS_UNKNOWN" and empty.epistemic_state == EpistemicLabel.UNKNOWN


def test_the_dead_shared_contracts_stub_is_gone():
    import warden.horsemen as horsemen
    import warden.horsemen.contracts as contracts
    assert not hasattr(contracts, "try_import_shared_contracts")
    assert "try_import_shared_contracts" not in horsemen.__all__
    assert "horsemen_contracts" not in Path(contracts.__file__).read_text(encoding="utf-8")


# -- the command line -------------------------------------------------------------------------------

@pytest.fixture
def cli(tmp_path, monkeypatch, capsys, measured):
    target = _repo(tmp_path / "t")
    commit_all(target)
    seats = tmp_path / "seats"
    seats.mkdir()
    (seats / "exit_seats.py").write_text(SEATS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(seats))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    (tmp_path / "ghost").mkdir()
    (tmp_path / "swizzle").mkdir()
    (tmp_path / "assay").mkdir()
    _corpus(tmp_path / "assay", GOOD)
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")

    def run(*extra):
        args = ["tagteam", str(target), "--from-ghost", str(findings), "--drafter", "exit_seats:Once",
                "--judge", "exit_seats:Judge", "--ghost-root", str(tmp_path / "ghost"),
                "--swizzle-root", str(tmp_path / "swizzle"), "--assay-root", str(tmp_path / "assay"),
                "--assay-floor", "3", "--authorize", "william", "--reason", "cli receipt", *extra]
        code = main(args)
        out = capsys.readouterr()
        return code, json.loads(out.out), out.err

    run.target, run.tmp = target, tmp_path
    return run


def test_the_command_line_writes_a_receipt_and_the_json_contract_is_unchanged(cli):
    out = cli.tmp / "receipt.json"
    code, payload, err = cli("--receipt", str(out))
    assert code == 0 and payload["decision"] == "ACCEPT"
    receipt = json.loads(out.read_text(encoding="utf-8"))
    assert receipt["final_verdict"] == "APPROVED" and receipt["files_changed"] == ["NOTE.md"]
    assert receipt["specimens_used"] == ["a"]
    assert receipt["before_revision"] == git(cli.target, "rev-parse", "HEAD")
    assert "receipt" not in payload          # stdout stays the cns.run/1 record
    assert "receipt written" in err


def test_a_receipt_inside_the_target_is_refused_before_anything_runs(cli):
    code, payload, _ = cli("--receipt", str(cli.target / "receipt.json"))
    assert code == 2 and payload["decision"] == "USAGE_ERROR" and "inside the target" in payload["reason"]
    assert (cli.target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_a_receipt_that_cannot_be_written_is_said_and_never_changes_the_exit_code(cli):
    code, payload, err = cli("--receipt", str(cli.tmp / "missing-folder" / "receipt.json"))
    assert code == 0 and payload["decision"] == "ACCEPT"
    assert "the receipt was not written" in err
