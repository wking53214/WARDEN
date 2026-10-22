"""`--stack DIR`: the whole circuit from one folder of checkouts, and the grant's scope told to the seats.

Before these, running the circuit meant naming six paths and three module specs by hand, and the
maker seats never learned the grant's scope: Burnish left code untidied under a `code` grant, and
a Drafter proposed code under a `documentation` grant only to have it declined.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.cli import main
from warden.tagteam import TagTeam

from fakes import FakeFinisher, FakeJudge

SEAT = '''
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.roles import Verdict


def _t(target, baseline, path, new):
    note = Path(target) / path
    old = note.read_text(encoding="utf-8") if note.is_file() else ""
    return Transformation(
        target=str(Path(target).resolve()), intent="stack test", architectural_reason="test",
        affected_files=(path,), expected_behavior="none", preservation_requirements=(),
        known_defects=(), transformation_scope="documentation", baseline_reference=baseline,
        evidence=(), edits=(FileEdit(path=path, kind="write", new=new, old=old),),
        status=TransformationStatus.PROPOSED)


class Drafter:
    requires_contract = "1"
    scope = None
    def __init__(self): self.done = False
    def propose(self, target, observed, baseline):
        if self.done: return None
        self.done = True
        return _t(target, baseline, "NOTE.md", f"scope={self.scope}\\n")


class Judge:
    requires_contract = "1"
    def decide(self, evidence): return Verdict("ACCEPT", ("ok",), "stack judge")


class Burnish:
    requires_contract = "1"
    scope = "documentation"
    def finish(self, target, baseline, facts):
        return _t(target, baseline, "README.md", f"finished under {self.scope}\\n")
'''

_MODULES = ("drafter", "drafter.seat", "judge", "judge.seat", "burnish", "burnish.finisher")


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                                encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "README.md").write_text("# d\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def _stack(root: Path, names=("GHOST_TOOLS", "Swizzle", "assay", "DRAFTER", "Judge", "burnish")) -> Path:
    """A folder of checkouts whose names differ in case from the canonical ones, each with a seat package."""
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        (root / name).mkdir()
    packages = {"drafter": "seat.py", "judge": "seat.py", "burnish": "finisher.py"}
    for name in names:
        module = packages.get(name.lower())
        if module:
            (root / name / name.lower()).mkdir()
            (root / name / name.lower() / "__init__.py").write_text("", encoding="utf-8")
            (root / name / name.lower() / module).write_text(SEAT, encoding="utf-8")
    return root


@pytest.fixture
def measured(monkeypatch):
    for m in _MODULES:
        sys.modules.pop(m, None)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))
    yield
    for m in _MODULES:
        sys.modules.pop(m, None)


def _run(capsys, *args):
    code = main(["tagteam", *map(str, args)])
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err


def test_the_stack_folder_must_exist(tmp_path, capsys):
    target = _repo(tmp_path / "t")
    code, payload, _ = _run(capsys, target, "--stack", tmp_path / "nowhere")
    assert code == 2 and payload["decision"] == "USAGE_ERROR" and "nowhere" in payload["reason"]


def test_a_stack_with_parts_missing_names_them_and_runs_nothing(tmp_path, capsys):
    target = _repo(tmp_path / "t")
    stack = _stack(tmp_path / "stack", names=("ghost_tools", "SWIZZLE"))
    code, payload, _ = _run(capsys, target, "--stack", stack, "--authorize", "william", "--reason", "r")
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert "assay, drafter, judge, burnish" in payload["reason"]
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_two_folders_differing_only_by_case_are_refused(tmp_path, capsys):
    target = _repo(tmp_path / "t")
    stack = _stack(tmp_path / "stack", names=("ghost_tools", "SWIZZLE", "assay", "DRAFTER", "Judge", "burnish",
                                                "Assay"))
    code, payload, _ = _run(capsys, target, "--stack", stack)
    assert code == 2 and "assay" in payload["reason"] and "differing only by case" in payload["reason"]


def test_the_stack_seats_everyone_with_names_matched_case_blind(tmp_path, capsys, measured):
    target = _repo(tmp_path / "t")
    stack = _stack(tmp_path / "stack")
    code, payload, err = _run(capsys, target, "--stack", stack, "--authorize", "william", "--reason", "r",
                              "--scope", "code")
    assert code == 0 and payload["decision"] == "ACCEPT", (payload["reason"], err)
    versions = payload["versions"]
    assert versions["ghost_tools"]["path"] == str(stack / "GHOST_TOOLS")
    assert versions["swizzle"]["path"] == str(stack / "Swizzle")
    assert versions["assay"]["path"] == str(stack / "assay")
    assert versions["seats"]["drafter"]["spec"] == "drafter.seat:Drafter"
    assert versions["seats"]["judge"]["spec"] == "judge.seat:Judge"
    assert versions["seats"]["finisher"]["spec"] == "burnish.finisher:Burnish"
    assert payload["verdict"]["judge"] == "stack judge"
    # The seats were told the grant's scope before they were asked.
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "scope=code\n"
    assert (target / "README.md").read_text(encoding="utf-8") == "finished under code\n"


def test_an_explicit_option_wins_over_the_stacks_copy(tmp_path, capsys, measured):
    target = _repo(tmp_path / "t")
    stack = _stack(tmp_path / "stack")
    other = tmp_path / "other_swizzle"
    other.mkdir()
    code, payload, _ = _run(capsys, target, "--stack", stack, "--swizzle-root", other,
                            "--authorize", "william", "--reason", "r")
    assert code == 0
    assert payload["versions"]["swizzle"]["path"] == str(other)
    assert payload["versions"]["ghost_tools"]["path"] == str(stack / "GHOST_TOOLS")


def test_a_seat_inside_the_target_is_still_refused_when_the_stack_names_it(tmp_path, capsys, measured):
    target = _repo(tmp_path / "t")
    stack = _stack(target / "vendored_stack")
    code, payload, _ = _run(capsys, target, "--stack", stack, "--authorize", "william", "--reason", "r")
    assert code == 2 and payload["decision"] == "SEAT_NOT_LOADED"
    assert "inside the folder being governed" in payload["reason"]


# -- the grant's scope reaches the seats, with or without --stack -----------------------------------

class ScopedDrafter:
    requires_contract = "1"

    def __init__(self):
        self.scope = None
        self.seen = []

    def propose(self, target, observed, baseline):
        self.seen.append(self.scope)
        return None


class Stubborn:
    """A Finisher whose scope is read-only."""
    requires_contract = "1"

    @property
    def scope(self):
        return "documentation"

    def finish(self, target, baseline, facts):
        return None


def _auth(root, scope):
    return grant("william", "transform", str(root.resolve()), scope, "scope test")


@pytest.mark.parametrize("scope", ["documentation", "code"])
def test_the_drafter_learns_the_grants_scope_before_its_first_call(tmp_path, measured, scope):
    _repo(tmp_path)
    drafter = ScopedDrafter()
    TagTeam(drafter=drafter, judge=FakeJudge()).run(tmp_path, findings=[], authorization=_auth(tmp_path, scope))
    assert drafter.seen == [scope]


def test_the_finisher_learns_the_grants_scope_too(tmp_path, measured):
    _repo(tmp_path)
    finisher = FakeFinisher()
    finisher.scope = "documentation"   # built with its own idea; the grant corrects it
    TagTeam(drafter=ScopedDrafter(), finisher=finisher, judge=FakeJudge()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "code"))
    assert finisher.scope == "code" and finisher.calls == 1


def test_a_seat_without_a_scope_attribute_is_left_alone(tmp_path, measured):
    _repo(tmp_path)
    finisher = FakeFinisher()
    TagTeam(drafter=ScopedDrafter(), finisher=finisher, judge=FakeJudge()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "code"))
    assert not hasattr(finisher, "scope") and finisher.calls == 1


def test_a_seat_that_will_not_take_the_scope_is_noted_not_crashed(tmp_path, measured):
    _repo(tmp_path)
    result = TagTeam(drafter=ScopedDrafter(), finisher=Stubborn(), judge=FakeJudge()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "code"))
    assert result.decision != "ERROR"
    assert any("The Finisher keeps a scope of its own" in n for n in result.notes)


class WritesWhenTold:
    """A Finisher whose `scope` setter touches the tree: the handoff is a seat call and must be guarded."""
    requires_contract = "1"

    def __init__(self):
        self.target = None

    @property
    def scope(self):
        return "documentation"

    @scope.setter
    def scope(self, value):
        (self.target / "planted.md").write_text("planted before Ghost looked\n", encoding="utf-8")

    def finish(self, target, baseline, facts):
        return None


def test_a_seat_that_writes_while_being_told_the_scope_is_refused_and_undone(tmp_path, measured):
    _repo(tmp_path)
    finisher = WritesWhenTold()
    finisher.target = tmp_path
    result = TagTeam(drafter=ScopedDrafter(), finisher=finisher, judge=FakeJudge()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path, "code"))
    assert result.decision == "REJECT" and "The Finisher changed the tree" in result.reason
    assert not (tmp_path / "planted.md").exists()


def test_without_a_grant_no_scope_is_told(tmp_path, measured):
    _repo(tmp_path)
    drafter = ScopedDrafter()
    result = TagTeam(drafter=drafter).run(tmp_path, findings=[])
    assert result.decision == "REFUSED" and drafter.seen == [None]


def _manifest(root: Path, repos: dict) -> Path:
    path = root / "stack.json"
    path.write_text(json.dumps({"schema": "warden-stack/1", "contract": "1", "repos": repos}), encoding="utf-8")
    return path


def _git_stack(root: Path) -> dict:
    """Make every checkout in a stack folder a git repository and return name -> commit."""
    from gitutil import commit_all, git
    out = {}
    for child in sorted(root.iterdir()):
        if child.is_dir():
            (child / "MARK.md").write_text(child.name + "\n", encoding="utf-8")
            commit_all(child, "seed")
            out[child.name] = git(child, "rev-parse", "HEAD").strip()
    return out


def test_a_join_inside_the_target_or_missing_is_a_usage_error(tmp_path, capsys, measured):
    target = _repo(tmp_path / "proj")
    stack = _stack(tmp_path / "stack")
    (target / "vendor").mkdir()
    code, payload, _ = _run(capsys, target, "--stack", stack, "--join", target / "vendor", "--authorize", "w",
                         "--reason", "r")
    assert code == 2 and payload["decision"] == "USAGE_ERROR" and "outside the target" in payload["reason"]
    code, payload, _ = _run(capsys, target, "--stack", stack, "--join", tmp_path / "nowhere", "--authorize", "w",
                         "--reason", "r")
    assert code == 2 and "does not exist" in payload["reason"]


def test_a_stack_manifest_pins_every_checkout_and_joins_all_but_the_target(tmp_path, capsys, measured, monkeypatch):
    target = _repo(tmp_path / "proj")
    stack = _stack(tmp_path / "stack")
    commits = _git_stack(stack)
    seen = {}

    def scan(t, **kw):
        seen["joins"] = tuple(kw.get("joins", ()))
        return ()
    monkeypatch.setattr(tagteam, "ghost_scan", scan)
    manifest = _manifest(tmp_path, {name: sha for name, sha in commits.items()})
    code, payload, _ = _run(capsys, target, "--stack", stack, "--stack-manifest", manifest, "--authorize", "w",
                         "--reason", "r")
    assert code in (0, 3), payload["reason"]
    assert {p.name for p in seen["joins"]} == set(commits)
    assert len(payload["versions"]["joins"]) == len(commits)
    assert all(j["commit"] for j in payload["versions"]["joins"])
    # the target itself, when listed, is governed and not joined
    stack2 = _stack(tmp_path / "stack2")
    commits2 = _git_stack(stack2)
    target2 = _repo(stack2 / "widget")
    from gitutil import commit_all, git
    commit_all(target2, "seed")
    commits2["widget"] = git(target2, "rev-parse", "HEAD").strip()
    manifest2 = _manifest(tmp_path / "stack2", commits2)
    code, payload, _ = _run(capsys, target2, "--stack", stack2, "--stack-manifest", manifest2, "--authorize", "w",
                         "--reason", "r")
    assert code in (0, 3), payload["reason"]
    assert "widget" not in {p.name for p in seen["joins"]} and len(seen["joins"]) == len(commits2) - 1
    # a clone of the target at the same commit, governed from outside the stack, is the same repository.
    # (The run above changed stack2/widget in place; a stack member is now vetted even when it is skipped as a join,
    # so put it back first.)
    git(target2, "reset", "--hard", "-q")
    git(target2, "clean", "-fdq")
    clone = tmp_path / "clone"
    import subprocess
    subprocess.run(["git", "clone", "-q", str(target2), str(clone)], check=True)
    code, payload, _ = _run(capsys, clone, "--stack", stack2, "--stack-manifest", manifest2, "--authorize", "w",
                            "--reason", "r")
    assert code in (0, 3), payload["reason"]
    assert "widget" not in {p.name for p in seen["joins"]} and len(seen["joins"]) == len(commits2) - 1


def test_a_stack_manifest_at_the_wrong_commit_or_wrong_shape_runs_nothing(tmp_path, capsys, measured):
    target = _repo(tmp_path / "proj")
    stack = _stack(tmp_path / "stack")
    commits = _git_stack(stack)
    wrong = dict(commits)
    first = sorted(wrong)[0]
    wrong[first] = "0" * 40
    code, payload, _ = _run(capsys, target, "--stack", stack, "--stack-manifest", _manifest(tmp_path, wrong),
                         "--authorize", "w", "--reason", "r")
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert first in payload["reason"] and "is at" in payload["reason"] and (target / "NOTE.md").read_text() == "old\n"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other", "repos": {}}), encoding="utf-8")
    code, payload, _ = _run(capsys, target, "--stack", stack, "--stack-manifest", bad, "--authorize", "w", "--reason", "r")
    assert code == 2 and "schema" in payload["reason"]
    code, payload, _ = _run(capsys, target, "--stack-manifest", bad, "--authorize", "w", "--reason", "r")
    assert code == 2 and "needs --stack" in payload["reason"]


@pytest.mark.parametrize("spelling, label", [
    (lambda sha: sha[:7], "a 7-character prefix"),
    (lambda sha: sha[:39], "a 39-character prefix"),
    (lambda sha: sha + "0", "41 characters"),
    (lambda sha: "z" * 40, "40 characters that are not hex"),
    (lambda sha: sha.upper(), "uppercase hex (git prints lowercase, and commits are compared as printed)"),
    (lambda sha: " " + sha[:39], "a padded pin"),
])
def test_a_manifest_pin_must_be_the_whole_commit_exactly(tmp_path, capsys, measured, spelling, label):
    target = _repo(tmp_path / "proj")
    stack = _stack(tmp_path / "stack")
    commits = _git_stack(stack)
    first = sorted(commits)[0]
    pins = dict(commits)
    pins[first] = spelling(commits[first])
    code, payload, _ = _run(capsys, target, "--stack", stack, "--stack-manifest", _manifest(tmp_path, pins),
                            "--authorize", "w", "--reason", "r")
    assert code == 2 and payload["decision"] == "USAGE_ERROR", label
    assert first in payload["reason"] and "full 40-character commit is required" in payload["reason"], label
    assert payload["reason"].endswith("Nothing was run."), label
    assert (target / "NOTE.md").read_text() == "old\n", label


def test_a_full_lowercase_pin_equal_to_the_checkout_is_accepted(tmp_path, capsys, measured, monkeypatch):
    target = _repo(tmp_path / "proj")
    stack = _stack(tmp_path / "stack")
    commits = _git_stack(stack)
    assert all(len(sha) == 40 for sha in commits.values())
    monkeypatch.setattr(tagteam, "ghost_scan", lambda t, **kw: ())
    code, payload, _ = _run(capsys, target, "--stack", stack, "--stack-manifest", _manifest(tmp_path, commits),
                            "--authorize", "w", "--reason", "r")
    assert code in (0, 3), payload["reason"]
    assert len(payload["versions"]["joins"]) == len(commits)


def _dirty_run(tmp_path, capsys, monkeypatch, dirty):
    """Run a manifest-joined stack in which `dirty(folder)` has changed one checkout; return (code, payload, folder)."""
    target = _repo(tmp_path / "proj")
    stack = _stack(tmp_path / "stack")
    for child in stack.iterdir():
        (child / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    commits = _git_stack(stack)
    victim = stack / sorted(commits)[0]
    dirty(victim)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda t, **kw: ())
    code, payload, _ = _run(capsys, target, "--stack", stack, "--stack-manifest", _manifest(tmp_path, commits),
                            "--authorize", "w", "--reason", "r")
    return code, payload, victim, target


def test_a_joined_checkout_with_a_modified_tracked_file_is_refused(tmp_path, capsys, measured, monkeypatch):
    code, payload, victim, target = _dirty_run(
        tmp_path, capsys, monkeypatch, lambda f: (f / "MARK.md").write_text("changed\n", encoding="utf-8"))
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert repr(str(victim)) in payload["reason"] and "1 path(s) are dirty" in payload["reason"]
    assert payload["reason"].endswith("Nothing was run.")
    assert (target / "NOTE.md").read_text() == "old\n"


def test_a_joined_checkout_with_an_untracked_file_is_refused_and_the_count_is_exact(tmp_path, capsys, measured,
                                                                                    monkeypatch):
    def dirty(folder):
        (folder / "stray.txt").write_text("x\n", encoding="utf-8")
        (folder / "MARK.md").write_text("changed\n", encoding="utf-8")
    code, payload, victim, target = _dirty_run(tmp_path, capsys, monkeypatch, dirty)
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert repr(str(victim)) in payload["reason"] and "2 path(s) are dirty" in payload["reason"]
    assert payload["reason"].endswith("Nothing was run.")
    assert (target / "NOTE.md").read_text() == "old\n"
    code, payload, victim, _ = _dirty_run(
        tmp_path / "again", capsys, monkeypatch, lambda f: (f / "stray.txt").write_text("x\n", encoding="utf-8"))
    assert code == 2 and "1 path(s) are dirty" in payload["reason"]


def test_a_joined_checkout_with_only_ignored_files_is_accepted(tmp_path, capsys, measured, monkeypatch):
    def dirty(folder):
        (folder / "__pycache__").mkdir()
        (folder / "__pycache__" / "x.pyc").write_text("compiled\n", encoding="utf-8")
    code, payload, victim, _ = _dirty_run(tmp_path, capsys, monkeypatch, dirty)
    assert code in (0, 3), payload["reason"]
    assert len(payload["versions"]["joins"]) == 6


def test_a_clean_stack_is_still_joined(tmp_path, capsys, measured, monkeypatch):
    code, payload, _, _ = _dirty_run(tmp_path, capsys, monkeypatch, lambda folder: None)
    assert code in (0, 3), payload["reason"]
    assert len(payload["versions"]["joins"]) == 6


def test_the_governed_target_is_not_asked_whether_it_is_dirty_as_a_join(tmp_path, measured):
    """The target is excluded from the joins; its own dirty policy (REFUSED, in TagTeam) applies to it instead."""
    from gitutil import commit_all, git
    from warden.cli import _joins_from_manifest
    stack = _stack(tmp_path / "stack")
    commits = _git_stack(stack)
    target = _repo(stack / "widget")
    commit_all(target, "seed")
    commits["widget"] = git(target, "rev-parse", "HEAD").strip()
    (target / "NOTE.md").write_text("edited by the owner\n", encoding="utf-8")
    manifest = _manifest(tmp_path, commits)
    joins, problem = _joins_from_manifest(manifest, stack, target)
    assert problem == "" and "widget" not in {p.name for p in joins} and len(joins) == len(commits) - 1


def test_cns_is_the_manifest_from_the_hub(tmp_path, capsys, measured, monkeypatch):
    target = _repo(tmp_path / "proj")
    stack = _stack(tmp_path / "stack")
    commits = _git_stack(stack)
    cns = tmp_path / "cns"
    (cns / "contracts").mkdir(parents=True)
    _manifest(cns / "contracts", commits).rename(cns / "contracts" / "warden-stack.json")
    seen = {}

    def scan(t, **kw):
        seen["joins"] = tuple(kw.get("joins", ()))
        return ()
    monkeypatch.setattr(tagteam, "ghost_scan", scan)
    code, payload, _ = _run(capsys, target, "--stack", stack, "--cns", cns, "--authorize", "w", "--reason", "r")
    assert code in (0, 3), payload["reason"]
    assert {p.name for p in seen["joins"]} == set(commits)
    code, payload, _ = _run(capsys, target, "--stack", stack, "--cns", tmp_path / "not-cns", "--authorize", "w",
                            "--reason", "r")
    assert code == 2 and "no contracts/warden-stack.json" in payload["reason"]
    code, payload, _ = _run(capsys, target, "--stack", stack, "--cns", cns, "--stack-manifest",
                            cns / "contracts" / "warden-stack.json", "--authorize", "w", "--reason", "r")
    assert code == 2 and "give one" in payload["reason"]


# -- every stack folder the run uses is vetted, covered by the manifest or not -------------------------------

def _stack_run(tmp_path, capsys, monkeypatch, repos, dirty=None, extra=(), manifest=True):
    """A git stack run with a manifest naming only `repos` (a function of the full name->commit map); return
    (code, payload, target). `dirty(stack)` may change a checkout first."""
    target = _repo(tmp_path / "proj")
    stack = _stack(tmp_path / "stack")
    for child in stack.iterdir():
        (child / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    commits = _git_stack(stack)
    if dirty is not None:
        dirty(stack)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda t, **kw: ())
    args = ["--stack", stack, "--authorize", "w", "--reason", "r", *extra]
    if manifest:
        args += ["--stack-manifest", _manifest(tmp_path, repos(commits))]
    code, payload, _ = _run(capsys, target, *args)
    return code, payload, target, stack


def test_a_manifest_that_does_not_name_a_used_folder_runs_nothing(tmp_path, capsys, measured, monkeypatch):
    """A manifest naming only the Drafter used to leave the Judge seat and the instruments unchecked."""
    code, payload, target, stack = _stack_run(
        tmp_path, capsys, monkeypatch, lambda commits: {"DRAFTER": commits["DRAFTER"]},
        dirty=lambda stack: (stack / "Judge" / "judge" / "seat.py").write_text("# tampered\n", encoding="utf-8"))
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert "does not name" in payload["reason"] and "'judge' (the checkout at" in payload["reason"]
    assert "'ghost_tools'" in payload["reason"] and "'drafter'" not in payload["reason"]
    assert payload["reason"].endswith("Nothing was run.")
    assert (target / "NOTE.md").read_text() == "old\n"


def test_a_clean_but_uncovered_seat_is_refused_and_named(tmp_path, capsys, measured, monkeypatch):
    code, payload, target, stack = _stack_run(
        tmp_path, capsys, monkeypatch,
        lambda commits: {k: v for k, v in commits.items() if k != "Judge"})
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert "does not name 'judge' (the checkout at" in payload["reason"] and repr(str(stack / "Judge")) in payload["reason"]
    assert payload["reason"].endswith("Nothing was run.")
    assert (target / "NOTE.md").read_text() == "old\n"


def test_a_dirty_seat_is_refused_even_when_the_manifest_covers_it_and_the_commit_matches(tmp_path, capsys, measured,
                                                                                           monkeypatch):
    code, payload, target, stack = _stack_run(
        tmp_path, capsys, monkeypatch, lambda commits: commits,
        dirty=lambda stack: (stack / "Judge" / "judge" / "seat.py").write_text("# tampered\n", encoding="utf-8"))
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert repr(str(stack / "Judge")) in payload["reason"] and "1 path(s) are dirty" in payload["reason"]
    assert (target / "NOTE.md").read_text() == "old\n"


def test_a_folder_the_manifest_names_that_the_run_does_not_use_need_not_be_listed_for_it(tmp_path, capsys, measured,
                                                                                         monkeypatch):
    """An explicit option wins over the folder's copy, so the stack's own copy is not used and not required."""
    other = tmp_path / "other_swizzle"
    other.mkdir()
    code, payload, target, stack = _stack_run(
        tmp_path, capsys, monkeypatch, lambda commits: {k: v for k, v in commits.items() if k != "Swizzle"},
        extra=("--swizzle-root", other))
    assert code in (0, 3), payload["reason"]


def test_a_stack_without_a_manifest_refuses_a_dirty_folder_it_uses(tmp_path, capsys, measured, monkeypatch):
    code, payload, target, stack = _stack_run(
        tmp_path, capsys, monkeypatch, None, manifest=False,
        dirty=lambda stack: (stack / "burnish" / "burnish" / "finisher.py").write_text("# tampered\n",
                                                                                          encoding="utf-8"))
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert repr(str(stack / "burnish")) in payload["reason"] and payload["reason"].endswith("Nothing was run.")
    assert (target / "NOTE.md").read_text() == "old\n"


def test_a_stack_without_a_manifest_does_not_ask_a_folder_it_does_not_use(tmp_path, capsys, measured, monkeypatch):
    other = tmp_path / "other_swizzle"
    other.mkdir()
    code, payload, target, stack = _stack_run(
        tmp_path, capsys, monkeypatch, None, manifest=False, extra=("--swizzle-root", other),
        dirty=lambda stack: (stack / "Swizzle" / "stray.txt").write_text("x\n", encoding="utf-8"))
    assert code in (0, 3), payload["reason"]


def test_a_clean_git_stack_without_a_manifest_still_runs(tmp_path, capsys, measured, monkeypatch):
    code, payload, target, stack = _stack_run(tmp_path, capsys, monkeypatch, None, manifest=False)
    assert code in (0, 3), payload["reason"]


def test_a_clone_of_the_target_at_the_same_commit_is_skipped_as_a_join_but_still_vetted(tmp_path, capsys, measured,
                                                                                         monkeypatch):
    """The same-commit exemption used to skip the dirty check too, so a modified stack member that happened to be at
    the target's commit was never asked. Only the join is skipped."""
    import subprocess
    from gitutil import commit_all, git
    stack = _stack(tmp_path / "stack")
    commits = _git_stack(stack)
    member = _repo(stack / "widget")
    (member / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    commit_all(member, "seed")
    commits["widget"] = git(member, "rev-parse", "HEAD").strip()
    clone = tmp_path / "widget_clone"
    subprocess.run(["git", "clone", "-q", str(member), str(clone)], check=True)
    manifest = _manifest(tmp_path, commits)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda t, **kw: ())
    (member / "NOTE.md").write_text("tampered\n", encoding="utf-8")
    code, payload, _ = _run(capsys, clone, "--stack", stack, "--stack-manifest", manifest, "--authorize", "w",
                            "--reason", "r")
    assert code == 2 and payload["decision"] == "USAGE_ERROR"
    assert repr(str(member)) in payload["reason"] and "1 path(s) are dirty" in payload["reason"]
    assert payload["reason"].endswith("Nothing was run.")
    assert (clone / "NOTE.md").read_text() == "old\n"
    # put it back: the clean member is still not joined, as before
    git(member, "checkout", "--", ".")
    code, payload, _ = _run(capsys, clone, "--stack", stack, "--stack-manifest", manifest, "--authorize", "w",
                            "--reason", "r")
    assert code in (0, 3), payload["reason"]
    assert len(payload["versions"]["joins"]) == len(commits) - 1
