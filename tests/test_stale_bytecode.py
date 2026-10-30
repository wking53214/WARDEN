"""A planted or stale .pyc in a seat or an instrument checkout is never used.

The attack (round-6 audit, reproduced with the circuit_refusals harness): a clean `--stack` checkout of JUDGE has an
ignored `judge/__pycache__/`. An unchecked-hash .pyc placed there is loaded by Python in place of the source without
looking at the source, `git status` stays clean (the folder is ignored), the dirty check passes, and the tampered code
ran inside the governed run, which still ended ACCEPT.

The fix: Warden gives the Python it runs, and every instrument it starts, a fresh private bytecode cache directory
(`sys.pycache_prefix` and `PYTHONPYCACHEPREFIX`). With a prefix set, Python reads and writes .pyc only under the prefix
and never looks in a source tree's `__pycache__`, so a file planted there is not read.

The pyc here is real: built with `py_compile` in unchecked-hash mode from tampered source, in a temporary folder this
test creates.
"""

import importlib.util
import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

from gitutil import commit_all

from warden import isolation

ROOT = Path(__file__).resolve().parents[1]

LEGIT = '''import os
requires_contract = "1"


class Judge:
    requires_contract = "1"

    def decide(self, evidence):
        from warden.roles import Verdict
        return Verdict("ACCEPT", ("source ran",), "zjudge")
'''
TAMPERED = LEGIT.replace("source ran", "pyc ran") + '''
open(os.environ["ZMARKER"], "w").write("the tampered bytecode ran")
'''
DRAFTER = '''from pathlib import Path
from warden.models import FileEdit, Transformation, TransformationStatus


class Drafter:
    requires_contract = "1"
    scope = "documentation"

    def __init__(self):
        self.done = False

    def propose(self, target, observed, baseline):
        if self.done:
            return None
        self.done = True
        old = (Path(target) / "NOTE.md").read_text(encoding="utf-8")
        return Transformation(
            target=str(Path(target).resolve()), intent="x", architectural_reason="x", affected_files=("NOTE.md",),
            expected_behavior="none", preservation_requirements=(), known_defects=(),
            transformation_scope="documentation", baseline_reference=baseline, evidence=(),
            edits=(FileEdit(path="NOTE.md", kind="write", new="edit\\n", old=old),),
            status=TransformationStatus.PROPOSED)
'''


