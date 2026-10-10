"""Red-team false accepts, part two: a suite that skips, vendored code, a suite that rewrites
source, a killed keep test, concurrent runs, byte-faithful restores, and the audit file."""

import base64
import json
import tempfile
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden import runstate
from warden.authorization import grant
from warden.cli import main
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.suite import run_suite
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge, RemovingDrafter

DEAD_PY = "def unused():\n    return 1\n"
GOOD_TEST = "from pkg import VALUE\n\ndef test_value():\n    assert VALUE == 1\n"


def _repo(root: Path, tests: str = GOOD_TEST, dead: str = "pkg/dead.py", dead_text: str = DEAD_PY) -> Path:
    (root / "pkg").mkdir(exist_ok=True)
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_pkg.py").write_text(tests, encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    if dead:
        (root / dead).parent.mkdir(parents=True, exist_ok=True)
        (root / dead).write_bytes(dead_text.encode("utf-8") if isinstance(dead_text, str) else dead_text)
    return root


def _auth(root: Path, scope="code"):
    return grant("william", "transform", str(root.resolve()), scope, "false accept test")


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _scanner(monkeypatch, rel: str, ident: str = "ghost-dead1"):
    """Ghost reports the finding until the file has been commented out."""
    finding = {"id": ident, "severity": "minor", "summary": "unused", "status": "confirmed"}

    def fake_scan(target, **kw):
        p = Path(target) / rel
        if not p.exists() or b"WARDEN COMMENTED OUT" in p.read_bytes():
            return ()
        return (finding,)

    monkeypatch.setattr(tagteam, "ghost_scan", fake_scan)
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    return finding


