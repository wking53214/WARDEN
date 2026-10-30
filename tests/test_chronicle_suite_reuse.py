"""Opt-in suite reuse across runs, keyed by the chronicle: `--reuse-chronicle-suite` (default off, needs `--chronicle`).

At the first suite pass ("cycle 1 before") a run may take the result an earlier run recorded for the very same tree, when
that result is green and the environment key (Python, pytest and Warden versions, platform, suite runner, suite command)
is equal on every field. Anything else runs the suite. The chronicle is an ordinary unsigned file: these tests show what
the flag does with a file it is given, not that the file is true.
"""

import json
import subprocess
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden import chronicle, cli
from warden.authorization import grant
from warden.claimrow import claim_row
from warden.cli import main
from warden.suite import SuiteRun
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge

ENV = {"python_version": "cpython 3.12.3", "pytest_version": "9.2.0", "warden_version": "0.16.0",
       "platform": "linux-x86_64", "suite_runner": "pytest", "suite_command": "python -m pytest -q"}

_GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.org", "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> str:
    env = dict(_GIT_ENV, HOME=str(cwd))
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True, env=env)
    return done.stdout.strip()


# -- the library: what the run does with the lines it is given ---------------------------------------------------

def _repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


@pytest.fixture
def fakes(monkeypatch):
    """Every instrument reports fine; the suite is a green stand-in that counts how often it really ran; the
    environment key is a fixed one that a test can change."""
    calls: list[str] = []
    state = {"env": dict(ENV)}

    def fake_run_suite(target, python, timeout, runner):
        calls.append(str(target))
        return SuiteRun(ran=True, passed=1, exit_code=0)

    monkeypatch.setattr(tagteam, "run_suite", fake_run_suite)
    monkeypatch.setattr(tagteam, "suite_environment", lambda python, runner: dict(state["env"]))
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))
    calls_and_env = type("Fakes", (), {})()
    calls_and_env.calls, calls_and_env.state = calls, state
    return calls_and_env


def _auth(root: Path):
    return grant("william", "transform", str(root.resolve()), "documentation", "reuse across runs")


def _line(tree: str, run_id: str = "run_aaaaaaaaaaaa", **over) -> dict:
    """A chronicle line of an earlier run whose claimed tree is `tree`, with a green suite result recorded for it."""
    line = {"kind": "run", "when": "2026-10-30T10:00:00+00:00", "run_id": run_id, "claimed_tree_digest": tree,
            "held_tree_digest": "feedfacefeedface",
            "suite_trees": [{"tree_digest": tree, "when": "cycle 1 after", "green": True, "environment": dict(ENV),
                             "result": {"ran": True, "passed": 1, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0,
                                        "xpassed": 0, "exit_code": 0, "reason": ""}}]}
    line.update(over)
    return line


def _from_chronicle(result) -> list:
    """The passes that took their result from the chronicle (a pass that reuses an earlier pass of the same run names
    that pass's number instead)."""
    return [p["reused_from"] for p in result.suite_passes if isinstance(p["reused_from"], str)]


def _run(root: Path, entries, reuse: bool = True, **kw):
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=FakeJudge("INSUFFICIENT", ("hold it",)),
                   ghost_tools_root=Path("."), swizzle_root=Path("."), assay_root=Path("."),
                   chronicle_entries=entries, reuse_chronicle_suite=reuse, **kw)
    return team.run(root, findings=[], authorization=_auth(root))


def test_a_full_match_reuses_the_recorded_result_as_the_first_pass_and_says_so(tmp_path, fakes):
    _repo(tmp_path)
    base = tagteam._fingerprint(tmp_path)
    result = _run(tmp_path, [_line(base)])
    first = result.suite_passes[0]
    assert first["when"] == "cycle 1 before" and first["reused_from"] == "chronicle:run_aaaaaaaaaaaa"
    assert first["tree_digest"] == base and first["result"].passed == 1 and first["result"].green
    assert any(f"suite pass cycle 1 before: reused the result of chronicle run run_aaaaaaaaaaaa, tree digest {base} "
               "identical" in n for n in result.notes)
    assert result.suite_passes[1]["reused_from"] is None  # the changed tree was measured
    assert len(fakes.calls) == 1  # "cycle 1 after" only; the first pass was not run and the last reuses "after"
    row = claim_row(result, _auth(tmp_path))
    assert row["suite_before"]["reused_from"] == "chronicle:run_aaaaaaaaaaaa" and row["suite_before"]["pass"] == 1
    assert json.loads(json.dumps(row)) == row