def _plant(source_path: Path, tampered_source: str, work: Path) -> Path:
    """Compile `tampered_source` as an UNCHECKED_HASH pyc and put it where Python looks for `source_path`'s bytecode."""
    src = work / "tampered_src.py"
    src.write_text(tampered_source, encoding="utf-8")
    # Where PLAIN Python looks: beside the source, in its __pycache__. `cache_from_source` honours this process's
    # own cache prefix, and when this suite runs under Warden (`suite.py` sets PYTHONPYCACHEPREFIX for the target's
    # tests) that prefix would send the planted file elsewhere and the control below would prove nothing. Found by
    # self-hosting run 3. The subprocess env in `_env` drops the variable for the same reason.
    saved = sys.pycache_prefix
    sys.pycache_prefix = None
    try:
        cfile = Path(importlib.util.cache_from_source(str(source_path)))
    finally:
        sys.pycache_prefix = saved
    cfile.parent.mkdir(parents=True, exist_ok=True)
    py_compile.compile(str(src), cfile=str(cfile), dfile=str(source_path), doraise=True,
                       invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    return cfile


@pytest.fixture
def attack(tmp_path):
    """A clean, committed checkout of a one-module seat whose __pycache__ is ignored and holds a tampered pyc."""
    checkout = tmp_path / "stack" / "JUDGE"
    (checkout / "zjudge").mkdir(parents=True)
    (checkout / "zjudge" / "__init__.py").write_text("", encoding="utf-8")
    (checkout / "zjudge" / "seat.py").write_text(LEGIT, encoding="utf-8")
    (checkout / "pyproject.toml").write_text('[project]\nname = "zjudge"\nversion = "0.4.10"\n', encoding="utf-8")
    (checkout / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    commit_all(checkout)
    work = tmp_path / "work"
    work.mkdir()
    cfile = _plant(checkout / "zjudge" / "seat.py", TAMPERED, work)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=checkout, capture_output=True, text=True).stdout
    assert status == "", "the planted pyc must be invisible to git, or this is not the attack"
    seats = tmp_path / "seats"
    seats.mkdir()
    (seats / "zdrafter.py").write_text(DRAFTER, encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    (target / "NOTE.md").write_text("old\n", encoding="utf-8")
    (target / "tests").mkdir()
    (target / "tests" / "test_x.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    (target / "pyproject.toml").write_text('[project]\nname = "t"\nversion = "0.0.1"\n', encoding="utf-8")
    commit_all(target)
    marker = tmp_path / "marker.txt"
    return {"checkout": checkout, "seats": seats, "target": target, "marker": marker, "cfile": cfile,
            "tmp": tmp_path}


def _env(attack, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE")}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(attack["checkout"]), str(attack["seats"])])
    env["ZMARKER"] = str(attack["marker"])
    env["HOME"] = str(attack["tmp"] / "home")
    env.update(extra)
    return env


def test_the_planted_pyc_really_is_loaded_by_plain_python(attack):
    """The control: without Warden's protection the tampered bytecode runs. This is what makes the next test mean something."""
    done = subprocess.run([sys.executable, "-c", "import zjudge.seat"], env=_env(attack), capture_output=True, text=True,
                          cwd=attack["tmp"])
    assert done.returncode == 0, done.stderr
    assert attack["marker"].read_text() == "the tampered bytecode ran"


def test_the_control_plants_where_plain_python_looks_even_under_a_cache_prefix(attack, tmp_path, monkeypatch):
    """What self-hosting run 3 hit: this suite itself running with a bytecode prefix set (Warden's `suite.py` sets one
    for the target's tests). The planted file must still land in the checkout's own __pycache__, and the control
    subprocess must be given an environment without the prefix."""
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", str(tmp_path / "elsewhere"))
    (attack["tmp"] / "work2").mkdir()
    cfile = _plant(attack["checkout"] / "zjudge" / "seat.py", TAMPERED, attack["tmp"] / "work2")
    assert cfile.parent == attack["checkout"] / "zjudge" / "__pycache__" and cfile.is_file()
    assert "PYTHONPYCACHEPREFIX" not in _env(attack)
    done = subprocess.run([sys.executable, "-c", "import zjudge.seat"], env=_env(attack), capture_output=True, text=True,
                          cwd=attack["tmp"])
    assert done.returncode == 0, done.stderr
    assert attack["marker"].read_text() == "the tampered bytecode ran"


def test_warden_runs_the_source_not_the_planted_pyc_in_a_vetted_seat(attack):
    args = ["tagteam", str(attack["target"]), "--drafter", "zdrafter:Drafter", "--judge", "zjudge.seat:Judge",
            "--authorize", "tester", "--reason", "stale bytecode test"]
    done = subprocess.run([sys.executable, "-m", "warden.cli", *args], env=_env(attack), capture_output=True, text=True,
                          cwd=attack["tmp"], timeout=600)
    record = json.loads(done.stdout)
    assert record["verdict"] is not None, (record["decision"], record["reason"], done.stderr[-500:])
    assert record["verdict"]["reasons"] == ["source ran"], record["verdict"]
    assert not attack["marker"].exists(), "the tampered bytecode ran inside the governed run"
    seat = record["versions"]["seats"]["judge"]
    assert seat["version"] == "0.4.10" and seat["dirty"] is False


def test_instruments_are_started_with_a_private_bytecode_cache():
    env = isolation.instrument_env(ROOT)
    prefix = Path(env["PYTHONPYCACHEPREFIX"])
    assert prefix.is_dir()
    assert not prefix.resolve().is_relative_to(ROOT.resolve()), "the cache must not live in a checkout"
    assert (prefix.stat().st_mode & 0o077) == 0, "the cache directory is private to this user"
    assert isolation.instrument_env(ROOT)["PYTHONPYCACHEPREFIX"] == str(prefix), "one cache per Warden process"


def test_an_instrument_subprocess_does_not_read_a_planted_pyc(attack):
    script = "import zjudge.seat; print('imported')"
    proc = isolation.run_instrument([sys.executable, "-c", script], roots=[attack["checkout"]], timeout=120,
                                    extra_env={"ZMARKER": str(attack["marker"])})
    assert proc.returncode == 0, proc.stderr
    assert not attack["marker"].exists(), "an instrument loaded the tampered bytecode"


def test_the_prefix_is_set_only_while_main_runs_and_is_removed_after(tmp_path, monkeypatch):
    """`cli.main` called in-process (as the tests do) must not leave the interpreter with a changed cache for good."""
    from warden import cli
    seen = {}
    monkeypatch.setattr(cli, "_audit", lambda args: seen.setdefault("prefix", sys.pycache_prefix) and 0)
    before = sys.pycache_prefix
    findings = tmp_path / "f.json"
    findings.write_text("[]", encoding="utf-8")
    cli.main(["audit", str(tmp_path), "--from-ghost", str(findings)])
    assert seen["prefix"] and Path(seen["prefix"]).name.startswith("warden-pyc-")
    assert sys.pycache_prefix == before
    assert not Path(seen["prefix"]).exists()