@pytest.fixture(autouse=True)
def private_temp(tmp_path_factory, monkeypatch):
    """Locks and journals go to a temp directory of their own, so tests cannot meet each other."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path_factory.mktemp("warden-tmp")))


# -- 5. the keep test does not trust a suite that skips ---------------------------------------

SKIPPING = {
    "skip": GOOD_TEST + "\nimport pytest\n\n@pytest.mark.skip(reason='later')\ndef test_dead():\n    from pkg.dead import unused\n    assert unused() == 1\n",
    "xfail": GOOD_TEST + "\nimport pytest\n\n@pytest.mark.xfail(reason='known')\ndef test_dead():\n    from pkg.dead import unused\n    assert unused() == 2\n",
    "importorskip": "import pytest\n\npytest.importorskip('no_such_module_for_warden_tests')\nfrom pkg.dead import unused\n\n\ndef test_dead():\n    assert unused() == 1\n",
}


@pytest.mark.parametrize("kind", sorted(SKIPPING))
def test_code_covered_only_by_tests_that_did_not_run_is_not_commented_out(tmp_path, monkeypatch, kind):
    tests = SKIPPING[kind]
    _repo(tmp_path, tests)
    if kind == "importorskip":  # keep one test that really runs so the suite is green
        (tmp_path / "tests" / "test_ok.py").write_text(GOOD_TEST, encoding="utf-8")
    finding = _scanner(monkeypatch, "pkg/dead.py")
    result = TagTeam(drafter=RemovingDrafter(), ghost_tools_root=Path(".")).run(
        tmp_path, findings=[finding], authorization=_auth(tmp_path))
    assert result.cycles[0].outcome == "DECLINED"
    assert _read(tmp_path, "pkg/dead.py") == DEAD_PY
    assert any("some tests did not run (" in n and "so the suite cannot prove this code is unused" in n
               for n in result.notes)


def test_the_suite_run_counts_xfailed_and_xpassed(tmp_path):
    _repo(tmp_path, GOOD_TEST + "\nimport pytest\n\n@pytest.mark.xfail\ndef test_a():\n    assert False\n\n"
                    "@pytest.mark.xfail\ndef test_b():\n    assert True\n", dead="")
    import sys
    run = run_suite(tmp_path, sys.executable)
    assert run.xfailed == 1 and run.xpassed == 1 and run.passed == 1
    assert "1 xfailed" in run.describe()


def test_the_judge_is_told_how_many_tests_were_expected_to_fail(tmp_path, monkeypatch):
    _repo(tmp_path, GOOD_TEST + "\nimport pytest\n\n@pytest.mark.xfail\ndef test_a():\n    assert False\n", dead="")
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: ())
    judge = FakeJudge()
    TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge, ghost_tools_root=Path("."),
            swizzle_root=Path("."), assay_root=Path(".")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    assert judge.evidence.suite_before.xfailed == 1 and judge.evidence.suite_after.xfailed == 1


# -- 6. vendored and generated code is not edited -------------------------------------------

@pytest.mark.parametrize("rel,text", [
    ("vendor/lib/v.py", DEAD_PY),
    ("gen/x_pb2.py", DEAD_PY),
    ("third_party/a.py", DEAD_PY),
    ("pkg/made.py", "# DO NOT EDIT. Made by a tool.\n" + DEAD_PY),
    ("pkg/made.py", "#!/usr/bin/env python\n# Generated by protoc\n" + DEAD_PY),
    ("pkg/made.py", "# @generated\n" + DEAD_PY),
    ("pkg/made.py", "# This file is Auto-Generated\n" + DEAD_PY),
])
def test_a_removal_in_vendored_or_generated_code_is_declined(tmp_path, monkeypatch, rel, text):
    _repo(tmp_path, dead=rel, dead_text=text)
    finding = _scanner(monkeypatch, rel)
    result = TagTeam(drafter=RemovingDrafter(path=rel), ghost_tools_root=Path(".")).run(
        tmp_path, findings=[finding], authorization=_auth(tmp_path))
    assert result.cycles[0].outcome == "DECLINED"
    assert (tmp_path / rel).read_text(encoding="utf-8") == text
    assert any("this looks vendored or generated, so a change would be undone by the next update" in n
               for n in result.notes)


def test_any_code_edit_in_a_vendored_directory_is_declined_not_only_removals(tmp_path):
    _repo(tmp_path, dead="vendor/lib/v.py", dead_text="X = 1\n")
    finding = {"id": "ghost-1", "severity": "minor", "summary": "s", "status": "confirmed"}

    class Edits:
        def __init__(self):
            self.n = 0

        def propose(self, target, observed, baseline):
            self.n += 1
            if not observed:
                return None
            return Transformation(
                target=str(Path(target).resolve()), intent="x", architectural_reason="x",
                affected_files=("vendor/lib/v.py",), expected_behavior="x", preservation_requirements=(),
                known_defects=observed, transformation_scope="code", baseline_reference=baseline, evidence=(),
                edits=(FileEdit("vendor/lib/v.py", "write", "X = 2\n", "X = 1\n"),),
                status=TransformationStatus.PROPOSED)

    result = TagTeam(drafter=Edits()).run(tmp_path, findings=[finding], authorization=_auth(tmp_path))
    assert result.cycles[0].outcome == "DECLINED" and _read(tmp_path, "vendor/lib/v.py") == "X = 1\n"


# -- 7. a suite that modifies source is not trusted -------------------------------------------

@pytest.mark.parametrize("when", ["always", "after the change"])
def test_a_suite_that_changes_source_stops_the_run(tmp_path, when):
    _repo(tmp_path, dead="")
    src = tmp_path / "pkg" / "__init__.py"
    trigger = "True" if when == "always" else f"open({str(tmp_path / 'NOTE.md')!r}).read() == 'new\\n'"
    _repo_tests = (f"from pkg import VALUE\n\ndef test_value():\n    assert VALUE == 1\n"
                   f"    if {trigger}:\n        open({str(src)!r}, 'a').write('# touched by the suite\\n')\n")
    (tmp_path / "tests" / "test_pkg.py").write_text(_repo_tests, encoding="utf-8")
    result = TagTeam(drafter=FakeDrafter(steps=("new\n",))).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    assert result.decision == "INCONCLUSIVE"
    assert any("the test suite changed source files, so its result cannot be trusted" in n for n in result.notes)
    assert _read(tmp_path, "pkg/__init__.py") == "VALUE = 1\n" and _read(tmp_path, "NOTE.md") == "old\n"
    assert "The tree was put back as it was found because the run did not finish accepted." in result.notes


# -- 8. a killed keep test cannot leave a trap behind ------------------------------------------

def test_the_original_bytes_are_journaled_outside_the_target_before_a_trap_is_written(tmp_path, monkeypatch):
    _repo(tmp_path)
    finding = _scanner(monkeypatch, "pkg/dead.py")
    seen = {}
    real = tagteam.run_suite

    def spying(target, python, *a, **kw):
        if b"warden keep-test" in (Path(target) / "pkg" / "dead.py").read_bytes():
            journal = runstate.journal_path(Path(target))
            seen["journal"] = json.loads(journal.read_text(encoding="utf-8"))
            seen["outside"] = not str(journal).startswith(str(target))
        return real(target, python, *a, **kw)

    monkeypatch.setattr(tagteam, "run_suite", spying)
    result = TagTeam(drafter=RemovingDrafter(), ghost_tools_root=Path(".")).run(
        tmp_path, findings=[finding], authorization=_auth(tmp_path))
    assert result.cycles[0].outcome == "APPLIED"
    original = base64.b64decode(seen["journal"]["files"]["pkg/dead.py"]["original"])
    assert original == DEAD_PY.encode() and seen["outside"]
    assert not runstate.journal_path(tmp_path).exists()


def test_a_leftover_journal_is_restored_at_the_start_of_the_next_run(tmp_path):
    _repo(tmp_path)
    original = (tmp_path / "pkg" / "dead.py").read_bytes()
    trap = b"raise RuntimeError('warden keep-test: trap')\n"
    runstate.write_journal(tmp_path, {"pkg/dead.py": original}, {"pkg/dead.py": trap})
    (tmp_path / "pkg" / "dead.py").write_bytes(trap)
    result = TagTeam(drafter=None).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert (tmp_path / "pkg" / "dead.py").read_bytes() == original
    assert "A previous run was interrupted during the keep test; its trap code was removed." in result.notes
    assert not runstate.journal_path(tmp_path).exists()


def test_a_journal_cannot_write_outside_the_target(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    _repo(target)
    runstate.write_journal(target, {"../escaped.txt": b"x", "/tmp/warden-abs.txt": b"x"},
                           {"../escaped.txt": b"y", "/tmp/warden-abs.txt": b"y"})
    TagTeam(drafter=None).run(target, findings=[], authorization=_auth(target))
    assert not (tmp_path / "escaped.txt").exists() and not Path("/tmp/warden-abs.txt").exists()


# -- 9. a lock against concurrent runs -------------------------------------------------------------

def test_a_second_run_on_a_held_target_changes_nothing(tmp_path):
    _repo(tmp_path)
    drafter = FakeDrafter(steps=("new\n",))
    held = runstate.TargetLock(tmp_path)
    assert held.acquire()
    try:
        result = TagTeam(drafter=drafter).run(tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    finally:
        held.release()
    assert result.decision == "INCONCLUSIVE" and drafter.calls == 0
    assert any("another Warden run is using this target" in n for n in result.notes)
    assert _read(tmp_path, "NOTE.md") == "old\n"
    again = TagTeam(drafter=FakeDrafter(steps=("new\n",))).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    assert again.decision.startswith("ACCEPT")  # released, so the next run goes ahead


def test_the_lock_is_released_after_a_run_that_fails(tmp_path):
    _repo(tmp_path)

    class Boom:
        def propose(self, *a):
            raise RuntimeError("x")

    TagTeam(drafter=Boom()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    probe = runstate.TargetLock(tmp_path)
    assert probe.acquire()
    probe.release()


# -- 10. restores are byte faithful ----------------------------------------------------------------

def test_a_failing_change_to_a_crlf_file_comes_back_with_crlf(tmp_path):
    _repo(tmp_path, dead="")
    (tmp_path / "pkg" / "__init__.py").write_bytes(b"VALUE = 1\r\n")
    before = (tmp_path / "pkg" / "__init__.py").read_bytes()
    result = TagTeam(drafter=FakeDrafter(steps=("VALUE = 2\n",), path="pkg/__init__.py")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT"
    assert (tmp_path / "pkg" / "__init__.py").read_bytes() == before


def test_an_accepted_change_to_a_crlf_file_keeps_crlf(tmp_path):
    _repo(tmp_path, dead="")
    (tmp_path / "NOTE.md").write_bytes(b"one\r\ntwo\r\n")
    result = TagTeam(drafter=FakeDrafter(steps=("one\ntwo\nthree\n",))).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    assert result.decision.startswith("ACCEPT")
    assert (tmp_path / "NOTE.md").read_bytes() == b"one\r\ntwo\r\nthree\r\n"


def test_a_replace_edit_written_with_lf_matches_and_keeps_a_crlf_file(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x = 1\r\ny = 2\r\n")
    t = Transformation(target=str(tmp_path), intent="i", architectural_reason="r", affected_files=("a.txt",),
                       expected_behavior="e", preservation_requirements=(), known_defects=(),
                       transformation_scope="code", baseline_reference="b", evidence=(),
                       edits=(FileEdit("a.txt", "replace", "x = 3\n", "x = 1\n"),))
    t.authorize(_auth(tmp_path))
    t.apply(tmp_path)
    assert (tmp_path / "a.txt").read_bytes() == b"x = 3\r\ny = 2\r\n"


def test_a_commented_out_crlf_file_stays_crlf(tmp_path, monkeypatch):
    _repo(tmp_path, dead_text=DEAD_PY.replace("\n", "\r\n"))
    finding = _scanner(monkeypatch, "pkg/dead.py")
    result = TagTeam(drafter=RemovingDrafter(), ghost_tools_root=Path(".")).run(
        tmp_path, findings=[finding], authorization=_auth(tmp_path))
    raw = (tmp_path / "pkg" / "dead.py").read_bytes()
    assert result.cycles[0].outcome == "APPLIED" and b"WARDEN COMMENTED OUT" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_a_latin1_file_does_not_crash_the_run_and_edits_to_it_are_declined(tmp_path):
    _repo(tmp_path, dead="legacy.py", dead_text=b"# caf\xe9\nX = 1\n")
    legacy = (tmp_path / "legacy.py").read_bytes()
    finding = {"id": "ghost-1", "severity": "minor", "summary": "s", "status": "confirmed", "evidence": {"file": "legacy.py"}}

    class Edits:
        def propose(self, target, observed, baseline):
            if not observed:
                return None
            return Transformation(
                target=str(Path(target).resolve()), intent="x", architectural_reason="x",
                affected_files=("legacy.py",), expected_behavior="x", preservation_requirements=(),
                known_defects=observed, transformation_scope="code", baseline_reference=baseline, evidence=(),
                edits=(FileEdit("legacy.py", "replace", "X = 2\n", "X = 1\n"),),
                status=TransformationStatus.PROPOSED)

    result = TagTeam(drafter=Edits()).run(tmp_path, findings=[finding], authorization=_auth(tmp_path))
    assert result.decision != "ERROR" and result.cycles[0].outcome == "DECLINED"
    assert (tmp_path / "legacy.py").read_bytes() == legacy
    assert any("not valid UTF-8" in n for n in result.notes)


def test_apply_refuses_a_latin1_file_in_plain_words(tmp_path):
    (tmp_path / "a.py").write_bytes(b"# caf\xe9\nX = 1\n")
    t = Transformation(target=str(tmp_path), intent="i", architectural_reason="r", affected_files=("a.py",),
                       expected_behavior="e", preservation_requirements=(), known_defects=(),
                       transformation_scope="code", baseline_reference="b", evidence=(),
                       edits=(FileEdit("a.py", "write", "X = 2\n", ""),))
    t.authorize(_auth(tmp_path))
    with pytest.raises(ValueError, match="not valid UTF-8"):
        t.apply(tmp_path)
    assert (tmp_path / "a.py").read_bytes() == b"# caf\xe9\nX = 1\n"


# -- 11. the audit command does not overwrite or escape ----------------------------------------------

def _findings_file(tmp_path: Path) -> Path:
    f = tmp_path / "f.json"
    f.write_text(json.dumps([{"id": "ghost-1", "severity": "minor", "summary": "s"}]), encoding="utf-8")
    return f


def test_audit_will_not_overwrite_a_hand_written_file_without_markers(tmp_path, capsys):
    target = tmp_path / "t"
    target.mkdir()
    (target / "WARDEN_AUDIT.md").write_text("# My own audit\nHand written.\n", encoding="utf-8")
    code = main(["audit", str(target), "--from-ghost", str(_findings_file(tmp_path)),
                 "--authorize", "william", "--reason", "x"])
    assert code != 0 and _read(target, "WARDEN_AUDIT.md") == "# My own audit\nHand written.\n"
    assert "no Warden markers" in capsys.readouterr().err


def test_audit_will_not_write_through_a_symlink(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("keep me\n", encoding="utf-8")
    (target / "WARDEN_AUDIT.md").symlink_to(outside)
    code = main(["audit", str(target), "--from-ghost", str(_findings_file(tmp_path)),
                 "--authorize", "william", "--reason", "x"])
    assert code != 0 and outside.read_text(encoding="utf-8") == "keep me\n"


def test_audit_still_writes_a_new_file_and_updates_a_marked_one(tmp_path):
    target = tmp_path / "t"
    target.mkdir()
    args = ["audit", str(target), "--from-ghost", str(_findings_file(tmp_path)), "--authorize", "william", "--reason", "x"]
    assert main(args) == 0 and "ghost-1" in _read(target, "WARDEN_AUDIT.md")
    assert main(args) == 0
