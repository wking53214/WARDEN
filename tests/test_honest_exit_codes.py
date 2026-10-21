"""Honest exit codes, honest "not measured", strict readers, and the version handshake.

Each test reproduces a finding from the second red team: a run that could not measure
something, or wrote nothing, used to exit 0 and read as success to CI, or an instrument's
odd output was believed. Each now fails closed.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import warden
import warden.cli as cli
import warden.ghost as ghost
import warden.swizzle as swizzle
import warden.tagteam as tagteam
from warden.authorization import grant
from warden.cli import EXIT_CODES, main
from warden.tagteam import TagTeam

from fakes import FakeDrafter
from gitutil import as_checkout

SEATS = '''
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.roles import Verdict


def _t(target, observed, baseline, path, new, cites=()):
    note = Path(target) / path
    old = note.read_text(encoding="utf-8") if note.is_file() else ""
    return Transformation(
        target=str(Path(target).resolve()), intent="test change", architectural_reason="test",
        affected_files=(path,), expected_behavior="none", preservation_requirements=(),
        known_defects=tuple(cites), transformation_scope="documentation", baseline_reference=baseline,
        evidence=(), edits=(FileEdit(path=path, kind="write", new=new, old=old),),
        status=TransformationStatus.PROPOSED)


class Once:
    requires_contract = "1"
    path, text = "NOTE.md", "changed\\n"
    def __init__(self): self.done = False
    def propose(self, target, observed, baseline):
        if self.done: return None
        self.done = True
        return _t(target, observed, baseline, self.path, self.text)


class Breaker(Once):
    path, text = "pkg/__init__.py", "VALUE = 2\\n"


class Forever:
    requires_contract = "1"
    n = 0
    def propose(self, target, observed, baseline):
        Forever.n += 1
        return _t(target, observed, baseline, "NOTE.md", f"v{Forever.n}\\n")


class Crasher:
    requires_contract = "1"
    def propose(self, target, observed, baseline): raise RuntimeError("boom")


class Nothing:
    requires_contract = "1"
    def propose(self, target, observed, baseline): return None


class NoOp:
    """Proposes to write the file exactly as it already is."""
    requires_contract = "1"
    calls = 0
    def propose(self, target, observed, baseline):
        NoOp.calls += 1
        text = (Path(target) / "NOTE.md").read_text(encoding="utf-8")
        return _t(target, observed, baseline, "NOTE.md", text)


class CodeFile:
    """Out of a documentation grant's scope, citing no defect; then runs dry."""
    requires_contract = "1"
    def __init__(self): self.n = 0
    def propose(self, target, observed, baseline):
        self.n += 1
        if self.n > 1: return None
        return _t(target, observed, baseline, "pkg/__init__.py", "VALUE = 1  # tidy\\n")


class CodeFileAlways:
    requires_contract = "1"
    def propose(self, target, observed, baseline):
        return _t(target, observed, baseline, "pkg/__init__.py", "VALUE = 1  # tidy\\n")


class ScopeAndTest:
    """An out-of-scope edit alongside an edit to a test file."""
    requires_contract = "1"
    def propose(self, target, observed, baseline):
        p = _t(target, observed, baseline, "pkg/__init__.py", "VALUE = 1  # tidy\\n")
        q = _t(target, observed, baseline, "tests/test_x.py", "def test_v():\\n    assert True\\n")
        p.edits = p.edits + q.edits
        return p


class Judge:
    requires_contract = "1"
    decision = "ACCEPT"
    def decide(self, evidence): return Verdict(self.decision, ("ok",), "judge")


class RejectingJudge(Judge):
    decision = "REJECT"


class OddJudge:
    """A verdict with no judge name and an extra field."""
    requires_contract = "1"
    def decide(self, evidence):
        v = Verdict("ACCEPT", ("ok",))
        object.__setattr__(v, "extra", 1)
        return v


