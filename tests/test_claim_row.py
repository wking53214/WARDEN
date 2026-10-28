"""The claim row: from a record alone a reader can tell which change was governed and what the held tree is.

The row is built from what the run had in its hands (the claim seat's facts, the grant, the structured suite
results, Ghost's findings, the Judge's sentences, the held digest and the held tree's fingerprint). Three things are
checked here: the `diff_sha256` names exactly one commit among candidates, the held tree equals base + claimed diff +
the Finisher's edits file by file, and the row survives a trip through JSON unchanged.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from gitutil import commit_all, git

import warden.tagteam as tagteam
from warden import held
from warden.authorization import grant
from warden.claimrow import KEYS, claim_row
from warden.cli import main
from warden.guard import Snapshot
from warden.tagteam import TagTeam, _fingerprint

from fakes import FakeDrafter, FakeJudge

FINISHER = '''
from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus

APPENDED = "\\n<!-- generated -->\\nfacts\\n"


class Finisher:
    requires_contract = "1"

    def finish(self, target, baseline, facts):
        path = Path(target) / "README.md"
        old = path.read_text(encoding="utf-8")
        return Transformation(
            target=str(Path(target).resolve()), intent="facts section", architectural_reason="test",
            affected_files=("README.md",), expected_behavior="none", preservation_requirements=(), known_defects=(),
            transformation_scope="documentation", baseline_reference=baseline, evidence=(),
            edits=(FileEdit(path="README.md", kind="write", new=old + APPENDED, old=old),),
            status=TransformationStatus.PROPOSED)
'''

_GIT_ENV = {"GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.org", "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1"}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
                          env=dict(_GIT_ENV, HOME=str(cwd)))
    return done.stdout.strip()


def _commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def _reference(root: Path) -> list[str]:
    """Five commits, each adding text to a different file. Returns their shas, oldest first."""
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / "tools").mkdir()
    (root / "tools" / "util.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    commit_all(root, "base")
    shas = [git(root, "rev-parse", "HEAD")]
    (root / "NOTE.md").write_text("a note\n", encoding="utf-8")
    shas.append(_commit(root, "Step 1: a note"))
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\nNAME = 'demo'\n", encoding="utf-8")
    shas.append(_commit(root, "Step 2: a name"))
    (root / "README.md").write_text("# demo\n\nIt has a name.\n", encoding="utf-8")
    shas.append(_commit(root, "Step 3: say so in the README"))
    (root / "tools" / "util.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n", encoding="utf-8")
    shas.append(_commit(root, "Step 4: a second helper"))
    return shas


def _diff_sha(root: Path, sha: str) -> str:
    out = subprocess.run(["git", "diff", "--no-ext-diff", "--no-color", "--no-renames", "--src-prefix=a/",
                          "--dst-prefix=b/", f"{sha}^", sha], cwd=str(root), check=True, capture_output=True).stdout
    return hashlib.sha256(out).hexdigest()


def _fingerprint_of(files: dict, where: Path) -> str:
    where.mkdir()
    for rel, data in files.items():
        (where / rel).parent.mkdir(parents=True, exist_ok=True)
        (where / rel).write_bytes(data)
    return _fingerprint(where)


@pytest.fixture
def governed(tmp_path, monkeypatch, capsys):
    """Commit 3 of five governed on a clone that stands at commit 2, with a Finisher that appends to the README."""
    reference = tmp_path / "reference"
    shas = _reference(reference)
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", shas[2])
    seats = tmp_path / "seats"
    seats.mkdir()
    (seats / "rowseats.py").write_text(FINISHER, encoding="utf-8")
    monkeypatch.syspath_prepend(str(seats))
    receipt = tmp_path / "receipt.json"
    code = main(["tagteam", str(target), "--claim-commit", shas[3], "--claim-repo", str(reference),
                 "--finisher", "rowseats:Finisher", "--authorize", "william", "--reason", "govern commit 3",
                 "--scope", "code", "--receipt", str(receipt)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED" and payload["finished"], payload["reason"]

    class Run:
        pass

    run = Run()
    run.reference, run.target, run.shas, run.payload, run.receipt, run.tmp = reference, target, shas, payload, receipt, tmp_path
    return run


def test_the_row_has_exactly_the_shared_keys_and_round_trips_through_json(governed):
    row = governed.payload["claim"]
    assert tuple(row) == KEYS
    assert json.loads(json.dumps(row)) == row


def test_the_diff_digest_names_exactly_one_of_the_candidate_commits(governed):
    row = governed.payload["claim"]
    candidates = {sha: _diff_sha(governed.reference, sha) for sha in governed.shas[1:]}
    matching = [sha for sha, digest in candidates.items() if digest == row["diff_sha256"]]
    assert matching == [governed.shas[3]] and row["claimed_commit"] == governed.shas[3]
    assert row["base_commit"] == governed.shas[2] and row["claimed_subject"] == "Step 3: say so in the README"
    assert row["claimed_author"] == "Ada <ada@example.org>" and row["claimed_date"].startswith("20")
    assert row["origin"] == str(governed.reference) and row["diff_bytes"] > 0
    assert row["actor"] == "william" and row["scope"] == "code" and row["authority"] == "human_operator"
    assert row["authorization_id"].startswith("auth_") and row["transformation_id"].startswith("xform_")


def test_the_actors_files_and_the_finishers_edits_are_told_apart(governed):
    row = governed.payload["claim"]
    before = _git(governed.reference, "show", f"{governed.shas[2]}:README.md") + "\n"
    after = _git(governed.reference, "show", f"{governed.shas[3]}:README.md") + "\n"
    assert row["files"] == [{"path": "README.md", "status": "M", "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                             "after_sha256": hashlib.sha256(after.encode()).hexdigest(), "protected": False}]
    assert row["finisher_edits"] == [{"path": "README.md", "lines_added": 3, "lines_removed": 0}]
    assert row["suite_before"]["passed"] == 1 and row["suite_after"]["passed"] == 1
    assert (row["ghost_before_count"], row["ghost_after_count"], row["new_findings"], row["closed_findings"]) == (0, 0, [], [])
    assert row["rules_fired"] == [] and row["judge"]["verdict"] is None and row["decision"] == "ACCEPT_UNVERIFIED"
    names = {p["name"] for p in row["participants"]}
    assert {"warden", "drafter seat", "finisher seat"} <= names


def test_the_held_tree_is_base_plus_the_claimed_diff_plus_the_finishers_edits(governed):
    row = governed.payload["claim"]
    record = held.load(governed.target, row["held_digest"])
    held_files = held._unb64(record["files"])
    base = Snapshot(governed.target).files  # the tree was put back, so this is commit 2's tree
    claimed = dict(base, **{"README.md": (_git(governed.reference, "show", f"{governed.shas[3]}:README.md") + "\n").encode()})
    expected = dict(claimed, **{"README.md": claimed["README.md"] + b"\n<!-- generated -->\nfacts\n"})
    assert held_files == expected
    assert row["base_tree_digest"] == _fingerprint_of(base, governed.tmp / "m_base")
    assert row["claimed_tree_digest"] == _fingerprint_of(claimed, governed.tmp / "m_claimed")
    assert row["held_tree_digest"] == _fingerprint_of(expected, governed.tmp / "m_held")
    assert row["held_tree_digest"] == record["claim"]["held_tree_digest"]  # the held file carries the row


def test_the_held_file_and_the_receipt_carry_the_row(governed):
    row = governed.payload["claim"]
    record = held.load(governed.target, row["held_digest"])
    assert record["claim"]["claimed_commit"] == governed.shas[3] and "evidence" in record
    receipt = json.loads(governed.receipt.read_text(encoding="utf-8"))
    assert receipt["claim"]["diff_sha256"] == row["diff_sha256"] and receipt["evidence"] is None  # no Judge was seated
    assert governed.payload["evidence"] is None


def _repo(root: Path) -> Path:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n", encoding="utf-8")
    (root / "NOTE.md").write_text("old note\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0.0.1"\n', encoding="utf-8")
    return root


def test_an_ordinary_drafter_run_has_a_row_with_no_commit_and_its_files_by_digest(tmp_path):
    _repo(tmp_path)
    auth = grant("william", "transform", str(tmp_path.resolve()), "documentation", "row test")
    result = TagTeam(drafter=FakeDrafter(steps=("new note\n",))).run(tmp_path, findings=[], authorization=auth)
    row = claim_row(result, auth)
    assert tuple(row) == KEYS and row["claimed_commit"] is None and row["diff_sha256"] is None
    assert row["files"] == [{"path": "NOTE.md", "status": "M", "before_sha256": hashlib.sha256(b"old note\n").hexdigest(),
                             "after_sha256": hashlib.sha256(b"new note\n").hexdigest(), "protected": False}]
    assert row["base_tree_digest"] == result.baseline and row["held_tree_digest"] == result.held_tree_digest
    assert row["held_tree_digest"] != row["base_tree_digest"] and row["claimed_tree_digest"] == row["held_tree_digest"]
    assert row["suite_before"]["passed"] == 1 and row["participants"] == [] and row["finisher_edits"] == []
    assert json.loads(json.dumps(row)) == row


def test_the_judges_sentences_and_evidence_are_kept_on_the_result(tmp_path, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))
    auth = grant("william", "transform", str(tmp_path.resolve()), "documentation", "row test")
    judge = FakeJudge("INSUFFICIENT", ("no attacks", "the machine does not approve that"))
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), judge=judge, ghost_tools_root=Path("."), swizzle_root=Path("."),
                   assay_root=Path("."))
    result = team.run(tmp_path, findings=[], authorization=auth)
    assert result.evidence is judge.evidence and result.decision == "ACCEPT_UNVERIFIED"
    row = claim_row(result, auth, {"seats": {"judge": {"spec": "fakes:FakeJudge", "version": "1", "commit": None}}})
    assert row["rules_fired"] == ["no attacks", "the machine does not approve that"]
    assert row["judge"] == {"seat": "fakes:FakeJudge", "version": "1", "commit": None, "verdict": "INSUFFICIENT"}
    import dataclasses
    serialised = json.loads(json.dumps(dataclasses.asdict(result.evidence)))
    assert serialised["suite_after"]["passed"] == 1 and serialised["attacks"][0]["status"] == "held"
