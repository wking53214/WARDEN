"""Rule 7: no change stands unless the target's own suite was green before
and is still green after. Elegant.md: "No beautification or fix commit merges
without a green automated suite." Until 2026-10-07 the tag team never ran
the target's tests at all.
"""
from pathlib import Path

from warden.authorization import grant
from warden.suite import SuiteRun, preserved
from warden.tagteam import TagTeam

from fakes import FakeDrafter
from heldutil import keep_held


def _repo(root: Path, test_body: str = "    assert True\n") -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_pkg.py").write_text(
        "from pkg import VALUE\n\ndef test_value():\n" + test_body, encoding="utf-8")
    (root / "NOTE.md").write_text("old note\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.0.1"\n',
                                          encoding="utf-8")


def _auth(root: Path):
    return grant("william", "transform", str(root.resolve()), "code", "rule 7 test")


def _breaker():
    """A drafter whose change alters behavior: VALUE becomes 2, and the suite checks 1."""
    return FakeDrafter(steps=("VALUE = 2\n",), path="pkg/__init__.py")


def test_a_change_that_breaks_the_suite_is_put_back(tmp_path: Path):
    _repo(tmp_path, "    assert VALUE == 1\n")
    result = TagTeam(drafter=_breaker()).run(tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "REJECT" and not result.applied
    assert (tmp_path / "pkg" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert result.suite_before.green and result.suite_after.failed == 1
    assert any("put back" in n for n in result.notes)


def test_a_red_suite_before_the_change_means_no_write(tmp_path: Path):
    _repo(tmp_path, "    assert False\n")
    before = (tmp_path / "NOTE.md").read_text(encoding="utf-8")
    result = TagTeam(drafter=FakeDrafter()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "INCONCLUSIVE" and not result.applied
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == before


def test_no_tests_means_no_write(tmp_path: Path):
    _repo(tmp_path)
    (tmp_path / "tests" / "test_pkg.py").unlink()
    before = (tmp_path / "NOTE.md").read_text(encoding="utf-8")
    result = TagTeam(drafter=FakeDrafter()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.decision == "INCONCLUSIVE"
    assert (tmp_path / "NOTE.md").read_text(encoding="utf-8") == before
    assert not result.suite_before.ran


def test_a_preserving_change_records_both_counts(tmp_path: Path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter()).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert result.held_digest
    keep_held(result, tmp_path)
    assert result.suite_before.passed == result.suite_after.passed == 1
    assert any(n.startswith("Rule 7 suite cycle 1 after: 1 passed") for n in result.notes)


def test_turning_the_gate_off_is_said_out_loud(tmp_path: Path):
    _repo(tmp_path)
    result = TagTeam(drafter=FakeDrafter(), run_tests=False).run(
        tmp_path, findings=[], authorization=_auth(tmp_path))
    assert any("Rule 7 NOT RUN" in n for n in result.notes)


def test_preserved_rules():
    green = SuiteRun(ran=True, passed=3)
    assert preserved(green, SuiteRun(ran=True, passed=3)) is None
    assert preserved(green, SuiteRun(ran=True, passed=2)) is not None
    assert preserved(green, SuiteRun(ran=True, passed=4, failed=1)) is not None
    assert preserved(green, SuiteRun(ran=False, reason="x")) is not None