class Finisher:
    requires_contract = "1"
    def finish(self, target, baseline, facts):
        return _t(target, (), baseline, "pkg/__init__.py", "VALUE = 2\\n")


class Old:
    requires_contract = "0"
    def propose(self, target, observed, baseline): return None


class Current:
    requires_contract = "1"
    def propose(self, target, observed, baseline): return None


class Unversioned:
    def propose(self, target, observed, baseline): return None
'''


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                                encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


@pytest.fixture
def rig(tmp_path, monkeypatch, capsys):
    """A target, the seats module on the path, and every instrument reporting 'fine'."""
    target = _repo(tmp_path / "t")
    seats = tmp_path / "seats"
    seats.mkdir()
    (seats / "exit_seats.py").write_text(SEATS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(seats))
    sys.modules.pop("exit_seats", None)
    (tmp_path / "ghost").mkdir()
    (tmp_path / "swizzle").mkdir()
    (tmp_path / "assay").mkdir()
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))

    class Rig:
        pass

    r = Rig()
    r.target, r.tmp = target, tmp_path

    def run(*extra, drafter="exit_seats:Once", judge="exit_seats:Judge", finisher=None, measured=True,
            authorize=True, scope="documentation", path=None):
        args = ["tagteam", str(path or target), "--from-ghost", str(_findings(tmp_path))]
        if drafter:
            args += ["--drafter", drafter]
        if judge:
            args += ["--judge", judge]
        if finisher:
            args += ["--finisher", finisher]
        if measured:
            args += ["--ghost-root", str(tmp_path / "ghost"), "--swizzle-root", str(tmp_path / "swizzle"),
                     "--assay-root", str(tmp_path / "assay")]
        if authorize:
            args += ["--authorize", "william", "--reason", "exit code test", "--scope", scope]
        code = main(args + list(extra))
        out = capsys.readouterr()
        return code, json.loads(out.out), out.err

    r.run = run
    return r


def _findings(tmp_path: Path) -> Path:
    f = tmp_path / "f.json"
    f.write_text("[]", encoding="utf-8")
    return f


# -- 1. the exit-code contract, one test per row ----------------------------------------------------

def test_0_is_accept_and_only_accept(rig):
    code, payload, _ = rig.run()
    assert (code, payload["decision"], payload["reason"]) == (0, "ACCEPT", "")  # cns.run/1: the reason is text; ACCEPT carries an empty one


@pytest.mark.parametrize("how,decision", [
    ("reject", "REJECT"), ("judge", "JUDGE_REJECTED"), ("circles", "NOT_CONVERGED"), ("finish", "FINISH_REJECTED")])
def test_1_is_every_kind_of_rejection(rig, how, decision):
    if how == "reject":
        code, payload, _ = rig.run(drafter="exit_seats:Breaker", scope="code")
    elif how == "judge":
        code, payload, _ = rig.run(judge="exit_seats:RejectingJudge")
    elif how == "circles":
        code, payload, _ = rig.run("--max-cycles", "2", drafter="exit_seats:Forever")
    else:
        code, payload, _ = rig.run(finisher="exit_seats:Finisher", scope="code")
    assert (code, payload["decision"]) == (1, decision)
    assert payload["reason"]


def test_2_is_a_usage_error_a_seat_that_will_not_load_or_unsound_proofs(rig, monkeypatch):
    code, payload, _ = rig.run(path=rig.tmp / "nope")
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    code, payload, _ = rig.run(drafter="no_such_module:Seat")
    assert code == 2 and payload["decision"] == "SEAT_NOT_LOADED"
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: False)
    code, payload, _ = rig.run()
    assert code == 2 and payload["swizzle_sound"] is False and payload["decision"] != "ACCEPT"
    assert "swizzle" in payload["unmeasured"]


def test_3_is_accept_unverified(rig):
    code, payload, _ = rig.run(judge=None)
    assert (code, payload["decision"]) == (3, "ACCEPT_UNVERIFIED") and payload["reason"]


def test_4_is_error(rig):
    code, payload, _ = rig.run(drafter="exit_seats:Crasher")
    assert (code, payload["decision"]) == (4, "ERROR") and "RuntimeError" in payload["reason"]


def test_5_is_refused_and_writes_nothing(rig):
    code, payload, _ = rig.run(authorize=False)
    assert (code, payload["decision"]) == (5, "REFUSED") and payload["reason"]
    assert (rig.target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_6_is_inconclusive_when_ghost_is_down(rig, monkeypatch):
    def down(target, **kw):
        raise RuntimeError("ghost_buster failed (2): boom")
    monkeypatch.setattr(tagteam, "ghost_scan", down)
    # The findings file avoids the first scan; the re-inspection after the edit is what fails.
    code, payload, _ = rig.run()
    assert (code, payload["decision"]) == (6, "INCONCLUSIVE")
    assert "ghost" in payload["unmeasured"] and "Ghost" in payload["reason"]
    assert (rig.target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_6_is_inconclusive_when_the_suite_is_red_from_the_start(rig):
    (rig.target / "tests" / "test_x.py").write_text("def test_v():\n    assert False\n", encoding="utf-8")
    code, payload, _ = rig.run()
    assert (code, payload["decision"]) == (6, "INCONCLUSIVE") and "suite" in payload["reason"]


def test_6_is_inconclusive_when_the_assay_key_is_unusable(rig, monkeypatch):
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (False, {}, "key unproven"))
    code, payload, _ = rig.run()
    assert (code, payload["decision"]) == (6, "INCONCLUSIVE")
    assert "assay" in payload["unmeasured"] and payload["reason"]


def test_an_unknown_decision_never_exits_zero(rig, monkeypatch):
    real = TagTeam.run

    def odd(self, *a, **kw):
        from dataclasses import replace
        return replace(real(self, *a, **kw), decision="SOMETHING_NEW")
    monkeypatch.setattr(TagTeam, "run", odd)
    code, payload, _ = rig.run()
    assert code != 0 and payload["decision"] == "SOMETHING_NEW"


def test_every_decision_the_code_can_produce_has_an_exit_code():
    source = Path(tagteam.__file__).read_text(encoding="utf-8")
    labels = set(re.findall(r'stop\(\s*"([A-Z_]+)"', source))
    labels |= set(re.findall(r'decision(?:, said)? = "([A-Z_]+)"', source))
    labels |= set(re.findall(r'return "([A-Z_]{5,})", ', source))
    labels |= set(re.findall(r'decision="([A-Z_]+)"', source))
    assert labels and labels <= set(tagteam.DECISIONS)
    assert set(tagteam.DECISIONS) <= set(EXIT_CODES)
    assert EXIT_CODES["ACCEPT"] == 0 and [k for k, v in EXIT_CODES.items() if v == 0] == ["ACCEPT"]


def test_the_help_text_carries_the_table(capsys):
    with pytest.raises(SystemExit):
        main(["tagteam", "--help"])
    text = capsys.readouterr().out
    assert "REFUSED" in text and "INCONCLUSIVE" in text and "only 0 means" in text


def test_audit_exits_2_when_it_cannot_read_findings_or_will_not_write(tmp_path, capsys):
    target = tmp_path / "t"
    target.mkdir()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["audit", str(target), "--from-ghost", str(bad)]) == 2
    assert main(["audit", str(target), "--from-ghost", str(tmp_path / "missing.json")]) == 2
    assert main(["audit", str(tmp_path / "nope"), "--from-ghost", str(bad)]) == 2
    good = tmp_path / "ok.json"
    good.write_text("[]", encoding="utf-8")
    assert main(["audit", str(target), "--from-ghost", str(good), "--authorize", "william"]) == 2  # no reason
    assert not (target / "WARDEN_AUDIT.md").exists()
    capsys.readouterr()


def test_audit_will_not_print_a_clean_report_when_ghost_analysed_nothing(tmp_path, monkeypatch, capsys):
    target = tmp_path / "t"
    target.mkdir()
    blind = ghost.Findings(())
    blind.blind = "Ghost scanned 0 files, so an empty list of findings does not mean the code is clean"
    monkeypatch.setattr(cli, "ghost_scan", lambda *a, **kw: blind)
    assert main(["audit", str(target), "--ghost-root", str(tmp_path)]) == 2


# -- 2. unmeasured is true when an instrument is down -----------------------------------------------

def test_ghost_down_is_listed_as_unmeasured_with_a_reason(tmp_path, monkeypatch):
    _repo(tmp_path / "t")

    def down(target, **kw):
        raise RuntimeError("no such module")
    monkeypatch.setattr(tagteam, "ghost_scan", down)
    result = TagTeam(drafter=FakeDrafter(), ghost_tools_root=tmp_path).run(
        tmp_path / "t", authorization=grant("w", "transform", str((tmp_path / "t").resolve()), "documentation", "r"))
    assert result.decision == "INCONCLUSIVE" and "ghost" in result.unmeasured
    assert "suite" in result.unmeasured  # the run stopped before the suite was ever measured
    assert result.reason and result.reason == result.notes[-1]


def test_a_scan_that_hangs_is_ghost_being_down_not_a_hang(tmp_path, monkeypatch):
    hang = tmp_path / "ghost" / "ghost_buster"
    hang.mkdir(parents=True)
    (hang / "__init__.py").write_text("", encoding="utf-8")
    (hang / "cli.py").write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    as_checkout(tmp_path / "ghost")       # an instrument root has to be a checkout Warden can name
    t = _repo(tmp_path / "t")
    result = TagTeam(drafter=FakeDrafter(), ghost_tools_root=tmp_path / "ghost", ghost_timeout=1).run(
        t, authorization=grant("w", "transform", str(t.resolve()), "documentation", "r"))
    assert result.decision == "INCONCLUSIVE" and "ghost" in result.unmeasured
    assert "did not finish" in result.reason


def test_swizzle_proofs_failing_lists_swizzle_and_gives_a_reason(rig, monkeypatch):
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: False)
    code, payload, _ = rig.run()
    assert "swizzle" in payload["unmeasured"] and "SWIZZLE" in payload["reason"]


def test_every_non_accept_run_has_a_reason_equal_to_its_last_note_text(rig):
    for kw in ({"authorize": False}, {"judge": None}, {"drafter": "exit_seats:Crasher"}):
        _, payload, _ = rig.run(**kw)
        assert payload["reason"] and "\n" not in payload["reason"]
        assert payload["reason"] in payload["notes"][-1] or payload["reason"] in " ".join(payload["notes"])


# -- 3. instruments are read strictly ---------------------------------------------------------------

def _proc(out="", err="", code=0):
    return subprocess.CompletedProcess([], code, stdout=out, stderr=err)


@pytest.mark.parametrize("out,code", [
    ("0 of 0 proofs hold.\n", 0),
    ("1 of 12 proofs hold.\n", 0),
    ("12 of 12 proofs hold.\n", 1),
    ("note: 12 of 12 proofs hold. (not really)\n", 0),
    ("all 12 of 12 proofs hold.\n", 0),
    ("12 of 12 proofs hold.\nFAILED x\n3 of 12 proofs hold.\n", 0),
    ("NOT all proofs hold: 3 failed\n", 0),
    ("", 0),
])
def test_swizzle_prove_is_not_believed_unless_it_is_exactly_n_of_n(monkeypatch, out, code):
    monkeypatch.setattr(swizzle, "run_instrument", lambda *a, **kw: _proc(out, "", code))
    assert swizzle.swizzle_proofs_hold(swizzle_root=Path("/x"), check_contract=False)[0] is False


def test_swizzle_prove_is_believed_when_it_is_exactly_n_of_n(monkeypatch):
    def fake(cmd, **kw):
        if "--contract" in cmd:
            return _proc('{"name": "swizzle", "contract": 1}')
        return _proc("\n12 of 12 proofs hold.\n", "", 0)
    monkeypatch.setattr(swizzle, "run_instrument", fake)
    assert swizzle.swizzle_proofs_hold(swizzle_root=Path("/x")) == (True, "SWIZZLE proofs: 12 of 12 proofs hold.")


def _gov(items, code=0, err=""):
    return _proc(json.dumps(items), err, code)


GOOD = [{"scenario": "a", "severity": "high", "status": "held"},
        {"scenario": "b", "severity": "low", "status": "violated"}]


def test_governor_report_is_read_when_it_is_well_formed(monkeypatch):
    monkeypatch.setattr(swizzle, "run_instrument", lambda *a, **kw: _gov(GOOD, 1))
    got = swizzle.governor_attacks(swizzle_root=Path("/x"), warden_root=Path("/w"))
    assert [g["status"] for g in got] == ["held", "violated"]


@pytest.mark.parametrize("proc", [
    _gov(GOOD, 2, "Traceback: cannot import warden"),
    _gov(GOOD, 3),
    _gov([], 0),
    _gov({"findings": GOOD}, 0),
    _gov([GOOD[0], "held"], 0),
    _gov([{"scenario": "a", "severity": "high"}], 0),
    _gov([{"scenario": "a", "severity": 3, "status": "held"}], 0),
    _gov([{"scenario": "a", "severity": "high", "status": "errored"}], 0),
    _gov([{"scenario": "a", "severity": "high", "status": "not_run"}], 0),
    _proc("banner\n" + json.dumps(GOOD), "", 0),
    _proc("", "", 0),
])
def test_governor_report_is_not_measured_unless_every_item_is_well_formed(monkeypatch, proc):
    monkeypatch.setattr(swizzle, "run_instrument", lambda *a, **kw: proc)
    notes: list = []
    assert swizzle.governor_attacks(swizzle_root=Path("/x"), warden_root=Path("/w"), note=notes) is None
    assert notes and "not measured" in notes[0]


def test_governor_not_measured_note_carries_swizzles_stderr(monkeypatch):
    monkeypatch.setattr(swizzle, "run_instrument", lambda *a, **kw: _gov(GOOD, 2, "fatal: warden import failed"))
    notes: list = []
    swizzle.governor_attacks(swizzle_root=Path("/x"), warden_root=Path("/w"), note=notes)
    assert "warden import failed" in notes[0]


def test_governor_status_is_compared_after_lowercasing(monkeypatch):
    monkeypatch.setattr(swizzle, "run_instrument",
                        lambda *a, **kw: _gov([{"scenario": "a", "severity": "High", "status": "VIOLATED"}], 1))
    got = swizzle.governor_attacks(swizzle_root=Path("/x"), warden_root=Path("/w"))
    assert got[0]["status"] == "violated"


def _card(judgements, proof="29/29"):
    return {"judgements": judgements, "proof": proof}


MODES = [{"specimen_class": "FAILURE_MODE", "outcome": o} for o in ("banished", "banished", "escaped", "misnamed")]


def _assay(monkeypatch, proc):
    monkeypatch.setattr(swizzle, "run_instrument", lambda *a, **kw: proc)
    return swizzle.assay_score(swizzle_root=Path("/x"), assay_root=Path("/a"))


def test_assay_counts_only_known_outcomes(monkeypatch):
    state, score, _ = _assay(monkeypatch, _proc(json.dumps(_card(MODES))))
    assert state is True and (score["failure_modes"], score["caught"], score["escaped"], score["misnamed"]) == (4, 2, 1, 1)


@pytest.mark.parametrize("card", [
    {"judgements": None}, {"judgements": "none"}, {"judgements": []}, {"judgements": [None, 3]},
    {"judgements": [{"specimen_class": "REFERENCE", "outcome": "banished"}]},
    {"results": MODES}, [1, 2], None,
])
def test_assay_with_odd_judgements_is_not_graded_and_does_not_crash(monkeypatch, card):
    state, score, why = _assay(monkeypatch, _proc(json.dumps(card)))
    assert state is None and score == {} and why


def test_assay_with_an_unknown_outcome_is_unscorable(monkeypatch):
    odd = MODES + [{"specimen_class": "FAILURE_MODE", "outcome": "caught-ish"}]
    state, score, why = _assay(monkeypatch, _proc(json.dumps(_card(odd))))
    assert state is False and score == {} and "caught-ish" in why
    state, _, _ = _assay(monkeypatch, _proc(json.dumps(_card([{"specimen_class": "FAILURE_MODE"}]))))
    assert state is False


def test_assay_banner_is_ignored_only_if_the_rest_parses(monkeypatch):
    good = "swizzle 2.0\n" + json.dumps(_card(MODES), indent=1)
    assert _assay(monkeypatch, _proc(good))[0] is True
    partial = 'swizzle\n{"judgements": [{"specimen_class": "FAILURE_MODE", "outcome": "banished"}]} trailing junk'
    assert _assay(monkeypatch, _proc(partial))[0] is None
    cut = "banner\n" + json.dumps(_card(MODES))[:-5]
    assert _assay(monkeypatch, _proc(cut))[0] is None


def _ghost(monkeypatch, out, err="", code=0):
    monkeypatch.setattr(ghost, "run_instrument", lambda *a, **kw: _proc(out, err, code))
    return ghost.scan(Path("."), ghost_tools_root=Path("/g"))


@pytest.mark.parametrize("out", [
    '[{"id": ["a"], "summary": "x"}]', '[{"id": 7}]', '[{"id": null}]', '["finding"]', '[1]', '{"findings": 3}',
    "not json", '{"id": "ghost-1"}',
])
def test_ghost_findings_must_be_records_with_text_ids(monkeypatch, out):
    with pytest.raises(RuntimeError):
        _ghost(monkeypatch, out)


def test_ghost_timeout_is_passed_to_the_subprocess_and_reported(monkeypatch):
    seen = {}

    def fake(cmd, *, roots, timeout, **kw):
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(ghost, "run_instrument", fake)
    with pytest.raises(RuntimeError, match="did not finish within 7 seconds"):
        ghost.scan(Path("."), ghost_tools_root=Path("/g"), ghost_timeout=7)
    assert seen["timeout"] == 7
    assert ghost.DEFAULT_TIMEOUT == 600


def test_garbled_ghost_output_after_edits_puts_the_tree_back(tmp_path, monkeypatch):
    t = _repo(tmp_path / "t")
    calls = {"n": 0}

    def scan(target, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return ()
        raise RuntimeError("ghost_buster JSON was not a list of findings")
    monkeypatch.setattr(tagteam, "ghost_scan", scan)
    result = TagTeam(drafter=FakeDrafter(), ghost_tools_root=tmp_path).run(
        t, authorization=grant("w", "transform", str(t.resolve()), "documentation", "r"))
    assert result.decision == "INCONCLUSIVE" and result.put_back and "ghost" in result.unmeasured
    assert (t / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_a_finding_with_a_list_id_in_a_findings_file_is_ghost_garbled_not_a_crash(tmp_path):
    t = _repo(tmp_path / "t")
    result = TagTeam(drafter=FakeDrafter()).run(
        t, findings=[{"id": ["x"], "summary": "s"}], authorization=grant("w", "transform", str(t.resolve()), "documentation", "r"))
    assert result.decision == "INCONCLUSIVE" and "ghost" in result.unmeasured
    result = TagTeam(drafter=FakeDrafter()).run(t, findings=["oops"])
    assert result.decision == "INCONCLUSIVE"


def test_ghost_that_scanned_nothing_is_not_clean(tmp_path, monkeypatch):
    t = _repo(tmp_path / "t")
    blind = ghost.Findings(())
    blind.blind = "Ghost scanned 0 files, so an empty list of findings does not mean the code is clean"
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: blind)
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    result = TagTeam(drafter=FakeDrafter(steps=()), ghost_tools_root=tmp_path, swizzle_root=tmp_path).run(
        t, authorization=grant("w", "transform", str(t.resolve()), "documentation", "r"))
    assert "ghost" in result.unmeasured and any("scanned 0 files" in n for n in result.notes)
    assert result.decision != "ACCEPT"


def test_ghost_scan_reads_the_files_scanned_line_from_stderr(monkeypatch):
    got = _ghost(monkeypatch, "[]", "ghost_buster: scanning 0 file(s) under /x\n")
    assert got == () and got.blind
    got = _ghost(monkeypatch, "[]", "ghost_buster: nothing analysed\n")
    assert got.blind
    got = _ghost(monkeypatch, "[]", "ghost_buster: scanning 12 file(s) under /x\n")
    assert got == () and got.blind is None


# -- 4. the version handshake ------------------------------------------------------------------------

def test_warden_exposes_its_version_and_contract():
    assert warden.CONTRACT == "1" and isinstance(warden.__version__, str)


def test_a_seat_that_wants_another_contract_is_refused_with_both_versions_named(rig):
    code, payload, err = rig.run(drafter="exit_seats:Old")
    assert code == 2 and payload["decision"] == "SEAT_NOT_LOADED"
    assert "'0'" in payload["reason"] and "'1'" in payload["reason"]
    assert (rig.target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_a_seat_with_the_right_contract_runs_with_no_warning(rig):
    code, payload, err = rig.run(drafter="exit_seats:Current")
    assert "requires_contract" not in err and code in (0, 3)


def test_a_seat_without_a_contract_is_refused_and_nothing_runs(rig):
    code, payload, err = rig.run(drafter="exit_seats:Unversioned")
    assert code == 2 and payload["decision"] == "SEAT_NOT_LOADED"
    assert "does not say which Warden contract" in payload["reason"]
    assert 'requires_contract = "1"' in payload["reason"]
    assert "requires_contract" in err
    assert (rig.target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_each_seat_position_refuses_a_missing_declaration(rig):
    for flag in ("drafter", "finisher", "judge"):
        code, payload, _ = rig.run(**{flag: "exit_seats:Unversioned"})
        assert code == 2 and payload["decision"] == "SEAT_NOT_LOADED", flag


def test_the_output_names_the_contract_checked_and_the_versions_that_took_part(rig):
    code, payload, _ = rig.run(drafter="exit_seats:Current", judge="exit_seats:Judge")
    assert payload["contract"] == warden.CONTRACT == "1"
    v = payload["versions"]
    assert v["warden"]["version"] == warden.__version__ and v["warden"]["contract"] == "1"
    assert v["seats"]["drafter"]["spec"] == "exit_seats:Current"
    assert v["seats"]["drafter"]["requires_contract"] == "1"
    assert v["seats"]["judge"]["requires_contract"] == "1"
    assert v["seats"]["finisher"] is None
    for key, folder in (("ghost_tools", "ghost"), ("swizzle", "swizzle"), ("assay", "assay")):
        assert v[key]["path"].endswith(folder) and v[key]["commit"] is None and v[key]["version"] is None


def test_an_instrument_that_was_not_given_is_reported_as_null(rig):
    _, payload, _ = rig.run(measured=False)
    v = payload["versions"]
    assert v["ghost_tools"] is None and v["swizzle"] is None and v["assay"] is None


def test_a_refusal_also_names_the_contract_checked(rig):
    _, payload, _ = rig.run(drafter="exit_seats:Old")
    assert payload["contract"] == "1"


def test_a_verdict_with_no_judge_name_and_an_extra_field_is_reported_not_a_crash(rig):
    code, payload, _ = rig.run(judge="exit_seats:OddJudge")
    assert payload["decision"] in {"ACCEPT", "ACCEPT_UNVERIFIED"}
    notes = " ".join(payload["notes"])
    assert "did not name the judge" in notes and "fields Warden does not know" in notes


# -- 5. small items ----------------------------------------------------------------------------------

def test_a_target_that_does_not_exist_or_is_a_file_exits_2_with_json(rig, tmp_path):
    code, payload, _ = rig.run(path=tmp_path / "nowhere")
    assert code == 2 and payload["decision"] == "USAGE_ERROR" and "does not exist" in payload["reason"]
    (tmp_path / "afile").write_text("x", encoding="utf-8")
    code, payload, _ = rig.run(path=tmp_path / "afile")
    assert code == 2 and "not a directory" in payload["reason"]


def test_an_authorization_without_a_reason_is_refused(rig, tmp_path, capsys):
    code = main(["tagteam", str(rig.target), "--from-ghost", str(_findings(tmp_path)), "--drafter", "exit_seats:Once",
                 "--authorize", "william", "--reason", "   "])
    payload = json.loads(capsys.readouterr().out)
    assert code == 5 and payload["decision"] == "REFUSED" and payload["reason"] == "a reason is required"
    assert (rig.target / "NOTE.md").read_text(encoding="utf-8") == "old\n"
    code = main(["tagteam", str(rig.target), "--from-ghost", str(_findings(tmp_path)),
                 "--authorize", "william"])
    assert code == 5 and json.loads(capsys.readouterr().out)["reason"] == "a reason is required"


def test_a_self_authorization_is_refused_with_json_and_exit_5(rig, tmp_path, capsys):
    code = main(["tagteam", str(rig.target), "--from-ghost", str(_findings(tmp_path)),
                 "--authorize", "warden", "--reason", "x"])
    assert code == 5 and json.loads(capsys.readouterr().out)["decision"] == "REFUSED"


def test_a_proposal_that_changes_nothing_is_dropped_not_applied(rig):
    code, payload, _ = rig.run(drafter="exit_seats:NoOp")
    outcomes = [c["outcome"] for c in payload["cycles"]]
    assert outcomes == ["NOTHING_TO_PROPOSE"] and payload["converged"] is True
    assert any("would change nothing" in n for n in payload["notes"])
    assert "APPLIED" not in outcomes and payload["decision"] != "NOT_CONVERGED"


def test_an_out_of_scope_proposal_that_cites_no_defect_is_declined_and_the_loop_goes_on(rig):
    code, payload, _ = rig.run(drafter="exit_seats:CodeFile", scope="documentation")
    assert [c["outcome"] for c in payload["cycles"]] == ["DECLINED", "NOTHING_TO_PROPOSE"]
    assert payload["decision"] == "ACCEPT" and code == 0
    assert (rig.target / "pkg" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert any("declined, nothing was written" in n for n in payload["notes"])


def test_an_out_of_scope_proposal_repeated_ends_the_run(rig):
    code, payload, _ = rig.run(drafter="exit_seats:CodeFileAlways", scope="documentation")
    assert payload["decision"] == "NOT_CONVERGED" and code == 1
    assert (rig.target / "pkg" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_a_proposal_that_also_touches_a_test_file_is_still_rejected(rig):
    code, payload, _ = rig.run(drafter="exit_seats:ScopeAndTest", scope="documentation")
    assert payload["decision"] == "REJECT" and code == 1
    assert (rig.target / "tests" / "test_x.py").read_text(encoding="utf-8").count("assert VALUE == 1") == 1
