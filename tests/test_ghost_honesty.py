"""Warden reads both Ghosts: the old bare list and the new honest object.

New Ghost (exit codes 0 clean / 1 findings / 2 did not start / 3 crashed) says whether its scan
finished, how much it looked at, and which checks did not run. Only checks that should have run
and did not are a gap. Checks the caller declined or that are opt-in and unrequested are
information. A clean default run must still be able to ACCEPT.
"""

import json
import subprocess
from pathlib import Path

import pytest

import warden.cli as cli
import warden.ghost as ghost
import warden.tagteam as tagteam
from warden import audit
from warden.authorization import grant
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge


def _proc(out, err="", code=0):
    return subprocess.CompletedProcess(["x"], code, out, err)


def _row(check, by_request, reason=None, state="declined"):
    return {"check": check, "state": state, "by_request": by_request,
            "reason": reason or ("skipped at your request" if by_request else f"{check} could not run")}


#: What new Ghost prints for Warden's own default flags on a clean repo.
DEFAULT_ROWS = [_row("mutate", True, "opt-in and not requested (--mutate)", "not_run"),
                _row("kernel", True, "opt-in and not requested (--kernel PATH)", "not_run"),
                _row("tests", True, "skipped at your request (--no-tests)"),
                _row("secrets", True, "skipped at your request (--no-secrets)")]


def _obj(findings=(), status="ok", rows=DEFAULT_ROWS, scanned=3, unparsable=(), exit_code=0, error=None):
    return json.dumps({
        "status": status, "error": error, "exit_code": exit_code, "findings": list(findings),
        "scan": {"files_scanned": scanned, "files_skipped": 0, "files_unparsable": len(unparsable),
                 "unparsable": [{"file": f, "reason": "SyntaxError"} for f in unparsable]},
        "unmeasured": list(rows)})


def _scan(monkeypatch, out, err="", code=0):
    monkeypatch.setattr(ghost, "run_instrument", lambda *a, **kw: _proc(out, err, code))
    return ghost.scan(Path("."), ghost_tools_root=Path("/g"))


# -- the reader ---------------------------------------------------------------------------------

def test_old_ghost_bare_list_still_reads_with_no_gaps(monkeypatch):
    got = _scan(monkeypatch, '[{"id": "ghost-1", "summary": "s"}]', code=1)
    assert [f["id"] for f in got] == ["ghost-1"]
    assert got.gaps == () and got.status is None and got.scan_counts is None


def test_new_ghost_clean_default_run_has_no_gap(monkeypatch):
    got = _scan(monkeypatch, _obj())
    assert got == () and got.status == "ok" and got.gaps == ()
    assert got.scan_counts["files_scanned"] == 3
    assert set(got.declined) == {"mutate", "kernel", "tests", "secrets"}


def test_new_ghost_findings_come_through_as_the_same_records(monkeypatch):
    got = _scan(monkeypatch, _obj([{"id": "ghost-aaa", "summary": "dead"}]), code=1)
    assert [f["id"] for f in got] == ["ghost-aaa"] and got.gaps == ()


def test_unparsable_files_are_a_gap(monkeypatch):
    rows = DEFAULT_ROWS + [{"check": "parse", "state": "unparsable", "by_request": False,
                            "reason": "1 file(s) could not be parsed, so the code detectors skipped them"}]
    got = _scan(monkeypatch, _obj(findings=[{"id": "g1"}], status="incomplete", rows=rows, unparsable=["pkg/bad.py"]),
                code=1)
    assert got.status == "incomplete" and len(got.gaps) == 1 and got.gaps[0].startswith("parse:")
    assert got.scan_counts["files_unparsable"] == 1


def test_unparsable_count_is_a_gap_even_if_ghost_forgot_the_row(monkeypatch):
    got = _scan(monkeypatch, _obj(rows=DEFAULT_ROWS, unparsable=["a.py"]))
    assert got.gaps and got.gaps[0].startswith("parse:")


def test_a_detector_that_raised_and_git_missing_are_gaps(monkeypatch):
    rows = DEFAULT_ROWS + [_row("structural", False, "2 detector(s) raised", "could_not_run"),
                           _row("branches", False, "git is not available", "could_not_run")]
    got = _scan(monkeypatch, _obj(status="incomplete", rows=rows))
    assert [g.split(":")[0] for g in got.gaps] == ["structural", "branches"]


def test_a_row_that_does_not_say_who_asked_is_a_gap_and_requested_is_an_alias(monkeypatch):
    rows = [{"check": "x", "reason": "no idea"}, {"check": "y", "requested": True, "reason": "asked"},
            {"check": "z", "requested": False, "reason": "not asked"}]
    got = _scan(monkeypatch, _obj(rows=rows))
    assert [g.split(":")[0] for g in got.gaps] == ["x", "z"] and got.declined == ("y",)