def test_the_flag_is_off_by_default(tmp_path, fakes):
    _repo(tmp_path)
    base = tagteam._fingerprint(tmp_path)
    result = _run(tmp_path, [_line(base)], reuse=False)
    assert _from_chronicle(result) == []
    assert not any("chronicle run" in n for n in result.notes) and len(fakes.calls) == 2
    assert TagTeam().reuse_chronicle_suite is False


def test_a_run_with_reuse_ends_as_a_run_without_it_on_the_same_data(tmp_path, fakes):
    _repo(tmp_path)
    base = tagteam._fingerprint(tmp_path)
    with_reuse = _run(tmp_path, [_line(base)])
    without = _run(tmp_path, [_line(base)], reuse=False)
    assert with_reuse.decision == without.decision == "ACCEPT_UNVERIFIED"
    assert [c.outcome for c in with_reuse.cycles] == [c.outcome for c in without.cycles]
    assert with_reuse.unmeasured == without.unmeasured and with_reuse.reason == without.reason
    assert with_reuse.suite_before == without.suite_before and with_reuse.suite_after == without.suite_after
    assert with_reuse.put_back and without.put_back


@pytest.mark.parametrize("name,mutate", [
    ("another tree: neither digest is the base", lambda line, base: line.update(
        claimed_tree_digest="0" * 16, held_tree_digest="1" * 16)),
    ("no suite result recorded for the base tree", lambda line, base: line["suite_trees"][0].update(
        tree_digest="2" * 16)),
    ("the green flag is false", lambda line, base: line["suite_trees"][0].update(green=False)),
    ("a failure is recorded", lambda line, base: line["suite_trees"][0]["result"].update(failed=1)),
    ("an error is recorded", lambda line, base: line["suite_trees"][0]["result"].update(errors=1)),
    ("nothing passed", lambda line, base: line["suite_trees"][0]["result"].update(passed=0)),
    ("pytest exited non-zero", lambda line, base: line["suite_trees"][0]["result"].update(exit_code=1)),
    ("the suite did not run", lambda line, base: line["suite_trees"][0]["result"].update(ran=False)),
    ("a line from before these fields existed", lambda line, base: (line.pop("suite_trees"), line.pop("run_id"))),
    ("no environment key", lambda line, base: line["suite_trees"][0].pop("environment")),
    ("a line that is not a run", lambda line, base: line.update(kind="keep")),
] + [
    (f"the {field} differs", lambda line, base, field=field: line["suite_trees"][0]["environment"].update(
        {field: "other"})) for field in chronicle.ENVIRONMENT_FIELDS
] + [
    (f"the {field} is missing", lambda line, base, field=field: line["suite_trees"][0]["environment"].pop(field))
    for field in chronicle.ENVIRONMENT_FIELDS
])
def test_nothing_is_reused_when_the_tree_the_result_or_the_environment_differs(tmp_path, fakes, name, mutate):
    _repo(tmp_path)
    base = tagteam._fingerprint(tmp_path)
    line = _line(base)
    mutate(line, base)
    result = _run(tmp_path, [line])
    assert _from_chronicle(result) == [], name
    assert len(fakes.calls) == 2, name  # the suite really ran at the first pass and after the change
    assert any("no chronicle run recorded a green result" in n for n in result.notes), name
    assert result.decision == "ACCEPT_UNVERIFIED"


def test_this_runs_environment_differing_from_the_recorded_one_runs_the_suite(tmp_path, fakes):
    _repo(tmp_path)
    base = tagteam._fingerprint(tmp_path)
    fakes.state["env"]["pytest_version"] = "9.3.0"
    result = _run(tmp_path, [_line(base)])
    assert result.suite_passes[0]["reused_from"] is None and len(fakes.calls) == 2


def test_an_environment_that_cannot_be_told_is_never_matched(tmp_path, fakes, monkeypatch):
    _repo(tmp_path)
    base = tagteam._fingerprint(tmp_path)
    monkeypatch.setattr(tagteam, "suite_environment", lambda python, runner: None)
    result = _run(tmp_path, [_line(base)])
    assert result.suite_passes[0]["reused_from"] is None and len(fakes.calls) == 2


def test_a_cargo_runner_is_never_reused(tmp_path, fakes, monkeypatch):
    """Cargo's toolchain is not part of the key, so a Cargo suite is always run."""
    from warden import suite
    _repo(tmp_path)
    base = tagteam._fingerprint(tmp_path)
    monkeypatch.setattr(tagteam, "suite_environment", suite.suite_environment)
    result = _run(tmp_path, [_line(base)], suite_runner="cargo")
    assert result.suite_passes[0]["reused_from"] is None and len(fakes.calls) == 2


