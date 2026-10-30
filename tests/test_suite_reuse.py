"""Suite reuse within one run: a pass on a tree whose fingerprint this run already measured reuses that result.

On a run with one applied change and one finishing edit the suite used to run six times on three distinct trees
(before, after, converged, finisher before, finisher after, final state for the Judge); passes 3, 4 and 6 measured
bytes already measured. Now each pass fingerprints the tree first and reuses the earlier result when the digest was
seen in this run, says so in the notes and in `suite_passes` (`reused_from`), and `--suite-always` turns it off.
Reuse never reaches across runs.
"""

import json
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden import cli
from warden.authorization import grant
from warden.cli import main
from warden.suite import SuiteRun
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeFinisher, FakeJudge

SEATS = '''
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus


def _t(target, baseline, path, new):
    old = (Path(target) / path).read_text(encoding="utf-8") if (Path(target) / path).is_file() else ""
    return Transformation(
        target=str(Path(target).resolve()), intent="t", architectural_reason="t", affected_files=(path,),
        expected_behavior="none", preservation_requirements=(), known_defects=(), transformation_scope="documentation",
        baseline_reference=baseline, evidence=(), edits=(FileEdit(path=path, kind="write", new=new, old=old),),
        status=TransformationStatus.PROPOSED)


class Once:
    requires_contract = "1"
    def __init__(self): self.done = False
    def propose(self, target, observed, baseline):
        if self.done: return None
        self.done = True
        return _t(target, baseline, "NOTE.md", "changed\\n")


class Finisher:
    requires_contract = "1"
    def finish(self, target, baseline, facts):
        return _t(target, baseline, "README.md", "final\\n")
'''


def _repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "NOTE.md").write_text("old\n", encoding="utf-8")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


@pytest.fixture
def counted(monkeypatch):
    """Every instrument reports fine, and the suite is a green stand-in that counts how often it really ran."""
    calls = []

    def fake_run_suite(target, python, timeout, runner):
        calls.append(str(target))
        return SuiteRun(ran=True, passed=1, exit_code=0)

    monkeypatch.setattr(tagteam, "run_suite", fake_run_suite)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score",
                        lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks",
                        lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))
    return calls


def _auth(root):
    return grant("william", "transform", str(root.resolve()), "documentation", "reuse test")


def _team(**kw):
    return TagTeam(drafter=kw.pop("drafter", FakeDrafter(steps=("new\n",))), judge=FakeJudge(),
                   finisher=kw.pop("finisher", FakeFinisher(path="README.md", new_text="final\n")),
                   ghost_tools_root=Path("."), swizzle_root=Path("."), assay_root=Path("."), **kw)


def test_six_passes_become_three_when_the_trees_are_identical(tmp_path, counted):
    _repo(tmp_path)
    result = _team().run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "ACCEPT"
    assert [p["when"] for p in result.suite_passes] == [
        "cycle 1 before", "cycle 1 after", "converged", "cycle 0 before", "cycle 0 after", "final state, for the Judge"]
    assert [p["reused_from"] for p in result.suite_passes] == [None, None, 2, 2, None, 5]
    assert len(counted) == 3
    digests = [p["tree_digest"] for p in result.suite_passes]
    assert digests[1] == digests[2] == digests[3] and digests[4] == digests[5] and len(set(digests)) == 3
    assert result.suite_passes[2]["result"] is result.suite_passes[1]["result"]
    assert any(f"suite pass converged: reused the result of pass 2, tree digest {digests[1]} identical" in n
               for n in result.notes)


def test_a_one_byte_change_is_measured_again(tmp_path, counted):
    _repo(tmp_path)
    result = _team(drafter=FakeDrafter(steps=("new\n", "new!\n")), finisher=None).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    whens = [p["when"] for p in result.suite_passes]
    assert whens[:4] == ["cycle 1 before", "cycle 1 after", "cycle 2 before", "cycle 2 after"]
    reused = [p["reused_from"] for p in result.suite_passes]
    assert reused[:4] == [None, None, 2, None]
    assert result.suite_passes[1]["tree_digest"] != result.suite_passes[3]["tree_digest"]
    assert len(counted) == 3  # base, "new", "new!"; the second before-pass reused the first after-pass


def test_the_opt_out_runs_every_pass(tmp_path, counted):
    _repo(tmp_path)
    result = _team(suite_always=True).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert len(result.suite_passes) == 6 and all(p["reused_from"] is None for p in result.suite_passes)
    assert len(counted) == 6 and not any("reused the result" in n for n in result.notes)


def test_reuse_never_reaches_across_runs(tmp_path, counted):
    _repo(tmp_path)
    team = _team(finisher=None)
    team.run(tmp_path, findings=[], authorization=_auth(tmp_path))
    first = len(counted)
    (tmp_path / "NOTE.md").write_text("old\n", encoding="utf-8")  # back to the same bytes as the first run's base
    team.drafter = FakeDrafter(steps=("new\n",))
    result = team.run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.suite_passes[0]["reused_from"] is None and len(counted) > first


def test_the_record_and_the_row_say_which_pass_was_reused(tmp_path, monkeypatch, counted, capsys):
    (tmp_path / "t").mkdir()
    target = _repo(tmp_path / "t")
    seats = tmp_path / "seats"
    seats.mkdir()
    (seats / "reuse_seats.py").write_text(SEATS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(seats))
    code = main(["tagteam", str(target), "--drafter", "reuse_seats:Once", "--finisher", "reuse_seats:Finisher",
                 "--authorize", "william", "--reason", "reuse", "--from-ghost", str(_findings(tmp_path))])
    payload = json.loads(capsys.readouterr().out)
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED", payload["reason"]
    passes = payload["suite_passes"]
    assert [p["reused_from"] for p in passes] == [None, None, 2, 2, None] and passes[2]["passed"] == 1
    assert {"pass", "when", "tree_digest", "reused_from", "ran", "passed", "failed"} <= set(passes[0])
    assert payload["claim"]["suite_before"]["pass"] == 1 and payload["claim"]["suite_before"]["reused_from"] is None
    assert payload["claim"]["suite_after"]["pass"] == 5
    assert any("reused the result of pass 2" in n for n in payload["notes"])


def _findings(where: Path) -> Path:
    path = where / "findings.json"
    path.write_text("[]", encoding="utf-8")
    return path


def test_the_flag_reaches_the_run(tmp_path, monkeypatch, capsys):
    seen = {}

    def spy(args, *rest, **kw):
        seen["always"] = args.suite_always
        return 0

    monkeypatch.setattr(cli, "_run_team", spy)
    assert cli.main(["tagteam", str(tmp_path)]) == 0 and seen["always"] is False
    assert cli.main(["tagteam", str(tmp_path), "--suite-always"]) == 0 and seen["always"] is True
    capsys.readouterr()
