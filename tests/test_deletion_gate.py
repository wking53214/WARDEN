"""Code is commented out (never deleted) only if two opposite tests pass: keep it broken, then take it out."""

from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.deletion import is_deletion, keep_variant
from warden.models import defects_from_ghost
from warden.tagteam import TagTeam

from fakes import FakeDrafter, RemovingDrafter
from heldutil import keep_held

DEAD = {"id": "ghost-dead1", "detector": "unused_code", "severity": "minor", "summary": "unused", "status": "confirmed"}
DEAD_PY = "def unused():\n    return 1\n"


def _repo(root: Path, tests: str = "from pkg import VALUE\n\ndef test_value():\n    assert VALUE == 1\n"):
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "pkg" / "dead.py").write_text(DEAD_PY, encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_pkg.py").write_text(tests, encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n',
                                          encoding="utf-8")


def _obs():
    return defects_from_ghost([DEAD])


def _auth(root: Path):
    return grant("william", "transform", str(root.resolve()), "code", "deletion test")


@pytest.fixture
def ghost(monkeypatch):
    """Ghost reports the dead-code finding until the code is commented out."""
    def fake_scan(target, **kw):
        text = (Path(target) / "pkg" / "dead.py").read_text(encoding="utf-8")
        return () if "WARDEN COMMENTED OUT" in text else (DEAD,)

    monkeypatch.setattr(tagteam, "ghost_scan", fake_scan)
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)


def _team(**kw):
    return TagTeam(drafter=RemovingDrafter(), ghost_tools_root=Path("."), **kw)


def _dead(root):
    return (root / "pkg" / "dead.py")


def test_unused_code_passes_both_tests_and_is_commented_out_not_deleted(tmp_path, ghost):
    _repo(tmp_path)
    result = _team().run(tmp_path, findings=[DEAD], authorization=_auth(tmp_path))
    keep_held(result, tmp_path)
    assert result.decision.startswith("ACCEPT") and result.cycles[0].outcome == "APPLIED"
    text = _dead(tmp_path).read_text(encoding="utf-8")
    assert _dead(tmp_path).exists()
    assert "# WARDEN COMMENTED OUT 20" in text and "ghost-dead1" in text
    assert "# def unused():" in text and "\ndef unused" not in text
    assert any("keep test passed" in n for n in result.notes)


def test_only_the_removed_function_is_commented_and_the_file_still_compiles(tmp_path):
    from warden.deletion import commented_variant
    mod = tmp_path / "m.py"
    mod.write_text("def keep():\n    return 1\n\n\n@deco\ndef gone():\n    return 2\n", encoding="utf-8")
    t = FakeDrafter(steps=("def keep():\n    return 1\n",), path="m.py").propose(tmp_path, (), "b")
    text = commented_variant(tmp_path, t, "2026-10-08T20:53:00-04:00")["m.py"]
    assert "def keep():\n    return 1" in text and "# @deco" in text and "# def gone():" in text
    assert "2026-10-08T20:53:00-04:00" in text
    compile(text, "m.py", "exec")


def test_code_called_by_name_fails_the_keep_test_and_survives(tmp_path, ghost):
    """The CNS case: nothing imports it, but the suite runs it. Deleting would stay green."""
    _repo(tmp_path)
    (tmp_path / "tests" / "conftest.py").write_text(
        "import importlib.util, pathlib\n"
        "spec = importlib.util.spec_from_file_location('dead', pathlib.Path(__file__).parents[1] / 'pkg' / 'dead.py')\n"
        "dead = importlib.util.module_from_spec(spec); spec.loader.exec_module(dead)\n"
        "def pytest_sessionstart(session):\n"
        "    getattr(dead, 'unused', lambda: None)()\n", encoding="utf-8")
    result = _team().run(tmp_path, findings=[DEAD], authorization=_auth(tmp_path))
    assert result.decision.startswith("ACCEPT") and _dead(tmp_path).read_text(encoding="utf-8") == DEAD_PY
    assert [c.outcome for c in result.cycles] == ["DECLINED", "NOTHING_TO_PROPOSE"]
    assert any("keep test FAILED" in n for n in result.notes)
    assert any("declined and left in place" in n for n in result.notes)


