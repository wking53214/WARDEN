"""Red-team false accepts, part one: impersonation, forbidden directories, runs that do not end
accepted, and ids that carry code. Each test reproduces a failure that used to end in ACCEPT, a
crash, or a changed tree, and checks that the run now fails closed."""

import ast
import json
import sys
from pathlib import Path

import pytest

import warden.guard as guard
import warden.tagteam as tagteam
from warden.authorization import Unauthorized, grant
from warden.cli import main
from warden.ghost import scan
from warden.guard import SeatBrokeCharter, watch
from warden.models import FileEdit, Transformation, TransformationStatus, safe_id
from warden.swizzle import assay_score, governor_attacks, swizzle_proofs_hold
from warden.tagteam import TagTeam
from heldutil import keep_held

from fakes import FakeDrafter, FakeFinisher, RemovingDrafter


def _repo(root: Path, test_body: str = "    assert VALUE == 1\n") -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text(
        "from pkg import VALUE\n\ndef test_v():\n" + test_body, encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _auth(root: Path, scope="code"):
    return grant("william", "transform", str(root.resolve()), scope, "false accept test")


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _fake_package(root: Path, name: str, body: str) -> None:
    (root / name).mkdir(parents=True, exist_ok=True)
    (root / name / "__init__.py").write_text("", encoding="utf-8")
    (root / name / "cli.py").write_text(body, encoding="utf-8")


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


# -- 1. the target cannot impersonate an instrument ---------------------------------------------

LIE = "print('12 of 12 proofs hold.')\n"

#: What a SWIZZLE that declares the contract Warden reads prints for `--contract` (SWIZZLE's docs/CONTRACT.md).
DECLARES_CONTRACT = ("import sys\nif sys.argv[1:] == ['--contract']:\n"
                     "    print('{\"name\": \"swizzle\", \"contract\": 1, \"swizzle_version\": \"0.8.0\"}')\n"
                     "    raise SystemExit(0)\n")


def test_a_fake_swizzle_inside_the_target_is_not_believed(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    _fake_package(target, "swizzle", LIE)
    empty_root = tmp_path / "swizzle_root"
    empty_root.mkdir()
    monkeypatch.chdir(target)
    # Sanity: without the protection, running from the target does run the fake.
    import subprocess
    plain = subprocess.run([sys.executable, "-m", "swizzle.cli"], capture_output=True, text=True, cwd=target)
    assert "12 of 12" in plain.stdout
    holds, summary = swizzle_proofs_hold(swizzle_root=empty_root)
    assert holds is False and "12 of 12" not in summary


def test_the_real_root_is_used_even_when_the_target_has_a_fake(tmp_path, monkeypatch):
    target, root = tmp_path / "target", tmp_path / "root"
    target.mkdir()
    root.mkdir()
    _fake_package(target, "swizzle", LIE)
    _fake_package(root, "swizzle", DECLARES_CONTRACT + "print('3 of 3 proofs hold.')\n")
    monkeypatch.chdir(target)
    holds, summary = swizzle_proofs_hold(swizzle_root=Path("../root"))  # a relative root is made absolute
    assert holds is True and "3 of 3" in summary and "12 of 12" not in summary


def test_governor_attacks_and_assay_grading_ignore_a_fake_in_the_target(tmp_path, monkeypatch):
    target, root = tmp_path / "target", tmp_path / "root"
    target.mkdir()
    root.mkdir()
    _fake_package(target, "swizzle", "import json\nprint(json.dumps([{'scenario': 's', 'severity': 'high', 'status': 'held'}]))\n")
    monkeypatch.chdir(target)
    assert governor_attacks(swizzle_root=root, warden_root=target) is None
    state, score, _ = assay_score(swizzle_root=root, assay_root=root)
    assert state is None and score == {}


def test_a_fake_ghost_inside_the_target_is_not_used_by_the_scan(tmp_path, monkeypatch):
    target, root = tmp_path / "target", tmp_path / "root"
    target.mkdir()
    root.mkdir()
    _fake_package(target, "ghost_buster", "print('[{\"id\": \"FAKE-IN-TARGET\"}]')\n")
    monkeypatch.chdir(target)
    # With Ghost Tools not installed the empty root has no ghost_buster and the scan fails (it must not fall
    # back to the target's). With it installed (`warden[ghost]`) the real Ghost answers. Either way the
    # fake in the target is never the one that ran.
    try:
        found = scan(target, ghost_tools_root=root)
    except RuntimeError:
        return
    assert "FAKE-IN-TARGET" not in [f.get("id") for f in found]
    assert not getattr(found, "version_unverified", False)


def test_a_run_started_inside_the_target_does_not_trust_a_fake_swizzle(tmp_path, monkeypatch):
    target, root = tmp_path / "target", tmp_path / "root"
    target.mkdir()
    root.mkdir()
    _repo(target)
    _fake_package(target, "swizzle", LIE)
    monkeypatch.chdir(target)
    result = TagTeam(drafter=FakeDrafter(), swizzle_root=root).run(
        target, findings=[], authorization=_auth(target, "documentation"))
    assert result.swizzle_sound is False and result.decision == "INCONCLUSIVE"
    assert _read(target, "NOTE.md") == "old\n"


@pytest.mark.parametrize("actor", ["judge", "Assay", "DRAFTER", "burnish", "ghost", "swizzle",
                                   "ghost_tools", "The Warden", "the warden", "warden-bot"])
def test_no_part_of_the_stack_authorizes_a_change_to_wardens_own_tree(tmp_path, actor):
    (tmp_path / "warden").mkdir()
    (tmp_path / "warden" / "authorization.py").write_text("x = 1\n", encoding="utf-8")
    try:
        auth = grant(actor, "transform", str(tmp_path.resolve()), "code", "self")
    except Unauthorized:
        return  # refused already at the grant
    with pytest.raises(Unauthorized):
        TagTeam(drafter=FakeDrafter()).run(tmp_path, findings=[], authorization=auth)


# -- 2. no edits inside version control, environments or caches -------------------------------

class Proposes:
    """Proposes one edit, citing nothing."""

    def __init__(self, edit: FileEdit):
        self.edit = edit

    def propose(self, target, observed, baseline):
        return Transformation(
            target=str(Path(target).resolve()), intent="x", architectural_reason="x", affected_files=(self.edit.path,),
            expected_behavior="x", preservation_requirements=(), known_defects=(), transformation_scope="code",
            baseline_reference=baseline, evidence=(), edits=(self.edit,), status=TransformationStatus.PROPOSED)


@pytest.mark.parametrize("rel", [".git/hooks/pre-commit", ".git/config", "venv/lib/x.py", ".venv/x.py",
                                 "node_modules/a/index.js", "pkg/__pycache__/x.py", "env/a.py", ".tox/a.py",
                                 "site-packages/a.py", ".mypy_cache/a.json", ".hg/hgrc", ".svn/entries",
                                 ".eggs/a.py", ".pytest_cache/a", "A/.GIT/hooks/post-commit"])
def test_a_proposal_inside_a_forbidden_directory_is_refused_as_an_escape(tmp_path, rel):
    _repo(tmp_path)
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    result = TagTeam(drafter=Proposes(FileEdit(rel, "write", "#!/bin/sh\necho pwned\n", ""))).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and any("version control, an environment or a cache" in n for n in result.notes)
    assert not (tmp_path / rel).exists()


def test_a_link_into_the_git_directory_is_an_escape_too(tmp_path):
    _repo(tmp_path)
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / "shortcut").symlink_to(tmp_path / ".git")
    result = TagTeam(drafter=Proposes(FileEdit("shortcut/hooks/pre-commit", "write", "echo hi\n", ""))).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and not (tmp_path / ".git" / "hooks" / "pre-commit").exists()


def test_a_finisher_cannot_write_a_hook_either(tmp_path):
    _repo(tmp_path)
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    result = TagTeam(drafter=FakeDrafter(steps=()), finisher=FakeFinisher(path=".git/hooks/pre-commit", new_text="echo\n")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "FINISH_REJECTED" and not (tmp_path / ".git" / "hooks" / "pre-commit").exists()


def _git_tree(root: Path) -> Path:
    _repo(root)
    (root / ".git" / "hooks").mkdir(parents=True)
    (root / ".git" / "info").mkdir()
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (root / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\n", encoding="utf-8")
    return root


class WritesHook:
    def __init__(self, rel=".git/hooks/pre-commit", text="#!/bin/sh\necho pwned\n"):
        self.rel, self.text = rel, text

    def propose(self, target, observed, baseline):
        p = Path(target) / self.rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.text, encoding="utf-8")
        return None


@pytest.mark.parametrize("rel", [".git/hooks/pre-commit", ".git/hooks/pre-push", ".git/config", ".git/info/exclude"])
def test_a_drafter_that_writes_into_git_during_propose_is_caught_and_undone(tmp_path, rel):
    _git_tree(tmp_path)
    before = {p: (tmp_path / p).read_bytes() for p in (".git/config", ".git/hooks/pre-push")}
    result = TagTeam(drafter=WritesHook(rel)).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and any("changed the tree" in n for n in result.notes)
    assert not (tmp_path / ".git" / "hooks" / "pre-commit").exists()
    assert not (tmp_path / ".git" / "info" / "exclude").exists()
    for p, data in before.items():
        assert (tmp_path / p).read_bytes() == data


def test_watch_notices_a_removed_hook_and_a_seat_that_crashes_still_has_its_changes_undone(tmp_path):
    _git_tree(tmp_path)
    with pytest.raises(SeatBrokeCharter):
        with watch(tmp_path, "A seat"):
            (tmp_path / ".git" / "hooks" / "pre-push").unlink()
    assert (tmp_path / ".git" / "hooks" / "pre-push").read_text(encoding="utf-8") == "#!/bin/sh\n"
    with pytest.raises(ZeroDivisionError):
        with watch(tmp_path, "A seat"):
            (tmp_path / ".git" / "config").write_text("[evil]\n", encoding="utf-8")
            _ = 1 / 0
    assert (tmp_path / ".git" / "config").read_text(encoding="utf-8") == "[core]\n"


# -- 3. a run that does not end accepted leaves the tree as found -------------------------------

def _tree_state(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def test_a_suite_that_goes_red_in_a_later_cycle_puts_the_earlier_edits_back(tmp_path):
    counter = tmp_path / "counter.txt"
    target = tmp_path / "t"
    target.mkdir()
    _repo(target, f"    p = {str(counter)!r}\n    import os\n"
                  "    n = int(open(p).read()) + 1 if os.path.exists(p) else 1\n"
                  "    open(p, 'w').write(str(n))\n    assert n <= 2\n")
    before = _tree_state(target)
    result = TagTeam(drafter=FakeDrafter(steps=("one\n", "two\n"))).run(
        target, findings=[], authorization=_auth(target, "documentation"))
    assert result.decision == "INCONCLUSIVE"
    assert _tree_state(target) == before
    assert result.cycles[0].outcome == "APPLIED" and result.cycles[0].proposal is not None
    assert "The tree was put back as it was found because the run did not finish accepted." in result.notes
    assert result.put_back and not result.applied


def test_a_later_cycle_that_fails_puts_the_earlier_edits_back(tmp_path):
    _repo(tmp_path)
    before = _tree_state(tmp_path)
    drafter = FakeDrafter(steps=("one\n", "VALUE = 2\n"))
    drafter.path = "NOTE.md"
    calls = {"n": 0}
    real = drafter.propose

    def propose(target, observed, baseline):
        calls["n"] += 1
        if calls["n"] == 2:
            drafter.path = "pkg/__init__.py"
        return real(target, observed, baseline)

    drafter.propose = propose
    result = TagTeam(drafter=drafter).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and _tree_state(tmp_path) == before
    assert any("put back as it was found" in n for n in result.notes)


def test_not_converged_puts_everything_back(tmp_path):
    _repo(tmp_path)
    before = _tree_state(tmp_path)
    result = TagTeam(drafter=FakeDrafter(steps=[f"v{i}\n" for i in range(9)]), max_cycles=2).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    assert result.decision == "NOT_CONVERGED" and _tree_state(tmp_path) == before


def test_a_repeated_proposal_puts_everything_back(tmp_path):
    from fakes import StuckDrafter
    _repo(tmp_path)
    before = _tree_state(tmp_path)
    result = TagTeam(drafter=StuckDrafter()).run(tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    assert result.decision == "NOT_CONVERGED" and _tree_state(tmp_path) == before


def test_a_rejected_finish_puts_the_loop_edits_back_too(tmp_path):
    _repo(tmp_path)
    before = _tree_state(tmp_path)
    result = TagTeam(drafter=FakeDrafter(steps=("kept\n",)),
                     finisher=FakeFinisher(path="pkg/__init__.py", new_text="VALUE = 2\n")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "FINISH_REJECTED" and _tree_state(tmp_path) == before and result.put_back


def test_a_tree_too_large_to_restore_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    # Round 3: a tree that cannot be put back is never written to (it used to be written, and left changed).
    _repo(tmp_path)
    monkeypatch.setattr(guard, "_RESTORE_LIMIT", 10)
    drafter = FakeDrafter(steps=[f"v{i}\n" for i in range(9)])
    result = TagTeam(drafter=drafter, max_cycles=2).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    assert result.decision == "INCONCLUSIVE" and drafter.calls == 0
    assert "more than Warden can put back" in result.reason
    assert _read(tmp_path, "NOTE.md") == "old\n"


class Boom:
    def propose(self, target, observed, baseline):
        raise RuntimeError("secret internals")


class BoomLater:
    def __init__(self):
        self.n = 0

    def propose(self, target, observed, baseline):
        self.n += 1
        if self.n == 2:
            raise ValueError("late")
        return FakeDrafter(steps=("one\n",)).propose(target, observed, baseline)


class WrongProposal:
    def propose(self, target, observed, baseline):
        return {"edits": []}


class BoomFinisher:
    def finish(self, target, baseline, facts):
        raise KeyError("x")


class WrongFinisher:
    def finish(self, target, baseline, facts):
        return {"not": "a proposal"}


@pytest.mark.parametrize("drafter,finisher,seat,kind", [
    (Boom(), None, "The Drafter", "RuntimeError"),
    (BoomLater(), None, "The Drafter", "ValueError"),
    (WrongProposal(), None, "The Drafter", "WrongAnswer"),
    (FakeDrafter(steps=("one\n",)), BoomFinisher(), "The Finisher", "KeyError"),
    (FakeDrafter(steps=("one\n",)), WrongFinisher(), "The Finisher", "WrongAnswer"),
])
def test_a_seat_that_fails_ends_the_run_with_a_plain_note_and_the_tree_put_back(tmp_path, drafter, finisher, seat, kind):
    _repo(tmp_path)
    before = _tree_state(tmp_path)
    result = TagTeam(drafter=drafter, finisher=finisher).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    assert result.decision == "ERROR" and _tree_state(tmp_path) == before
    text = " ".join(result.notes)
    assert seat in text and kind in text and "Traceback" not in text and "secret internals" not in text


@pytest.mark.parametrize("answer", [None, {"decision": "ACCEPT", "reasons": []}, "ACCEPT", 7])
def test_a_judge_that_returns_the_wrong_type_is_an_error_not_an_accept(tmp_path, measured, answer):
    _repo(tmp_path)

    class Judge:
        def decide(self, evidence):
            return answer

    before = _tree_state(tmp_path)
    result = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=Judge(), ghost_tools_root=Path("."),
                     swizzle_root=Path("."), assay_root=Path(".")).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "documentation"))
    assert result.decision == "ERROR" and _tree_state(tmp_path) == before
    assert any("The Judge" in n for n in result.notes)


def test_ghost_garbage_stops_the_run_without_a_crash(tmp_path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter()).run(tmp_path, findings=["not a finding", 3],
                                                 authorization=_auth(tmp_path, "documentation"))
    assert result.decision == "INCONCLUSIVE" and _read(tmp_path, "NOTE.md") == "old\n"


# CLI: always valid JSON, and a seat's print() cannot corrupt it.

def _seat_module(directory: Path, body: str) -> None:
    directory.mkdir(exist_ok=True)
    (directory / "noisy_seat.py").write_text(body, encoding="utf-8")


def _cli(tmp_path, monkeypatch, capsys, body: str, extra=()):
    target = _repo(tmp_path / "t") if (tmp_path / "t").mkdir() is None else None
    _seat_module(tmp_path / "seats", body)
    monkeypatch.syspath_prepend(str(tmp_path / "seats"))
    sys.modules.pop("noisy_seat", None)
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")
    code = main(["tagteam", str(target), "--drafter", "noisy_seat:Seat", "--from-ghost", str(findings),
                 "--authorize", "william", "--reason", "cli test", *extra])
    return code, capsys.readouterr(), target


def test_a_seat_that_prints_cannot_corrupt_the_json(tmp_path, monkeypatch, capsys):
    code, out, _ = _cli(tmp_path, monkeypatch, capsys,
                        "class Seat:\n    requires_contract = \"1\"\n    def propose(self, target, observed, baseline):\n"
                        "        print('hello from the seat')\n        return None\n")
    payload = json.loads(out.out)
    assert payload["decision"] == "ACCEPT_UNVERIFIED" and code == 3
    assert "hello from the seat" in out.err and "hello" not in out.out


def test_a_seat_that_crashes_gives_json_and_a_nonzero_exit(tmp_path, monkeypatch, capsys):
    code, out, target = _cli(tmp_path, monkeypatch, capsys,
                             "class Seat:\n    requires_contract = \"1\"\n    def propose(self, target, observed, baseline):\n"
                             "        raise RuntimeError('boom')\n")
    payload = json.loads(out.out)
    assert payload["decision"] == "ERROR" and code == 4 and "Traceback" not in out.out
    assert any("The Drafter" in n and "RuntimeError" in n for n in payload["notes"])


def test_a_seat_that_will_not_load_still_gives_json(tmp_path, monkeypatch, capsys):
    code, out, _ = _cli(tmp_path, monkeypatch, capsys, "raise ImportError('nope')\n")
    # The label is now SEAT_NOT_LOADED (exit 2); ERROR is exit 4 and means a seat failed while running.
    payload = json.loads(out.out)
    assert code == 2 and payload["decision"] == "SEAT_NOT_LOADED" and payload["reason"]


def test_a_bad_findings_file_gives_json(tmp_path, capsys):
    target = _repo(tmp_path / "t") if (tmp_path / "t").mkdir() is None else None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code = main(["tagteam", str(target), "--from-ghost", str(bad)])
    assert code == 4 and json.loads(capsys.readouterr().out)["decision"] == "ERROR"


# -- 4. Ghost ids cannot inject code ------------------------------------------------------------

def test_safe_id_keeps_only_plain_characters_on_one_line_and_caps_length():
    assert safe_id("ghost-ab12.c:d_e") == "ghost-ab12.c:d_e"
    assert safe_id("a\nimport os") == "a?import?os"
    assert "\n" not in safe_id("x\r\ny z") and len(safe_id("a" * 500)) == 64


def test_an_id_with_a_newline_cannot_put_live_code_in_the_target(tmp_path, monkeypatch):
    evil = "ghost-dead1\nimport os\nos.system('touch pwned')"
    finding = {"id": evil, "detector": "unused_code", "severity": "minor", "summary": "unused", "status": "confirmed"}
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "dead.py").write_text("def unused():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")

    def fake_scan(target, **kw):
        text = (Path(target) / "pkg" / "dead.py").read_text(encoding="utf-8")
        return () if "WARDEN COMMENTED OUT" in text else (finding,)

    monkeypatch.setattr(tagteam, "ghost_scan", fake_scan)
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    result = TagTeam(drafter=RemovingDrafter(cites=evil), ghost_tools_root=Path(".")).run(
        tmp_path, findings=[finding], authorization=_auth(tmp_path))
    keep_held(result, tmp_path)
    assert result.cycles[0].outcome == "APPLIED"
    text = _read(tmp_path, "pkg/dead.py")
    assert all(line.startswith("#") for line in text.splitlines() if line.strip())
    tree = ast.parse(text)
    assert not tree.body  # nothing live at all
    assert not (tmp_path / "pwned").exists()
    assert "import?os" in text


def test_an_id_with_a_newline_cannot_break_the_audit_table():
    from warden import audit
    out = audit.update("", [{"id": "ghost-1\n| X | y", "severity": "minor", "summary": "s"}])
    rows = [ln for ln in out.splitlines() if ln.startswith("| ") and "ghost-1" in ln]
    assert len(rows) == 1 and rows[0].endswith("` |")
