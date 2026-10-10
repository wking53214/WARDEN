"""Round 3, part two: the lock and journal live where TMPDIR cannot lose them, an interrupted keep test is
only undone for a human grant and never over the user's own edit, Ghost and ASSAY are read without being
trusted, and the accounting says what really happened."""

import json
import subprocess
from pathlib import Path

import pytest

import warden.ghost as ghost
import warden.swizzle as swizzle
import warden.tagteam as tagteam
from warden import guard, runstate
from warden.authorization import Unauthorized, canonical, grant, is_stack_actor
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeFinisher, FakeJudge
from gitutil import commit_all, git


def _repo(root: Path) -> Path:
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pkg" / "dead.py").write_text("def unused():\n    return 1\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_pkg.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                                  encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _auth(root: Path, scope="documentation"):
    return grant("william", "transform", str(root.resolve()), scope, "round 3 test")


# -- D. where the lock and journal live ---------------------------------------------------------------

def test_the_journal_and_lock_do_not_move_when_tmpdir_changes(tmp_path, monkeypatch):
    target = tmp_path / "t"
    target.mkdir()
    one, two = tmp_path / "tmp_one", tmp_path / "tmp_two"
    one.mkdir()
    two.mkdir()
    monkeypatch.setenv("TMPDIR", str(one))
    runstate._cache.clear()
    first = (runstate.journal_path(target), runstate.lock_path(target))
    monkeypatch.setenv("TMPDIR", str(two))
    runstate._cache.clear()
    assert (runstate.journal_path(target), runstate.lock_path(target)) == first
    assert not any(str(p).startswith((str(one), str(two))) for p in first)


def test_a_run_started_under_another_tmpdir_still_sees_the_lock(tmp_path, monkeypatch):
    target = tmp_path / "t"
    target.mkdir()
    one, two = tmp_path / "tmp_one", tmp_path / "tmp_two"
    one.mkdir()
    two.mkdir()
    monkeypatch.setenv("TMPDIR", str(one))
    runstate._cache.clear()
    held = runstate.TargetLock(target)
    assert held.acquire()
    try:
        monkeypatch.setenv("TMPDIR", str(two))
        runstate._cache.clear()
        assert runstate.TargetLock(target).acquire() is False
    finally:
        held.release()


def test_in_a_git_repository_the_state_lives_inside_the_git_folder(tmp_path):
    _repo(tmp_path)
    commit_all(tmp_path)
    assert (tmp_path / ".git").resolve() in runstate.journal_path(tmp_path).resolve().parents
    assert git(tmp_path, "status", "--porcelain") == ""  # and it does not show up as work