def test_the_keep_test_always_restores_the_files(tmp_path, ghost):
    _repo(tmp_path)
    (tmp_path / "tests" / "test_pkg.py").write_text(
        "from pkg import dead\n\ndef test_it():\n    assert dead.unused() == 1\n", encoding="utf-8")
    _team().run(tmp_path, findings=[DEAD], authorization=_auth(tmp_path))
    assert _dead(tmp_path).read_text(encoding="utf-8") == DEAD_PY


def test_a_removal_that_adds_ghost_findings_is_put_back(tmp_path, ghost, monkeypatch):
    _repo(tmp_path)

    def scan(target, **kw):
        if "WARDEN COMMENTED OUT" in _dead(Path(target)).read_text(encoding="utf-8"):
            return ({"id": "ghost-new1", "detector": "unused_code", "severity": "minor", "summary": "x", "status": "confirmed"},)
        return (DEAD,)

    monkeypatch.setattr(tagteam, "ghost_scan", scan)
    result = _team().run(tmp_path, findings=[DEAD], authorization=_auth(tmp_path))
    assert result.decision.startswith("ACCEPT") and _dead(tmp_path).read_text(encoding="utf-8") == DEAD_PY
    assert any("comment-out test failed" in n for n in result.notes)


def test_a_removal_without_ghost_is_never_applied(tmp_path, ghost):
    _repo(tmp_path)
    result = TagTeam(drafter=RemovingDrafter()).run(tmp_path, findings=[DEAD], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and _dead(tmp_path).exists()


def test_a_removal_without_the_suite_is_never_applied(tmp_path, ghost):
    _repo(tmp_path)
    result = _team(run_tests=False).run(tmp_path, findings=[DEAD], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and _dead(tmp_path).exists()


def test_a_removal_is_not_applied_when_swizzle_proofs_fail(tmp_path, ghost, monkeypatch):
    _repo(tmp_path)
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: False)
    result = _team().run(tmp_path, findings=[DEAD], authorization=_auth(tmp_path))
    assert _dead(tmp_path).exists() and not result.applied


def test_a_removal_citing_no_ghost_finding_is_refused(tmp_path, ghost):
    _repo(tmp_path)
    result = TagTeam(drafter=RemovingDrafter(cites=""), ghost_tools_root=Path(".")).run(
        tmp_path, findings=[DEAD], authorization=_auth(tmp_path), )
    assert _dead(tmp_path).read_text(encoding="utf-8") == DEAD_PY and not result.applied


def test_the_applier_refuses_a_removal_that_skipped_the_tests(tmp_path):
    _repo(tmp_path)
    proposal = RemovingDrafter().propose(tmp_path, _obs(), "b")
    done = TagTeam()._apply(tmp_path, proposal, _auth(tmp_path), "python", [], 1, 0)
    assert done.outcome == "REFUSED" and _dead(tmp_path).exists()


def test_removed_code_that_cannot_be_made_to_fail_is_refused(tmp_path):
    _repo(tmp_path)
    (tmp_path / "data.json").write_text("{}\n", encoding="utf-8")
    t = RemovingDrafter(path="data.json").propose(tmp_path, _obs(), "b")
    assert keep_variant(tmp_path, t) is None


def test_a_partial_removal_traps_only_the_removed_function(tmp_path):
    mod = tmp_path / "m.py"
    mod.write_text("def keep():\n    return 1\n\n\ndef gone():\n    return 2\n", encoding="utf-8")
    t = FakeDrafter(steps=("def keep():\n    return 1\n",), path="m.py").propose(tmp_path, (), "b")
    text = keep_variant(tmp_path, t)["m.py"]
    assert text.index("raise") > text.index("def gone") and "def keep():\n    return 1" in text
    compile(text, "m.py", "exec")


def test_what_counts_as_removing_code(tmp_path):
    _repo(tmp_path)
    assert is_deletion(tmp_path, RemovingDrafter().propose(tmp_path, _obs(), "b"))
    assert is_deletion(tmp_path, FakeDrafter(steps=("X = 1\n",), path="pkg/dead.py").propose(tmp_path, (), "b"))
    (tmp_path / "NOTE.md").write_text("a\nb\n", encoding="utf-8")
    assert not is_deletion(tmp_path, FakeDrafter(steps=("a\n",), path="NOTE.md").propose(tmp_path, (), "b"))
    assert not is_deletion(tmp_path, FakeDrafter(steps=("VALUE = 1\nO = 2\n",), path="pkg/__init__.py").propose(tmp_path, (), "b"))