def test_incomplete_with_no_rows_is_still_a_gap(monkeypatch):
    got = _scan(monkeypatch, _obj(status="incomplete", rows=[]))
    assert got.gaps


def test_gap_text_is_one_plain_capped_line(monkeypatch):
    rows = [_row("parse", False, "bad\x1b[31m\nred " + "z" * 500)]
    got = _scan(monkeypatch, _obj(rows=rows))
    assert "\x1b" not in got.gaps[0] and "\n" not in got.gaps[0] and len(got.gaps[0]) < 220


def test_error_status_unknown_status_and_zero_files_do_not_read_as_clean(monkeypatch):
    with pytest.raises(RuntimeError, match="error instead of a scan"):
        _scan(monkeypatch, _obj(status="error", error={"kind": "usage", "message": "no such folder"}))
    with pytest.raises(RuntimeError, match="status Warden does not know"):
        _scan(monkeypatch, _obj(status="great"))
    assert _scan(monkeypatch, _obj(scanned=0)).blind


def test_exit_3_is_named_as_a_ghost_crash(monkeypatch):
    err = "Traceback (most recent call last):\n  File x\nKeyError: 'boom'\n"
    with pytest.raises(ghost.GhostCrashed, match=r"Ghost crashed \(exit code 3\): KeyError: 'boom'"):
        _scan(monkeypatch, _obj(status="error", error={"kind": "crash", "message": "KeyError"}), err, 3)
    with pytest.raises(ghost.GhostCrashed):
        _scan(monkeypatch, "", err, 3)


def test_exit_2_is_named_as_did_not_start(monkeypatch):
    with pytest.raises(ghost.GhostRefused, match=r"did not start \(exit code 2\): ghost_buster: bad flag"):
        _scan(monkeypatch, "", "ghost_buster: bad flag\n", 2)


def test_a_saved_report_in_either_shape_loads(tmp_path):
    old, new = tmp_path / "o.json", tmp_path / "n.json"
    old.write_text('[{"id": "ghost-1"}]', encoding="utf-8")
    new.write_text(_obj([{"id": "ghost-1"}], status="incomplete", rows=[_row("parse", False)]), encoding="utf-8")
    assert [f["id"] for f in ghost.load_report(old)] == ["ghost-1"] and ghost.load_report(old).gaps == ()
    got = ghost.load_report(new)
    assert [f["id"] for f in got] == ["ghost-1"] and got.gaps
    assert ghost.load_findings(new) == tuple(got)


# -- the loop -----------------------------------------------------------------------------------

def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _auth(t):
    return grant("william", "transform", str(t.resolve()), "documentation", "ghost honesty test")


@pytest.fixture
def instruments(monkeypatch):
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _team(tmp_path, judge=None, drafter=None):
    return TagTeam(drafter=drafter or FakeDrafter(steps=("new\n",)), judge=judge or FakeJudge("ACCEPT"),
                   ghost_tools_root=tmp_path, swizzle_root=tmp_path, assay_root=tmp_path)


def test_clean_default_run_with_new_ghost_still_accepts(tmp_path, monkeypatch, instruments):
    t = _repo(tmp_path / "t")
    monkeypatch.setattr(ghost, "run_instrument", lambda *a, **kw: _proc(_obj()))
    judge = FakeJudge("ACCEPT")
    r = _team(tmp_path, judge).run(t, authorization=_auth(t))
    assert r.decision == "ACCEPT" and r.unmeasured == ()
    assert r.ghost_scan["status"] == "ok" and r.ghost_scan["gaps"] == []
    assert "mutate" in r.ghost_scan["declined"]
    assert judge.evidence.unmeasured == ()


def test_clean_default_run_with_old_ghost_still_accepts(tmp_path, monkeypatch, instruments):
    t = _repo(tmp_path / "t")
    monkeypatch.setattr(ghost, "run_instrument", lambda *a, **kw: _proc("[]"))
    r = _team(tmp_path).run(t, authorization=_auth(t))
    assert r.decision == "ACCEPT" and r.unmeasured == () and r.ghost_scan is None


