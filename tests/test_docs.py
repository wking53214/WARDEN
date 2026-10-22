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
        if "/CNS.git@" in dep:      # CNS is pinned by tag, see test_the_cns_pin_is_the_v2_0_0_tag_and_is_stated_in_stack
            continue
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


def _workflow() -> str:
    return (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")


def test_every_action_is_pinned_by_full_sha_with_its_tag_in_a_comment():
    uses = re.findall(r"^\s*- uses: (\S+)(.*)$", _workflow(), re.MULTILINE)
    assert uses
    for action, rest in uses:
        name, _, ref = action.partition("@")
        assert SHA.fullmatch(ref), f"{action} is not pinned by a full commit SHA"
        assert re.search(r"#\s*v\d+\.\d+\.\d+", rest), f"{action} has no tag comment"
    assert {a.partition("@")[0] for a, _ in uses} == {"actions/checkout", "actions/setup-python"}


def test_the_tested_set_is_the_same_everywhere_it_is_stated():
    """ghost_tools, SWIZZLE, ASSAY and JUDGE: the CI checkouts, the smoke test's --expect, the pip install of the
    Judge, the `ghost` extra, the header comment and STACK.md name one commit each."""
    workflow, stack = _workflow(), (ROOT / "STACK.md").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pins: dict[str, set[str]] = {"ghost_tools": set(), "SWIZZLE": set(), "ASSAY": set(), "JUDGE": set()}
    for repo, ref in re.findall(r"repository: wking53214/(\w+)\n\s+ref: (\w{40})", workflow):
        pins[repo].add(ref)
    for name, repo in (("ghost_tools", "ghost_tools"), ("swizzle", "SWIZZLE"), ("assay", "ASSAY")):
        pins[repo].update(re.findall(rf"--expect {name}=(\w{{40}})", workflow))
    pins["JUDGE"].update(re.findall(r"wking53214/JUDGE@(\w{40})", workflow))
    pins["ghost_tools"].update(re.findall(r"wking53214/ghost_tools@(\w{40})", pyproject))
    for repo, found in pins.items():
        assert len(found) == 1 and SHA.fullmatch(next(iter(found))), (repo, found)
        sha = next(iter(found))
        assert f"`{sha}`" in stack, f"STACK.md does not state {repo} {sha}"
        assert re.search(rf"^#\s+{repo}\s+\S+\s+{sha}$", workflow, re.MULTILINE), f"workflow header lacks {repo}"
    # Each pin is stated in the jobs that need it: the Judge in the pytest and circuit jobs, the rest in circuit.
    assert len(re.findall(r"wking53214/JUDGE@", workflow)) == 2
    assert workflow.count("repository: wking53214/ASSAY\n          ref:") == 2
    # The version written next to each pin is the version the repository declares at that commit (kept by hand).
    for repo, version in (("ghost_tools", "1.10.8"), ("SWIZZLE", "0.8.7"), ("ASSAY", "0.11.5"), ("JUDGE", "0.4.8")):
        assert re.search(rf"^\| {repo} \| {re.escape(version)} \|", stack, re.MULTILINE), (repo, version)
        assert re.search(rf"^#\s+{repo}\s+{re.escape(version)}\s", workflow, re.MULTILINE), (repo, version)


def test_the_cns_pin_is_the_v2_0_0_tag_and_is_stated_in_stack():
    """CNS is pinned by tag, spelled the same way in every repository of the circuit (CNS's seat_pins check compares
    the text, and pip treats a tag URL and a commit URL as two sources). STACK.md names the tag and the commit it
    peels to."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    stack = (ROOT / "STACK.md").read_text(encoding="utf-8")
    assert pyproject.count("cns @ git+https://github.com/wking53214/CNS.git@v2.0.0") == 1
    assert 'dependencies = ["cns @ git+https://github.com/wking53214/CNS.git@v2.0.0"]' in pyproject
    peeled = "b13e5d2f9e0e4291725f82794b89117c3d840ac1"
    assert re.search(rf"^\| CNS \| v2\.0\.0 \| `{peeled}` \|", stack, re.MULTILINE)


def test_the_tags_are_described_without_claiming_a_release_that_is_not_tagged():
    """Asserts the text only: it never needs the repository's tags to be present (a shallow CI checkout has none)."""
    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    changelog = " ".join((ROOT / "CHANGELOG.md").read_text(encoding="utf-8").split())
    # The docs say "0.13.x is not tagged"; a new minor series makes that stale, so this fails then and points at
    # the sentence to update.
    assert warden.__version__.startswith("0.13."), "update the tag sentence in README.md and CHANGELOG.md"
    for text in (readme, changelog):
        assert "Release tags exist up to `v0.12.0`" in text
        assert "`0.13.x` releases are not tagged" in text
        assert "last tag is `v0.11.4`" not in text and "newest tag is `v0.11.4`" not in text
        assert "`v0.10.0` tag does not match its tree" in text and "`__version__` is `0.9.0`" in text
        assert "owner's decision" in text


def test_the_markdown_code_fences_are_balanced_and_a_fence_ends_where_its_commands_end():
    """STACK.md once left the `bash` fence open through the paragraph that follows the command."""
    for name in ("README.md", "STACK.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        fences = [ln for ln in text.splitlines() if ln.startswith("```")]
        assert len(fences) % 2 == 0, f"{name} has an unclosed code fence"
    stack = (ROOT / "STACK.md").read_text(encoding="utf-8")
    start = stack.index("```bash\nwarden tagteam PATH --stack FOLDER")
    block = stack[start:stack.index("\n```\n", start + 3)]
    assert "A target that imports a sibling" not in block


def test_the_docs_say_assay_needs_matplotlibs_dependencies_installed():
    for name in ("README.md", "STACK.md"):
        text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
        assert "matplotlib's own dependencies (Pillow" in text and "56 of the" in text and "--no-deps" in text, name


def test_the_workflow_token_is_read_only():
    workflow = _workflow()
    top = workflow[:workflow.index("\njobs:")]
    assert re.search(r"^permissions:\n  contents: read$", top, re.MULTILINE)
    assert not re.search(r"^\s*(permissions|[a-z-]+): write\b", workflow, re.MULTILINE)


def test_no_document_tells_a_reader_to_install_a_bare_name_from_pypi():
    """`warden` and `cns` on PyPI are other projects, and so are the other names in this stack. A document may say
    not to install one (a line with "Do not"); it may not tell a reader to."""
    bare = re.compile(r"pip install\s+(?:-\S+\s+)*[\"']?(warden|cns|ghost[-_]tools|swizzle|assay|judge|drafter|burnish)"
                      r"\b(?!\s*@)")
    paths = [ROOT / "README.md", ROOT / "STACK.md", ROOT / "pyproject.toml", *sorted((ROOT / "docs").glob("*.md")),
             *sorted((ROOT / "warden").rglob("*.py")), *sorted((ROOT / "tools").glob("*.py"))]
    found = [f"{path.name}: {line.strip()[:80]}" for path in paths for line in path.read_text(encoding="utf-8").splitlines()
             if bare.search(line) and "Do not" not in line]
    assert not found, found