def test_a_symlink_planted_at_the_lock_name_is_refused_and_nothing_is_overwritten(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    runstate._cache.clear()
    (runstate.state_dir(target) / "lock").symlink_to(victim)
    with pytest.raises(runstate.StateUnavailable):
        runstate.TargetLock(target).acquire()
    assert victim.read_text(encoding="utf-8") == "precious"
    result = TagTeam(drafter=None).run(target, findings=[])
    assert result.decision == "INCONCLUSIVE" and victim.read_text(encoding="utf-8") == "precious"


def test_a_symlink_planted_at_the_journal_name_is_replaced_not_followed(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("precious", encoding="utf-8")
    runstate._cache.clear()
    journal = runstate.journal_path(target)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.unlink(missing_ok=True)
    journal.symlink_to(victim)
    runstate.write_journal(target, {"a.py": b"x"}, {"a.py": b"y"})
    assert victim.read_text(encoding="utf-8") == "precious"
    assert not journal.is_symlink()
    runstate.clear_journal(target)


def test_a_state_folder_that_is_a_symlink_is_refused(tmp_path, monkeypatch):
    target = tmp_path / "t"
    target.mkdir()
    runstate._cache.clear()
    leaf = runstate.state_dir(target)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    leaf_parent, name = leaf.parent, leaf.name
    leaf.rmdir()
    (leaf_parent / name).symlink_to(elsewhere)
    runstate._cache.clear()
    try:
        with pytest.raises(runstate.StateUnavailable):
            runstate.state_dir(target)
    finally:
        (leaf_parent / name).unlink()


TRAP = b"raise RuntimeError('warden keep-test: trap')\n"
ORIGINAL = b"def unused():\n    return 1\n"


def _interrupted(root: Path) -> None:
    runstate.write_journal(root, {"pkg/dead.py": ORIGINAL}, {"pkg/dead.py": TRAP})
    (root / "pkg" / "dead.py").write_bytes(TRAP)


def test_a_run_with_no_authorization_never_touches_the_tree_for_recovery(tmp_path):
    _repo(tmp_path)
    _interrupted(tmp_path)
    result = TagTeam(drafter=FakeDrafter()).run(tmp_path, findings=[])
    assert (tmp_path / "pkg" / "dead.py").read_bytes() == TRAP
    assert runstate.has_journal(tmp_path) and runstate.PENDING_NOTE in result.notes
    runstate.clear_journal(tmp_path)


def test_a_file_the_user_changed_since_the_trap_is_not_overwritten(tmp_path):
    _repo(tmp_path)
    _interrupted(tmp_path)
    (tmp_path / "pkg" / "dead.py").write_text("def unused():\n    return 'my own edit'\n", encoding="utf-8")
    result = TagTeam(drafter=None).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert "my own edit" in (tmp_path / "pkg" / "dead.py").read_text(encoding="utf-8")
    assert any("was changed after an interrupted keep test" in n for n in result.notes)
    assert runstate.INTERRUPTED_NOTE not in result.notes


def test_a_file_that_still_holds_the_trap_is_restored_for_a_human_grant(tmp_path):
    _repo(tmp_path)
    _interrupted(tmp_path)
    result = TagTeam(drafter=None).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert (tmp_path / "pkg" / "dead.py").read_bytes() == ORIGINAL
    assert runstate.INTERRUPTED_NOTE in result.notes and not runstate.has_journal(tmp_path)


def test_the_start_snapshot_is_taken_after_recovery_so_the_trap_is_never_put_back(tmp_path):
    _repo(tmp_path)
    _interrupted(tmp_path)
    result = TagTeam(drafter=FakeDrafter(), judge=FakeJudge("REJECT")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "JUDGE_REJECTED"
    assert (tmp_path / "pkg" / "dead.py").read_bytes() == ORIGINAL


# -- A. a stray git lock at the start ------------------------------------------------------------------

def test_a_git_index_lock_present_at_the_start_refuses_the_run(tmp_path):
    _repo(tmp_path)
    commit_all(tmp_path)
    (tmp_path / ".git" / "index.lock").write_text("", encoding="utf-8")
    drafter = FakeDrafter()
    result = TagTeam(drafter=drafter).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REFUSED" and drafter.calls == 0 and "index.lock" in result.reason


def test_a_dirty_repository_is_refused_before_any_seat_runs(tmp_path):
    _repo(tmp_path)
    commit_all(tmp_path)
    (tmp_path / "mine.txt").write_text("x", encoding="utf-8")
    drafter = FakeDrafter()
    result = TagTeam(drafter=drafter).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REFUSED" and drafter.calls == 0
    assert "commit or stash" in result.reason.lower() and not result.cycles


# -- E/H. honest accounting -----------------------------------------------------------------------------

def test_a_judge_that_raises_is_an_error_and_the_changes_do_not_stand(tmp_path):
    _repo(tmp_path)

    class Boom:
        def decide(self, evidence):
            raise RuntimeError("no")

    result = TagTeam(drafter=FakeDrafter(), judge=Boom()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ERROR" and result.put_back
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_an_unknown_judge_label_is_an_error_not_a_pass(tmp_path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter(), judge=FakeJudge("MAYBE")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ERROR" and "MAYBE" in result.reason and result.put_back
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_put_back_is_true_after_a_judge_reject_and_the_note_says_so(tmp_path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter(), judge=FakeJudge("REJECT")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "JUDGE_REJECTED" and result.put_back is True
    assert tagteam.PUT_BACK_NOTE in result.notes
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_a_rejected_finish_says_the_loop_result_was_restored_too(tmp_path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter(), finisher=FakeFinisher(path="tests/test_pkg.py", new_text="x = 1\n")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "code"))
    assert result.decision == "FINISH_REJECTED" and result.put_back
    assert "stands" not in result.reason
    assert tagteam.LOOP_PUT_BACK_NOTE in result.notes
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_a_run_that_changed_nothing_lists_the_suite_as_unmeasured(tmp_path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter(steps=[])).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.converged and "suite" in result.unmeasured


def test_a_judged_run_that_changed_nothing_is_not_downgraded_for_the_suite_the_judge_ran(tmp_path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter(steps=[]), judge=FakeJudge("ACCEPT")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert "suite" not in result.unmeasured


def test_declined_proposals_do_not_use_up_cycles(tmp_path):
    _repo(tmp_path)
    from fakes import _transformation

    class Mixed:
        n = 0

        def propose(self, target, observed, baseline):
            self.n += 1
            if self.n <= 2:   # out of scope for a documentation grant, naming no defect
                return _transformation(target, observed, baseline, "pkg/__init__.py", f"VALUE = {self.n + 1}\n")
            if self.n == 3:
                return _transformation(target, observed, baseline, "NOTE.md", "new\n")
            return None

    result = TagTeam(drafter=Mixed(), max_cycles=1).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.converged is False and result.decision == "NOT_CONVERGED"  # one real attempt used the one cycle
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"  # put back: not accepted
    applied = [c for c in result.cycles if c.applied]
    assert len(applied) == 1 and [c.outcome for c in result.cycles].count("DECLINED") == 2


def test_the_number_of_declined_proposals_is_capped(tmp_path):
    _repo(tmp_path)
    from fakes import _transformation

    class Endless:
        n = 0

        def propose(self, target, observed, baseline):
            self.n += 1
            return _transformation(target, observed, baseline, "pkg/__init__.py", f"VALUE = {self.n + 1}\n")

    drafter = Endless()
    result = TagTeam(drafter=drafter, max_cycles=2, max_declined=4).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "NOT_CONVERGED" and drafter.n == 4


def test_empty_folders_made_by_an_apply_are_removed_on_put_back(tmp_path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter(path="newdocs/deep/page.md"), judge=FakeJudge("REJECT")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.put_back and not (tmp_path / "newdocs").exists()


def test_a_tree_too_big_to_restore_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(guard, "_RESTORE_LIMIT", 10)
    drafter = FakeDrafter()
    result = TagTeam(drafter=drafter).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "INCONCLUSIVE" and drafter.calls == 0
    assert "put back" in result.reason and (tmp_path / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_proofs_failing_after_the_loop_report_swizzle_unsound(tmp_path, monkeypatch):
    _repo(tmp_path)
    answers = iter([True, False, False, False])
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: next(answers))
    result = TagTeam(drafter=FakeDrafter(), swizzle_root=tmp_path).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "INCONCLUSIVE" and result.swizzle_sound is False


def test_assay_floor_zero_is_said_out_loud(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 0}, "ok"))
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    result = TagTeam(drafter=FakeDrafter(steps=[]), swizzle_root=tmp_path, assay_root=tmp_path, assay_floor=0).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert any("NOT ENFORCED" in n for n in result.notes)


def test_a_seat_that_runs_past_the_seat_timeout_ends_the_run_as_error(tmp_path):
    _repo(tmp_path)
    import time

    class Slow:
        def propose(self, target, observed, baseline):
            time.sleep(30)

    started = time.time()
    result = TagTeam(drafter=Slow(), seat_timeout=1).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ERROR" and "did not answer within 1" in result.reason and time.time() - started < 20


# -- authorize names ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Drafter", "DRAFTER", "drafter-2", "Burnish", "ghost_tools", "Ghost", "SWIZZLE", "Assay",
                                  "JUDGE", "Warden", "The  Warden", "Dr​after", "G‍host", "Ｄrafter",
                                  "D r a f t e r", "Drаfter", "Jᴜdge", "self", "UNKNOWN", "​", "  "])
def test_reserved_and_lookalike_actor_names_cannot_authorize(name):
    with pytest.raises(Unauthorized):
        grant(name, "transform", "/x", "documentation", "because")


@pytest.mark.parametrize("name", ["william", "William N. King", "alice", "wking53214", "Selfridge", "Judy"])
def test_ordinary_names_can(name):
    assert grant(name, "transform", "/x", "documentation", "because").granted


def test_canonical_folds_the_tricks():
    assert canonical("Dr​аfter") == canonical("DRAFTER") == "drafter" and is_stack_actor("D R A F T E R")


# -- F. Ghost output is read without trust -----------------------------------------------------------------

def _fake_ghost(monkeypatch, payload, code=0, stderr=""):
    def fake(cmd, **kw):
        return subprocess.CompletedProcess(cmd, code, stdout=json.dumps(payload), stderr=stderr)
    monkeypatch.setattr(ghost, "run_instrument", fake)


FULL = {"status": "ok", "scan": {"files_scanned": 3, "files_skipped": 0, "files_unparsable": 0}, "unmeasured": [],
        "findings": []}


def test_a_complete_ghost_object_has_no_gap(tmp_path, monkeypatch):
    _fake_ghost(monkeypatch, {**FULL, "findings": [{"id": "g1"}]}, code=1)
    out = ghost.scan(tmp_path, ghost_tools_root=tmp_path)
    assert out.gaps == () and out.version_unverified is False


@pytest.mark.parametrize("missing", ["status", "scan", "unmeasured"])
def test_ghost_output_missing_a_field_is_a_gap(tmp_path, monkeypatch, missing):
    payload = {k: v for k, v in {**FULL, "findings": [{"id": "g1"}]}.items() if k != missing}
    _fake_ghost(monkeypatch, payload, code=1)
    out = ghost.scan(tmp_path, ghost_tools_root=tmp_path)
    assert out.gaps and missing in out.gaps[0]


def test_suppressed_findings_are_a_gap(tmp_path, monkeypatch):
    _fake_ghost(monkeypatch, {**FULL, "baseline": {"path": ".ghost_baseline.json", "suppressed": 3}})
    out = ghost.scan(tmp_path, ghost_tools_root=tmp_path)
    assert any("3 finding(s)" in g for g in out.gaps) and out.baseline == {"path": ".ghost_baseline.json", "suppressed": 3}


def test_a_baseline_with_nothing_suppressed_or_no_baseline_at_all_is_fine(tmp_path, monkeypatch):
    _fake_ghost(monkeypatch, {**FULL, "baseline": {"path": None, "suppressed": 0}})
    assert ghost.scan(tmp_path, ghost_tools_root=tmp_path).gaps == ()
    _fake_ghost(monkeypatch, FULL)
    assert ghost.scan(tmp_path, ghost_tools_root=tmp_path).gaps == ()


@pytest.mark.parametrize("bad", ["many", -1, True, [1]])
def test_an_unreadable_suppressed_count_is_a_gap_not_a_crash(tmp_path, monkeypatch, bad):
    _fake_ghost(monkeypatch, {**FULL, "baseline": {"path": None, "suppressed": bad}})
    assert ghost.scan(tmp_path, ghost_tools_root=tmp_path).gaps


def test_exit_1_with_no_findings_is_a_gap(tmp_path, monkeypatch):
    _fake_ghost(monkeypatch, FULL, code=1)
    out = ghost.scan(tmp_path, ghost_tools_root=tmp_path)
    assert any("exited 1" in g for g in out.gaps)
    _fake_ghost(monkeypatch, [], code=1)
    assert any("exited 1" in g for g in ghost.scan(tmp_path, ghost_tools_root=tmp_path).gaps)


def test_gaps_make_the_run_ghost_partial_and_old_ghost_is_noted_as_unverified(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    _fake_ghost(monkeypatch, {**FULL, "baseline": {"path": "b", "suppressed": 2}})
    result = TagTeam(drafter=FakeDrafter(steps=[]), ghost_tools_root=tmp_path).run(
        tmp_path, authorization=_auth(tmp_path))
    assert "ghost_partial" in result.unmeasured and result.ghost_scan["baseline"]["suppressed"] == 2
    _fake_ghost(monkeypatch, [])
    result = TagTeam(drafter=FakeDrafter(steps=[]), ghost_tools_root=tmp_path).run(
        tmp_path, authorization=_auth(tmp_path))
    assert "ghost_version_unverified" in result.informational
    assert "ghost_partial" not in result.unmeasured and "ghost" not in result.unmeasured


# -- I. the ASSAY key proof ----------------------------------------------------------------------------------

def _card(proof, outcomes=()):
    return json.dumps({"assay": "a", "proof": proof, "key_proven": not proof.startswith("NOT PROVEN"),
                       "judgements": [{"specimen_id": f"s{i}", "specimen_class": "FAILURE_MODE", "outcome": o}
                                      for i, o in enumerate(outcomes)]})


def _fake_instrument(monkeypatch, answers):
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        code, out, err = answers[min(len(calls) - 1, len(answers) - 1)]
        return subprocess.CompletedProcess(cmd, code, stdout=out, stderr=err)
    monkeypatch.setattr(swizzle, "run_instrument", fake)
    return calls


BAD_TRANSIENT = (2, _card("NOT PROVEN: verify_manifest.py could not run: timed out", ["UNSUMMONED"]),
                 "swizzle: cannot score 29 specimen(s): a, b")
GOOD = (0, _card("29/29 claims hold", ["banished", "escaped"]), "")


def test_a_transient_key_proof_failure_is_retried_once_and_the_pass_is_reported(tmp_path, monkeypatch):
    calls = _fake_instrument(monkeypatch, [BAD_TRANSIENT, GOOD])
    state, score, summary = swizzle.assay_score(swizzle_root=tmp_path, assay_root=tmp_path)
    assert state is True and score["caught"] == 1 and len(calls) == 2
    assert "second run" in summary


def test_a_key_proof_that_fails_twice_relays_the_real_reason(tmp_path, monkeypatch):
    calls = _fake_instrument(monkeypatch, [BAD_TRANSIENT])
    state, _, summary = swizzle.assay_score(swizzle_root=tmp_path, assay_root=tmp_path)
    assert state is False and len(calls) == 2
    assert "could not run: timed out" in summary and "cannot score 29" in summary and "run twice" in summary


def test_a_key_that_really_fails_is_not_retried(tmp_path, monkeypatch):
    calls = _fake_instrument(monkeypatch, [(2, _card("NOT PROVEN: 28/29 claims hold", ["UNSUMMONED"]), "swizzle: cannot score 1")])
    state, _, summary = swizzle.assay_score(swizzle_root=tmp_path, assay_root=tmp_path)
    assert state is False and len(calls) == 1 and "28/29 claims hold" in summary


# -- A. `warden audit` follows the dirty-folder rule only when it writes ------------------------------------

def test_audit_writes_only_into_a_clean_folder_and_may_rewrite_its_own_file(tmp_path, capsys):
    from warden.cli import main
    target = tmp_path / "t"
    target.mkdir()
    _repo(target)
    commit_all(target)
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")
    args = ["audit", str(target), "--from-ghost", str(findings)]
    write = args + ["--authorize", "william", "--reason", "audit test"]

    (target / "mine.txt").write_text("my work", encoding="utf-8")
    assert main(args) == 0  # printing is read-only, so a dirty folder does not matter
    assert main(write) == 2 and not (target / "WARDEN_AUDIT.md").exists()
    assert "uncommitted" in capsys.readouterr().err

    (target / "mine.txt").unlink()
    assert main(write) == 0 and (target / "WARDEN_AUDIT.md").exists()
    assert main(write) == 0  # its own file being new or modified does not count as other work
