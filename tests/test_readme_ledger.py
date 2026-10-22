"""The README's evidence and ledger point at things that exist, and the README keeps the sections it promises.

A claim of "works" in the README names a test, a CI job or a recorded run. This file fails if a named test is gone,
if the ledger cites a version the CHANGELOG does not have (or dates it differently), if marketing words come back,
or if a number the README states about the code or `docs/REGISTRY.json` is not the real one.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

REQUIRED_HEADINGS = (
    "## WHAT THIS IS",
    "## HOW TO INSTALL AND RUN",
    "## WHAT WORKS",
    "## WHAT DOES NOT WORK / NOT PROVEN",
    "## KNOWN DEFECTS",
    "## WHAT BROKE AND HOW IT WAS FIXED",
    "## SELF-HOSTING",
    "## CEILINGS CODE CANNOT FIX",
)
BANNED_WORDS = ("robust", "powerful", "production-ready", "production ready", "seamless", "comprehensive",
                "blazing", "enterprise", "battle-tested", "state-of-the-art")


def section(title: str) -> str:
    start = README.index("\n" + title + "\n")
    following = re.search(r"^## ", README[start + len(title) + 2:], re.M)
    end = start + len(title) + 2 + following.start() if following else len(README)
    return README[start:end]


def test_the_readme_keeps_the_sections_it_promises_in_order():
    positions = [README.index("\n" + heading + "\n") for heading in REQUIRED_HEADINGS]
    assert positions == sorted(positions)
    assert all(README.count("\n" + heading + "\n") == 1 for heading in REQUIRED_HEADINGS)


def test_every_test_the_readme_names_exists():
    named = set(re.findall(r"`(tests/test_\w+\.py)(?:::(\w+))?`", README))
    assert named, "the README names no tests"
    for path, function in named:
        source = (ROOT / path).read_text(encoding="utf-8")
        if function:
            assert re.search(rf"^\s*def {function}\(", source, re.M), f"{path}::{function} is named in the README"


def test_a_test_named_by_its_function_alone_in_the_ledger_exists():
    everything = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py"))
    for function in re.findall(r"`::(test_\w+)`", section("## WHAT BROKE AND HOW IT WAS FIXED")):
        assert re.search(rf"^\s*def {function}\(", everything, re.M), function


def test_every_version_in_the_ledger_is_a_changelog_release_on_the_same_date():
    ledger = section("## WHAT BROKE AND HOW IT WAS FIXED")
    released = dict(re.findall(r"^## \[([^\]]+)\] - (\d{4}-\d{2}-\d{2})", CHANGELOG, re.M))
    entries = re.findall(r"^- \*\*(\d+\.\d+\.\d+)(?: \((\d{4}-\d{2}-\d{2})\))?", ledger, re.M)
    assert entries, "the ledger has no entries"
    for version, date in entries:
        assert version in released, f"{version} is not a CHANGELOG release"
        assert not date or date == released[version], f"{version}: README says {date}, CHANGELOG says {released[version]}"
    mentioned = set(re.findall(r"\b0\.\d+\.\d+\b", ledger))
    assert mentioned <= set(released), mentioned - set(released)


def test_every_ci_job_the_readme_names_is_in_the_workflow():
    jobs = re.findall(r"`(lint|extras|pytest|circuit|assay-latest)`", README)
    assert {"lint", "extras", "pytest", "circuit", "assay-latest"} <= set(jobs)
    for job in set(jobs):
        assert re.search(rf"^  {job}:", WORKFLOW, re.M), job
    assert set(re.findall(r"^    runs-on: (\S+)", WORKFLOW, re.M)) == {"ubuntu-latest"}, "README says CI uses ubuntu-latest only"


def test_the_readme_uses_no_marketing_words():
    lowered = README.lower()
    assert not [word for word in BANNED_WORDS if word in lowered]


def test_the_registry_numbers_the_readme_states_are_the_registry_s():
    rows = json.loads((ROOT / "docs" / "REGISTRY.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 6 and "rows 1 to 4" in README and "rows 5 and 6" in README
    assert "3 of 5 known failure modes" in rows[2]["adversarial_validation_executed"] and "(Ghost caught 3 of 5" in README
    assert "5 of 7 known failure modes" in rows[3]["adversarial_validation_executed"] and "(5 of 7)" in README
    five = rows[4]
    assert five["unknown"].startswith("2026-10-14") and "Row 5 is dated 2026-10-14" in README
    assert "seven repositories" in five["repository"] and "ACCEPT_UNVERIFIED" in five["warden_involvement"]
    six = rows[5]
    assert "WARDEN: ACCEPT" in six["warden_involvement"]
    assert re.search(r"^## \[0\.11\.2\] - 2026-10-15", CHANGELOG, re.M) and "2026-10-15 for Warden 0.11.2" in README


def test_the_defaults_and_limits_the_readme_states_are_the_code_s(capsys):
    import pytest

    from warden import cli, guard, models, tagteam

    with pytest.raises(SystemExit):
        cli.main(["tagteam", "--help"])
    helptext = " ".join(capsys.readouterr().out.split())
    for flag, default in (("--max-cycles", 10), ("--ghost-timeout", 600), ("--suite-timeout", 900),
                          ("--seat-timeout", 3600)):
        assert re.search(rf"{flag} \S+\s.*?\(default {default}\)", helptext), (flag, default)
    assert tagteam.DEFAULT_MAX_CYCLES == 10 and "`--max-cycles`, default 10" in README
    assert "`--suite-timeout` (default 900 seconds)" in README and "`--seat-timeout` (default 3600)" in README
    assert "default 600 seconds" in README
    assert tagteam.DEFAULT_MAX_DECLINED == 50 and "At most 50 declined proposals" in README
    assert guard._RESTORE_LIMIT == 200 * 1024 * 1024 and "A tree over 200 MB" in README
    assert len(models.safe_id("a" * 100)) == 64 and "64 characters at most" in README


def test_the_ghost_scan_is_cut_at_ten_gaps_and_twenty_declined_checks_as_the_readme_says(tmp_path, monkeypatch):
    import sys

    import warden.tagteam as tagteam
    from warden.tagteam import TagTeam

    sys.path.insert(0, str(Path(__file__).parent))
    from fakes import FakeDrafter

    class Scan(tuple):
        status = "ok"
        scan_counts = {"files_scanned": 1, "files_skipped": 0, "files_unparsable": 0}
        gaps = tuple(f"gap {i}" for i in range(13))
        declined = tuple(f"check{i}" for i in range(25))
        baseline = None

    (tmp_path / "NOTE.md").write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: Scan())
    result = TagTeam(drafter=FakeDrafter(), ghost_tools_root=Path(".")).run(tmp_path, findings=None, authorization=None)
    info = result.ghost_scan
    assert len(info["gaps"]) == 10 and info["gaps_not_shown"] == 3 and len(info["declined"]) == 20
    assert "cut at 10 entries and `declined` at 20" in README


def test_the_readme_cns_migration_note_names_the_tag_and_its_commit():
    assert "from CNS `v1.9.0` to `v2.0.0`" in README
    assert "b13e5d2f9e0e4291725f82794b89117c3d840ac1" in README
