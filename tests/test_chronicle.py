"""The chronicle: a run settles what the previous run on the same tree promised, keyed by (origin, base, claimed commit).

A two-run chain settles `suite_green` HELD with the measurement; a run on an unrelated tree settles nothing; `warden
keep --chronicle` appends a human line; `warden chronicle DIR` prints the chain in the order it was written.
"""

import json
import subprocess
from pathlib import Path

import pytest

from gitutil import commit_all, git

from warden import chronicle
from warden.cli import main

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
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("from pkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
                                              encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n', encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    commit_all(root, "base")
    shas = [git(root, "rev-parse", "HEAD")]
    (root / "NOTE.md").write_text("a note\n", encoding="utf-8")
    shas.append(_commit(root, "Step 1: a note"))
    (root / "README.md").write_text("# demo\n\nMore.\n", encoding="utf-8")
    shas.append(_commit(root, "Step 2: more README"))
    return shas


def _run(capsys, target, reference, sha, where):
    code = main(["tagteam", str(target), "--claim-commit", sha, "--claim-repo", str(reference), "--authorize", "william",
                 "--reason", "chain", "--scope", "code", "--chronicle", str(where)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 3 and payload["decision"] == "ACCEPT_UNVERIFIED", payload["reason"]
    return payload


@pytest.fixture
def chain(tmp_path, capsys):
    reference = tmp_path / "reference"
    shas = _reference(reference)
    target = tmp_path / "target"
    _git(tmp_path, "clone", "-q", str(reference), str(target))
    _git(target, "checkout", "-q", shas[0])
    where = tmp_path / "chronicle"
    first = _run(capsys, target, reference, shas[1], where)

    class Chain:
        pass

    c = Chain()
    c.reference, c.target, c.shas, c.where, c.first, c.capsys, c.tmp = reference, target, shas, where, first, capsys, tmp_path
    return c


def test_the_first_run_opens_promises_and_settles_nothing(chain):
    note = chain.first["chronicle"]
    assert note["settled"] == [] and [p["promise"] for p in note["promises"]] == ["suite_green"]
    assert note["promises"][0]["expect"]["passed"] == 1
    path = Path(note["file"])
    assert path.parent == chain.where and path.name == chronicle.slug(str(chain.reference)) + ".jsonl"
    lines = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["kind"] == "run"
    assert lines[0]["key"] == {"origin": str(chain.reference), "base_commit": chain.shas[0], "claimed_commit": chain.shas[1]}
    assert lines[0]["claim"]["diff_sha256"] and lines[0]["held_digest"] == chain.first["held_digest"]
    assert any("Chronicle: this run is line 1 of" in n for n in chain.first["notes"])


def test_a_two_run_chain_settles_suite_green_held_with_the_measurement(chain):
    _git(chain.target, "checkout", "-q", chain.shas[1])
    second = _run(chain.capsys, chain.target, chain.reference, chain.shas[2], chain.where)
    settled = second["chronicle"]["settled"]
    assert len(settled) == 1
    s = settled[0]
    assert s["promise"] == "suite_green" and s["status"] == "HELD" and s["base_is"] == "held tree"
    assert s["settles"]["claimed_commit"] == chain.shas[1] and s["settles"]["base_commit"] == chain.shas[0]
    assert "first pass 1 passed, 0 failed, 0 errors; promised 1 passed, identical counts" == s["measurement"]
    assert second["claim"]["base_tree_digest"] == chain.first["claim"]["held_tree_digest"]
    assert any(n.startswith(f"Chronicle: suite_green promised by the run of {chain.shas[1][:12]}") and "is HELD" in n
               for n in second["notes"])
    lines = [json.loads(ln) for ln in Path(second["chronicle"]["file"]).read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2 and lines[1]["settled"] == settled and lines[1]["key"]["base_commit"] == chain.shas[1]


def test_a_run_on_an_unrelated_tree_settles_nothing(chain):
    # The same origin and the same chronicle, but the base is the parent again: no promise was made about that tree.
    again = _run(chain.capsys, chain.target, chain.reference, chain.shas[1], chain.where)
    assert again["chronicle"]["settled"] == []
    # Another repository with its own origin writes its own file and sees none of the first one's promises.
    other_ref = chain.tmp / "other"
    shas = _reference(other_ref)
    (other_ref / "pkg" / "__init__.py").write_text("VALUE = 1\nOTHER = True\n", encoding="utf-8")
    _commit(other_ref, "Step 3: other")
    other = chain.tmp / "other_target"
    _git(chain.tmp, "clone", "-q", str(other_ref), str(other))
    _git(other, "checkout", "-q", shas[1])
    third = _run(chain.capsys, other, other_ref, shas[2], chain.where)
    assert third["chronicle"]["settled"] == [] and Path(third["chronicle"]["file"]).name != Path(chain.first["chronicle"]["file"]).name
    assert len(list(chain.where.glob("*.jsonl"))) == 2


def test_keep_appends_a_human_line_and_the_reader_prints_the_chain_in_order(chain):
    digest = chain.first["held_digest"]
    code = main(["keep", str(chain.target), "--digest", digest, "--authorize", "William King", "--reason", "reviewed",
                 "--chronicle", str(chain.where)])
    kept = json.loads(chain.capsys.readouterr().out)
    assert code == 0 and kept["decision"] == "KEPT" and any("Chronicle: the keep was written" in n for n in kept["notes"])
    _git(chain.target, "reset", "-q", "--hard")
    _git(chain.target, "clean", "-fdq")
    _git(chain.target, "checkout", "-q", chain.shas[1])
    _run(chain.capsys, chain.target, chain.reference, chain.shas[2], chain.where)
    lines = [json.loads(ln) for ln in Path(chain.first["chronicle"]["file"]).read_text(encoding="utf-8").splitlines()]
    assert [ln["kind"] for ln in lines] == ["run", "keep", "run"]
    assert lines[1]["who"] == "William King" and lines[1]["digest"] == digest
    assert lines[1]["key"]["claimed_commit"] == chain.shas[1]
    assert main(["chronicle", str(chain.where)]) == 0
    out = chain.capsys.readouterr().out.splitlines()
    runs = [ln for ln in out if "  run   " in ln]
    assert len(runs) == 2 and f"claim {chain.shas[1][:12]}" in runs[0] and f"claim {chain.shas[2][:12]}" in runs[1]
    assert any(ln.startswith(lines[1]["when"]) and "keep" in ln and "William King" in ln for ln in out)
    assert any(ln.strip().startswith(f"settles {chain.shas[1][:12]}: suite_green HELD") for ln in out)
    assert out.index(runs[0]) < out.index(runs[1])
    assert main(["chronicle", str(chain.where), "--origin", str(chain.reference)]) == 0
    assert len([ln for ln in chain.capsys.readouterr().out.splitlines() if "  run   " in ln]) == 2
    assert main(["chronicle", str(chain.where), "--origin", "https://example.org/none"]) == 0
    assert chain.capsys.readouterr().out == ""
    assert main(["chronicle", str(chain.tmp / "missing")]) == 2


# -- settlement rules, on fabricated entries -------------------------------------------------------------------

def _entry(**promises):
    return {"kind": "run", "when": "2026-10-01T00:00:00+00:00", "key": {"origin": "o", "base_commit": "b", "claimed_commit": "c"},
            "held_tree_digest": "T", "claimed_tree_digest": "C", "promises": [{"promise": k, "expect": v} for k, v in promises.items()]}


GREEN = {"ran": True, "passed": 3, "failed": 0, "errors": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
RED = {**GREEN, "passed": 2, "failed": 1}


def test_settlement_rules():
    entries = [_entry(suite_green={"passed": 3, "failed": 0, "errors": 0}, **{"standing:ghost-a": "present",
                                                                               "fixed:ghost-b": "absent",
                                                                               "gaps_closed:mutate": "measured",
                                                                               "gaps_closed:secrets": "measured"})]
    now = "2026-10-28T00:00:00+00:00"
    held = {s["promise"]: s for s in chronicle.settle(entries, "T", GREEN, ["ghost-a"], ["secrets"], now)}
    assert held["suite_green"]["status"] == "HELD" and held["standing:ghost-a"]["status"] == "HELD"
    assert held["fixed:ghost-b"]["status"] == "HELD" and held["gaps_closed:mutate"]["status"] == "HELD"
    assert held["gaps_closed:secrets"]["status"] == "OPEN"
    broken = {s["promise"]: s for s in chronicle.settle(entries, "C", RED, ["ghost-b"], ["secrets", "mutate"],
                                                        "2027-02-01T00:00:00+00:00")}
    assert broken["suite_green"]["status"] == "BROKEN" and "counts differ" in broken["suite_green"]["measurement"]
    assert broken["standing:ghost-a"]["status"] == "BROKEN" and broken["fixed:ghost-b"]["status"] == "BROKEN"
    assert broken["gaps_closed:mutate"]["status"] == "BROKEN" and all(s["base_is"] == "claimed tree" for s in broken.values())
    unknown = {s["promise"]: s for s in chronicle.settle(entries, "T", None, None, [], now)}
    assert unknown["suite_green"]["status"] == "OPEN" and unknown["standing:ghost-a"]["status"] == "OPEN"
    assert chronicle.settle(entries, "X", GREEN, [], [], now) == [] and chronicle.settle(entries, None, GREEN, [], [], now) == []


def test_the_slug_never_uses_a_path_as_a_key_and_separates_origins():
    a, b = chronicle.slug("https://github.com/x/y"), chronicle.slug("https://github.com/x/z")
    assert a != b and a.startswith("https-github.com-x-y-") and chronicle.slug(None).startswith("no-origin-")
    assert chronicle.path_for(Path("/d"), "o").name == chronicle.slug("o") + ".jsonl"