def test_a_red_record_for_the_same_tree_and_environment_blocks_reuse_even_beside_a_green_one(tmp_path, fakes):
    _repo(tmp_path)
    base = tagteam._fingerprint(tmp_path)
    red = _line(base, run_id="run_bbbbbbbbbbbb")
    red["suite_trees"][0].update(green=False)
    red["suite_trees"][0]["result"].update(failed=2)
    for lines in ([_line(base), red], [red, _line(base)]):
        assert chronicle.reusable_suite(lines, base, ENV) is None
    result = _run(tmp_path, [_line(base), red])
    assert result.suite_passes[0]["reused_from"] is None


def test_the_newest_matching_green_line_is_the_one_named(tmp_path):
    base = "abcdabcdabcdabcd"
    older, newer = _line(base, run_id="run_000000000001"), _line(base, run_id="run_000000000002")
    found = chronicle.reusable_suite([older, newer], base, ENV)
    assert found is not None and found[0] == "run_000000000002" and found[1]["passed"] == 1
    assert chronicle.reusable_suite([older], "ffff" * 4, ENV) is None
    assert chronicle.reusable_suite([older], base, None) is None


def test_a_line_matches_by_its_held_tree_as_well_as_its_claimed_tree(tmp_path):
    base = "abcdabcdabcdabcd"
    line = _line("1234123412341234", held_tree_digest=base)
    line["suite_trees"][0]["tree_digest"] = base
    assert chronicle.reusable_suite([line], base, ENV) == ("run_aaaaaaaaaaaa", line["suite_trees"][0]["result"])


def test_only_the_passes_that_really_ran_the_suite_are_written_to_the_line():
    ok = SuiteRun(ran=True, passed=3, exit_code=0)
    red = SuiteRun(ran=True, passed=2, failed=1, exit_code=1)
    passes = [
        {"pass": 1, "when": "cycle 1 before", "tree_digest": "aa", "reused_from": None, "result": ok, "environment": ENV},
        {"pass": 2, "when": "cycle 1 after", "tree_digest": "bb", "reused_from": None, "result": red, "environment": ENV},
        {"pass": 3, "when": "converged", "tree_digest": "bb", "reused_from": 2, "result": red, "environment": ENV},
        {"pass": 4, "when": "x", "tree_digest": "cc", "reused_from": None, "result": ok, "environment": None},
        {"pass": 5, "when": "y", "tree_digest": "dd", "reused_from": "chronicle:run_z", "result": ok, "environment": ENV},
        {"pass": 6, "when": "z", "tree_digest": "ee", "reused_from": None, "result": SuiteRun(ran=False, reason="x"),
         "environment": ENV},
    ]
    trees = chronicle.suite_trees(passes)
    assert [(t["tree_digest"], t["green"]) for t in trees] == [("aa", True), ("bb", False)]
    assert trees[0]["environment"] == ENV and trees[0]["result"]["passed"] == 3
    assert json.loads(json.dumps(trees)) == trees


def test_a_result_taken_from_the_chronicle_cannot_settle_the_chronicles_own_promise():
    line = _line("abcdabcdabcdabcd")
    line["promises"] = [{"promise": "suite_green", "expect": {"passed": 1, "failed": 0, "errors": 0}}]
    measured = {"ran": True, "passed": 1, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    fresh = chronicle.settle([line], "abcdabcdabcdabcd", dict(measured, reused_from=None), [], [])
    taken = chronicle.settle([line], "abcdabcdabcdabcd", dict(measured, reused_from="chronicle:run_aaaaaaaaaaaa"), [], [])
    assert [s["status"] for s in fresh] == ["HELD"] and [s["status"] for s in taken] == ["OPEN"]
    assert "reused from the chronicle" in taken[0]["measurement"]


# -- the command line -------------------------------------------------------------------------------------------

def _two_commits(root: Path) -> tuple[str, str, str]:
    _repo(root)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "NOTE.md").write_text("one\n", encoding="utf-8")
    _git(root, "commit", "-q", "-a", "-m", "Step 1: one")
    first = _git(root, "rev-parse", "HEAD")
    (root / "NOTE.md").write_text("two\n", encoding="utf-8")
    _git(root, "commit", "-q", "-a", "-m", "Step 2: two")
    second = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", base)
    return base, first, second


def _tagteam(monkeypatch, tmp_path, capsys, target: Path, commit: str, chron: Path, *extra: str):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / "state"))
    code = main(["tagteam", str(target), "--claim-commit", commit, "--authorize", "william", "--reason", "reuse",
                 "--scope", "code", "--chronicle", str(chron), *extra])
    return code, json.loads(capsys.readouterr().out)


