"""tools/circuit_smoke.py runs Warden from a temporary folder, so every root it is given must be absolute.

CI passes relative roots (`--ghost-tools _circuit/ghost_tools ...`); before the roots were resolved at parse time,
that job failed on GitHub ("SWIZZLE's own proofs hold") while passing locally with absolute paths.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _smoke():
    spec = importlib.util.spec_from_file_location("circuit_smoke", ROOT / "tools" / "circuit_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def relative_roots(tmp_path, monkeypatch):
    for name in ("ghost_tools", "SWIZZLE", "ASSAY"):
        (tmp_path / "_circuit" / name).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return ["--ghost-tools", "_circuit/ghost_tools", "--swizzle", "_circuit/SWIZZLE", "--assay", "_circuit/ASSAY"]


def test_relative_roots_become_absolute_when_the_arguments_are_parsed(tmp_path, relative_roots):
    args = _smoke().parse_args([*relative_roots, "--real-judge"])
    expected = {"ghost_tools": "ghost_tools", "swizzle": "SWIZZLE", "assay": "ASSAY"}
    for attr, folder in expected.items():
        value = getattr(args, attr)
        assert value.is_absolute() and value == (tmp_path / "_circuit" / folder).resolve()


def test_dot_dot_and_home_forms_are_resolved_too(tmp_path, monkeypatch):
    (tmp_path / "a" / "b").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "a" / "b")
    monkeypatch.setenv("HOME", str(tmp_path))
    args = _smoke().parse_args(["--ghost-tools", "../b", "--swizzle", "~/a", "--assay", "."])
    assert args.ghost_tools == args.assay == (tmp_path / "a" / "b").resolve()
    assert args.swizzle == (tmp_path / "a").resolve()


def test_a_root_that_is_not_a_folder_is_a_usage_error(tmp_path, relative_roots, capsys):
    with pytest.raises(SystemExit) as stop:
        _smoke().parse_args(["--ghost-tools", "nowhere", *relative_roots[2:]])
    assert stop.value.code == 2 and "not a directory" in capsys.readouterr().err


def test_an_expect_that_is_not_a_name_and_a_full_sha_is_a_usage_error(relative_roots):
    with pytest.raises(SystemExit):
        _smoke().parse_args([*relative_roots, "--expect", "ghost_tools=abc"])
    with pytest.raises(SystemExit):
        _smoke().parse_args([*relative_roots, "--expect", "other=" + "a" * 40])


def test_the_paths_handed_to_warden_are_absolute_although_the_command_line_was_relative(relative_roots):
    """main() with relative roots: the first Warden command line it builds names every instrument root absolutely."""
    smoke = _smoke()
    seen = []

    def stop_at_first_run(args, base, seats):
        seen.append((list(args), base))
        raise smoke.Failed("stop here, the argument handling is all this test is about")

    smoke.run_warden = stop_at_first_run
    with pytest.raises(smoke.Failed):
        smoke.main([*relative_roots])
    (argv, base), = seen
    for flag in ("--ghost-root", "--swizzle-root", "--assay-root"):
        value = Path(argv[argv.index(flag) + 1])
        assert value.is_absolute() and value.is_dir(), (flag, value)
        assert not value.is_relative_to(base)