def test_an_unparsable_file_reaches_the_judge_and_blocks_a_plain_accept(tmp_path, monkeypatch, instruments):
    t = _repo(tmp_path / "t")
    rows = DEFAULT_ROWS + [_row("parse", False, "1 file(s) could not be parsed, so the code detectors skipped them")]
    monkeypatch.setattr(ghost, "run_instrument",
                        lambda *a, **kw: _proc(_obj(status="incomplete", rows=rows, unparsable=["pkg/bad.py"])))
    judge = FakeJudge("ACCEPT")
    r = _team(tmp_path, judge).run(t, authorization=_auth(t))
    assert r.decision == "ACCEPT_UNVERIFIED"
    assert "ghost_partial" in r.unmeasured and "ghost" not in r.unmeasured
    assert "ghost_partial" in judge.evidence.unmeasured
    assert r.ghost_scan["files_unparsable"] == 1 and r.ghost_scan["gaps"][0].startswith("parse:")
    assert any("Ghost scan has gaps" in n for n in r.notes)


def test_a_judge_reject_still_rejects_when_ghost_has_gaps(tmp_path, monkeypatch, instruments):
    t = _repo(tmp_path / "t")
    monkeypatch.setattr(ghost, "run_instrument",
                        lambda *a, **kw: _proc(_obj(status="incomplete", rows=[_row("parse", False)])))
    r = _team(tmp_path, FakeJudge("REJECT", ("no",))).run(t, authorization=_auth(t))
    assert r.decision == "JUDGE_REJECTED"


def test_ghost_crash_is_inconclusive_and_says_crash(tmp_path, monkeypatch, instruments):
    t = _repo(tmp_path / "t")
    monkeypatch.setattr(ghost, "run_instrument",
                        lambda *a, **kw: _proc("", "Traceback...\nKeyError: 'boom'\n", 3))
    r = _team(tmp_path).run(t, authorization=_auth(t))
    assert r.decision == "INCONCLUSIVE" and "ghost" in r.unmeasured
    assert "Ghost crashed (exit code 3)" in r.reason and "KeyError: 'boom'" in r.reason
    assert "not a finding" in r.reason
    assert (t / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_ghost_that_did_not_start_is_inconclusive_too(tmp_path, monkeypatch, instruments):
    t = _repo(tmp_path / "t")
    monkeypatch.setattr(ghost, "run_instrument", lambda *a, **kw: _proc("", "ghost_buster: bad flag\n", 2))
    r = _team(tmp_path).run(t, authorization=_auth(t))
    assert r.decision == "INCONCLUSIVE" and "did not start (exit code 2)" in r.reason


def test_gaps_in_a_saved_report_count_too(tmp_path, instruments):
    t = _repo(tmp_path / "t")
    f = tmp_path / "n.json"
    f.write_text(_obj(status="incomplete", rows=[_row("parse", False, "1 file(s) could not be parsed")]), encoding="utf-8")
    r = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=FakeJudge("ACCEPT")).run(
        t, findings=ghost.load_report(f), authorization=_auth(t))
    assert r.decision == "ACCEPT_UNVERIFIED" and r.ghost_scan["gaps"]


# -- drafter skipped reasons --------------------------------------------------------------------

class _Skipper(FakeDrafter):
    """Like Drafter: `describe_skipped` reports only the latest call."""

    def __init__(self, lines_per_call, **kw):
        super().__init__(**kw)
        self.lines_per_call = list(lines_per_call)
        self.latest = ()

    def propose(self, target, observed, baseline):
        self.latest = tuple(self.lines_per_call.pop(0)) if self.lines_per_call else ()
        return super().propose(target, observed, baseline)

    def describe_skipped(self):
        return self.latest


def test_drafter_skipped_reasons_are_collected_across_calls(tmp_path, monkeypatch, instruments):
    t = _repo(tmp_path / "t")
    monkeypatch.setattr(ghost, "run_instrument", lambda *a, **kw: _proc("[]"))
    d = _Skipper([["skipped ghost-a: no file"], ["skipped ghost-b: too risky", "skipped ghost-a: no file"]])
    r = _team(tmp_path, drafter=d).run(t, authorization=_auth(t))
    # call 1 proposes, call 2 runs dry: both calls' lines are kept, the repeat once.
    assert r.drafter_skipped == ("skipped ghost-a: no file", "skipped ghost-b: too risky")
    assert r.decision == "ACCEPT" and r.unmeasured == ()  # information, not a gap


def test_drafter_skipped_is_sanitized_and_capped(tmp_path, monkeypatch, instruments):
    t = _repo(tmp_path / "t")
    monkeypatch.setattr(ghost, "run_instrument", lambda *a, **kw: _proc("[]"))
    lines = [f"skipped ghost-{i}: bad\x1b[31m\x00\nreason " + "q" * 400 for i in range(30)] + [42, None]
    r = _team(tmp_path, drafter=_Skipper([lines])).run(t, authorization=_auth(t))
    assert len(r.drafter_skipped) == tagteam.MAX_SKIPPED_LINES + 1
    assert r.drafter_skipped[-1] == "... and 10 more not shown"
    for line in r.drafter_skipped[:-1]:
        assert len(line) <= 200 and "\x1b" not in line and "\x00" not in line and "\n" not in line