def test_two_consecutive_commits_the_second_run_takes_the_firsts_result_for_its_base_tree(tmp_path, monkeypatch, capsys):
    target = tmp_path / "t"
    target.mkdir()
    base, first, second = _two_commits(target)
    chron = tmp_path / "chron"
    code1, one = _tagteam(monkeypatch, tmp_path, capsys, target, first, chron)
    assert code1 == 3 and one["decision"] == "ACCEPT_UNVERIFIED" and all(
        p["reused_from"] is None for p in one["suite_passes"])
    lines = [json.loads(x) for f in chron.glob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["run_id"].startswith("run_") and lines[0]["suite_trees"]
    assert lines[0]["suite_trees"][0]["environment"]["suite_runner"] == "pytest"
    assert {t["tree_digest"] for t in lines[0]["suite_trees"]} >= {lines[0]["claimed_tree_digest"]}

    _git(target, "checkout", "-q", first)  # the base of the second commit is the first run's claimed tree
    code2, two = _tagteam(monkeypatch, tmp_path, capsys, target, second, chron, "--reuse-chronicle-suite")
    assert code2 == 3 and two["decision"] == "ACCEPT_UNVERIFIED", two["reason"]
    reused = two["suite_passes"][0]
    assert reused["when"] == "cycle 1 before" and reused["reused_from"] == f"chronicle:{lines[0]['run_id']}"
    assert reused["tree_digest"] == lines[0]["claimed_tree_digest"] and reused["passed"] == 1
    assert two["claim"]["suite_before"]["reused_from"] == reused["reused_from"]
    assert any(f"suite pass cycle 1 before: reused the result of chronicle run {lines[0]['run_id']}, tree digest "
               f"{reused['tree_digest']} identical" in n for n in two["notes"])

    # The same run without the flag, on the same data: the same decision and cycles, the suite really run.
    code3, three = _tagteam(monkeypatch, tmp_path, capsys, target, second, chron)
    assert (code3, three["decision"]) == (code2, two["decision"])
    assert [c["outcome"] for c in three["cycles"]] == [c["outcome"] for c in two["cycles"]]
    assert three["suite_passes"][0]["reused_from"] is None
    assert three["claim"]["suite_after"]["passed"] == two["claim"]["suite_after"]["passed"]
    assert not any("chronicle run" in n and "reused the result" in n for n in three["notes"])


def test_a_run_on_another_commit_does_not_reuse_the_result(tmp_path, monkeypatch, capsys):
    target = tmp_path / "t"
    target.mkdir()
    base, first, second = _two_commits(target)
    chron = tmp_path / "chron"
    _tagteam(monkeypatch, tmp_path, capsys, target, first, chron)
    # Still at the base, claiming commit 1 again: this run's base tree is the first run's base tree, which no line holds
    # as its claimed or held tree.
    code, again = _tagteam(monkeypatch, tmp_path, capsys, target, first, chron, "--reuse-chronicle-suite")
    assert again["suite_passes"][0]["reused_from"] is None
    assert any("no chronicle run recorded a green result" in n for n in again["notes"])


def test_the_flag_without_a_chronicle_is_a_usage_error(tmp_path, capsys):
    _two_commits(tmp_path)
    code = main(["tagteam", str(tmp_path), "--claim-commit", "HEAD", "--authorize", "william", "--reason", "t",
                 "--reuse-chronicle-suite"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["decision"] == "USAGE_ERROR" and "needs --chronicle" in out["reason"]
    assert "Nothing was run" in out["reason"]
    code = main(["tagteam", str(tmp_path), "--chronicle", str(tmp_path / "c"), "--reuse-chronicle-suite",
                 "--suite-always"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and "contradict" in out["reason"]


def test_the_flag_reaches_the_run_and_is_off_unless_given(tmp_path, monkeypatch, capsys):
    seen = {}

    def spy(args, *rest, **kw):
        seen["reuse"] = args.reuse_chronicle_suite
        return 0

    monkeypatch.setattr(cli, "_run_team", spy)
    assert cli.main(["tagteam", str(tmp_path)]) == 0 and seen["reuse"] is False
    assert cli.main(["tagteam", str(tmp_path), "--chronicle", str(tmp_path / "c"), "--reuse-chronicle-suite"]) == 0
    assert seen["reuse"] is True
    capsys.readouterr()


def test_a_line_written_by_this_run_carries_the_environment_key_for_every_measured_tree(tmp_path, monkeypatch, capsys):
    target = tmp_path / "t"
    target.mkdir()
    base, first, second = _two_commits(target)
    chron = tmp_path / "chron"
    _tagteam(monkeypatch, tmp_path, capsys, target, first, chron)
    line = json.loads(next(iter(chron.glob("*.jsonl"))).read_text(encoding="utf-8").splitlines()[0])
    assert all(set(t["environment"]) == set(chronicle.ENVIRONMENT_FIELDS) for t in line["suite_trees"])
    assert all(t["green"] is True and t["result"]["passed"] == 1 for t in line["suite_trees"])
