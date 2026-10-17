"""Documents that state facts the code owns are generated from it or tested against it."""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

import warden
from warden.cli import EXIT_CODES

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}")


def _gen_docs():
    spec = importlib.util.spec_from_file_location("gen_docs", ROOT / "tools" / "gen_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_docs_are_not_stale():
    gen = _gen_docs()
    assert (ROOT / "docs" / "EXIT_CODES.md").read_text(encoding="utf-8") == gen.exit_codes_md(), \
        "run: python tools/gen_docs.py --write"
    current = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert current == gen.architecture_md(current), "run: python tools/gen_docs.py --write"


def test_every_exit_code_decision_is_in_the_exit_code_page_and_the_readme_table():
    page = (ROOT / "docs" / "EXIT_CODES.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for decision, code in EXIT_CODES.items():
        assert re.search(rf"\| {code} \|.*`{decision}`", page), decision
    for decision in set(EXIT_CODES) - {"USAGE_ERROR", "SEAT_NOT_LOADED"}:
        assert f"`{decision}`" in readme, decision
    for code in set(EXIT_CODES.values()):
        assert re.search(rf"^\| {code} \|", readme, re.MULTILINE), f"README exit-code table lacks {code}"


def test_every_module_is_in_the_architecture_table():
    page = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    for path in (ROOT / "warden").rglob("*.py"):
        name = ".".join(path.relative_to(ROOT).with_suffix("").parts).removesuffix(".__init__")
        assert f"`{name}`" in page, name


def test_one_version_everywhere():
    done = subprocess.run([sys.executable, "-m", "warden.cli", "--version"], capture_output=True, text=True,
                          cwd=str(ROOT), env={"PYTHONPATH": str(ROOT), "PATH": ""})
    assert done.stdout.strip() == f"warden {warden.__version__}"
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert not re.search(r'^version\s*=\s*"', pyproject, re.MULTILINE), "the version has one source: warden/__init__.py"
    assert 'attr = "warden.__version__"' in pyproject
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(warden.__version__)}\]", changelog, re.MULTILINE)
    assert f"`{warden.__version__}`" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_readme_states_no_test_count_that_could_drift():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert not re.search(r"\b\d[\d,]* tests (are|were|pass|collected)", readme), \
        "a test count in the README goes stale; say how to count them instead"
    assert "pytest --collect-only -q" in readme


def test_dependencies_and_ci_siblings_are_pinned_to_full_commits():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    git_deps = re.findall(r"git\+https://[^\"'\s]+", pyproject)
    assert len(git_deps) == 2
    for dep in git_deps:
        assert SHA.fullmatch(dep.rsplit("@", 1)[1]), dep
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    refs = re.findall(r"^\s+ref: (\S+)", workflow, re.MULTILINE)
    repos = re.findall(r"^\s+repository: (\S+)", workflow, re.MULTILINE)
    assert refs and all(SHA.fullmatch(r) for r in refs), refs
    assert len(repos) == len(refs) + 1          # the one unpinned sibling is the named non-blocking latest job
    assert "continue-on-error: true" in workflow


def test_ci_runs_the_gates_and_the_supported_pythons():
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    for needed in ("ruff check .", "mypy", 'python-version: ["3.11", "3.12", "3.13"]', "tools/circuit_smoke.py"):
        assert needed in workflow, needed
    assert "Programming Language :: Python :: 3.13" in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_the_readme_says_who_uses_the_horsemen_interface():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "--receipt" in readme and "Judge, Drafter and Burnish do not import" in readme


def test_no_document_uses_an_em_dash():
    for path in [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "docs").glob("*.md"))]:
        assert "\u2014" not in path.read_text(encoding="utf-8"), path.name


def test_the_two_assay_floor_defaults_are_the_documented_ones(tmp_path, monkeypatch, capsys):
    """The command line starts from floor 3 and the library from floor 0. That difference is on purpose, so it
    is written down (README, docs/EXIT_CODES.md) and asserted here: change either default and this fails."""
    import inspect

    from warden import cli, tagteam
    from warden.tagteam import TagTeam

    # the library: no floor unless the caller passes one
    assert inspect.signature(TagTeam.__init__).parameters["assay_floor"].default == 0 == tagteam.LIBRARY_ASSAY_FLOOR
    assert TagTeam().assay_floor == 0
    # the command line: 3, in the parser and in what reaches the run
    assert cli.CLI_ASSAY_FLOOR == 3
    seen = {}

    def spy(args, *rest, **kw):
        seen["floor"] = args.assay_floor
        return 0

    monkeypatch.setattr(cli, "_run_team", spy)
    assert cli.main(["tagteam", str(tmp_path)]) == 0 and seen["floor"] == 3
    assert cli.main(["tagteam", str(tmp_path), "--assay-floor", "0"]) == 0 and seen["floor"] == 0
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.main(["tagteam", "--help"])
    assert "(default 3)" in capsys.readouterr().out

    # the documents say so
    page = (ROOT / "docs" / "EXIT_CODES.md").read_text(encoding="utf-8")
    assert "| `warden tagteam` | `--assay-floor 3`" in page
    assert "| `TagTeam(...)` in the library | `assay_floor=0`" in page
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    assert "The default is 3 **on the command line only**" in readme
    assert "`TagTeam(assay_floor=...)` in the library defaults to `0`" in readme