def test_a_drafter_without_or_with_a_broken_describe_skipped_is_fine(tmp_path, monkeypatch, instruments):
    t = _repo(tmp_path / "t")
    monkeypatch.setattr(ghost, "run_instrument", lambda *a, **kw: _proc("[]"))
    assert _team(tmp_path).run(t, authorization=_auth(t)).drafter_skipped == ()

    class Broken(FakeDrafter):
        def describe_skipped(self):
            raise ValueError("no")
    t2 = _repo(tmp_path / "t2")
    r = _team(tmp_path, drafter=Broken(steps=("new\n",))).run(t2, authorization=_auth(t2))
    assert r.decision == "ACCEPT" and r.drafter_skipped == ()


def test_the_cli_prints_both_new_fields(tmp_path, monkeypatch, capsys, instruments):
    t = _repo(tmp_path / "t")
    (tmp_path / "g").mkdir(), (tmp_path / "s").mkdir(), (tmp_path / "a").mkdir()
    monkeypatch.setattr(ghost, "run_instrument", lambda *a, **kw: _proc(_obj()))
    monkeypatch.setattr(cli, "_load_seat", lambda spec, w=None: (
        None if not spec else
        _Skipper([["skipped ghost-a: no file"]], steps=("new\n",)) if spec == "d" else FakeJudge("ACCEPT")))
    code = cli.main(["tagteam", str(t), "--drafter", "d", "--judge", "j", "--ghost-root", str(tmp_path / "g"),
                     "--swizzle-root", str(tmp_path / "s"), "--assay-root", str(tmp_path / "a"),
                     "--authorize", "william", "--reason", "x"])
    payload = json.loads(capsys.readouterr().out)
    assert (code, payload["decision"]) == (0, "ACCEPT"), payload["reason"]
    assert payload["drafter_skipped"] == ["skipped ghost-a: no file"]
    assert payload["ghost_scan"]["status"] == "ok" and payload["ghost_scan"]["files_scanned"] == 3


# -- ids change once ----------------------------------------------------------------------------

def _f(ident, file="pkg/mod.py", summary="unused function"):
    return {"id": ident, "detector": "dead_code", "severity": "major", "summary": summary,
            "evidence": {"file": file, "line_start": 4}}


def test_audit_keeps_its_human_id_when_ghost_ids_change_once():
    first = audit.update("", [_f("ghost-old1"), _f("ghost-old2", "pkg/other.py", "another")])
    rows = {r.ghost: r.id for r in audit.existing_rows(first)}
    # New Ghost: same defects, paths now relative to the scanned folder, new ids.
    second = audit.update(first, [_f("ghost-new1", "src/pkg/mod.py"), _f("ghost-new2", "src/pkg/other.py", "another")])
    after = audit.existing_rows(second)
    assert {r.ghost: r.id for r in after} == {"ghost-new1": rows["ghost-old1"], "ghost-new2": rows["ghost-old2"]}
    assert all(r.status == "Open" for r in after) and len(after) == 2


def test_audit_does_not_guess_when_the_match_is_ambiguous():
    first = audit.update("", [_f("ghost-old1", "pkg/mod.py"), _f("ghost-old2", "pkg/mod.py")])
    second = audit.update(first, [_f("ghost-new1", "a/pkg/mod.py"), _f("ghost-new2", "b/pkg/mod.py")])
    rows = audit.existing_rows(second)
    assert len(rows) == 4  # the two old rows stay as "not seen", the two new ones are new rows
    assert sum(r.status == "not seen in latest scan" for r in rows) == 2


def test_audit_does_not_call_a_new_finding_on_the_same_path_a_rename():
    first = audit.update("", [_f("ghost-a")])
    second = audit.update(first, [_f("ghost-c")])  # a fixed, b new, same file and summary: not a rename
    rows = {r.ghost: r for r in audit.existing_rows(second)}
    assert rows["ghost-a"].status == "not seen in latest scan" and rows["ghost-c"].id == "H2"


def test_audit_with_unchanged_ids_behaves_as_before():
    first = audit.update("", [_f("ghost-a")])
    second = audit.update(first, [_f("ghost-a"), _f("ghost-b", "x.py", "other")])
    ids = [(r.id, r.ghost, r.status) for r in audit.existing_rows(second)]
    assert ("H1", "ghost-a", "Open") in ids and len(ids) == 2
