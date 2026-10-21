"""A named instrument root is the one that runs, or the run fails closed: an installed copy never stands in.

Warden drops PYTHONPATH when it starts an instrument, but the interpreter's site-packages stays importable.
Before this, `--ghost-root /nonexistent` with Ghost Tools installed in the same environment scanned with the
installed copy ("Ghost Tools observed 0 finding(s)"), and `--swizzle-root /nonexistent/swz` with SWIZZLE
installed reported "12 of 12 proofs hold" for a root that is not there.

These tests give the interpreter a real installed copy of each instrument: a throwaway virtual environment
whose site-packages holds a stand-in `ghost_buster`, `swizzle` and `assay_production`. A root that is missing,
is not a directory, holds no such package, or holds one that resolves elsewhere must be refused for each of
the three, on the library's functions and on the command line; a good checkout must still be the one that runs,
installed copy or not.

A root that IS the installed copy is the harder case: `--ghost-root $VENV/lib/python3.13/site-packages` holds a real
`ghost_buster`, resolves under itself, and used to run (with commit and version null in the record) and, with a
rubber-stamp Judge, end in ACCEPT. A root that is, or lies inside, site-packages (or is a link to it) is refused,
and so is a plain copy of the package with no git commit or no version of its own, unless the caller opts in; then
the run says so and is never a plain ACCEPT.
"""

from __future__ import annotations

import json
import os
import subprocess
import venv
from pathlib import Path

import pytest

import cns
from warden import versions
from warden.ghost import scan
from warden.isolation import InstrumentRootError, locate_module, run_instrument, verify_root
from warden.swizzle import assay_score, governor_attacks, swizzle_contract_holds, swizzle_proofs_hold
from warden.tagteam import TagTeam

from fakes import FakeDrafter, FakeJudge
from gitutil import commit_all
from test_judge_seat import _auth, _repo
from test_stack_option import _stack, _repo as _stack_target

REPO_ROOT = Path(__file__).resolve().parents[1]
CNS_DIR = Path(cns.__file__).resolve().parents[1]

INSTALLED_PROOFS, ROOT_PROOFS = 7, 3
INSTALLED_FILES, ROOT_FILES = 7, 11


def _swizzle_cli(proofs: int) -> str:
    return f'''
import json, sys
args = sys.argv[1:]
if args == ["--contract"]:
    print(json.dumps({{"name": "swizzle", "contract": 1, "swizzle_version": "0"}}))
elif args[:1] == ["prove"]:
    print("{proofs} of {proofs} proofs hold.")
elif args[:1] == ["governor"]:
    print(json.dumps([{{"scenario": "s{proofs}", "severity": "high", "status": "held"}}]))
elif args[:1] == ["assay"]:
    print(json.dumps({{"judgements": [{{"specimen_class": "FAILURE_MODE", "outcome": "banished"}}],
                       "proof": "{proofs} claims hold"}}))
else:
    raise SystemExit(2)
'''


def _ghost_cli(files: int) -> str:
    """A clean Ghost report; the number of files it says it scanned tells which copy answered."""
    return (f'import json\nprint(json.dumps({{"findings": [], "status": "ok", "unmeasured": [], "scan": '
            f'{{"files_scanned": {files}, "files_skipped": 0, "files_unparsable": 0}}}}))\n')


def _write_instruments(base: Path, proofs: int, files: int) -> None:
    """Stand-ins for the three instruments' packages under `base` (a checkout root or a site-packages)."""
    files = {
        "ghost_buster/__init__.py": "", "ghost_buster/cli.py": _ghost_cli(files),
        "swizzle/__init__.py": "", "swizzle/cli.py": _swizzle_cli(proofs),
        "assay_production/__init__.py": "",
    }
    for name, text in files.items():
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture(scope="session")
def installed_python(tmp_path_factory) -> str:
    """A Python whose own site-packages holds an INSTALLED copy of every instrument, as `pip install` leaves it."""
    home = tmp_path_factory.mktemp("venv-with-instruments")
    venv.create(home, with_pip=False, symlinks=True)
    exe = home / "bin" / "python"
    purelib = subprocess.run([str(exe), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                             capture_output=True, text=True, check=True).stdout.strip()
    _write_instruments(Path(purelib), INSTALLED_PROOFS, INSTALLED_FILES)
    return str(exe)


@pytest.fixture
def checkout(tmp_path) -> Path:
    """A good checkout of all three instruments: a git repository with a version that holds each package."""
    root = tmp_path / "checkout"
    _write_instruments(root, ROOT_PROOFS, ROOT_FILES)
    (root / "pyproject.toml").write_text('[project]\nname = "stand-in"\nversion = "1.2.3"\n', encoding="utf-8")
    commit_all(root)
    return root


@pytest.fixture
def plain_copy(tmp_path) -> Path:
    """The same packages copied into an ordinary folder: no git, no pyproject, so no commit and no version."""
    root = tmp_path / "plain_copy"
    _write_instruments(root, ROOT_PROOFS, ROOT_FILES)
    return root


def _missing(tmp_path) -> Path:
    return tmp_path / "nowhere" / "swz"


def _a_file(tmp_path) -> Path:
    path = tmp_path / "just_a_file"
    path.write_text("x", encoding="utf-8")
    return path


def _empty_dir(tmp_path) -> Path:
    path = tmp_path / "etc_like"
    path.mkdir()
    (path / "passwd").write_text("root:x:0:0\n", encoding="utf-8")
    return path


def _without_init(tmp_path) -> Path:
    path = tmp_path / "no_init"
    for package in ("ghost_buster", "swizzle", "assay_production"):
        (path / package).mkdir(parents=True)
    return path


def _symlink_to(tmp_path, target: Path) -> Path:
    link = tmp_path / "link_to_site_packages"
    link.symlink_to(target, target_is_directory=True)
    return link


def _plain_copy(tmp_path) -> Path:
    root = tmp_path / "plain_copy_bad"
    _write_instruments(root, ROOT_PROOFS, ROOT_FILES)
    return root


def _link_to_installed(tmp_path, installed_python) -> Path:
    """A root whose packages are links to the installed copies: they resolve, but not under the root."""
    purelib = Path(subprocess.run([installed_python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                                  capture_output=True, text=True, check=True).stdout.strip())
    path = tmp_path / "linked"
    path.mkdir()
    for package in ("ghost_buster", "swizzle", "assay_production"):
        (path / package).symlink_to(purelib / package, target_is_directory=True)
    return path


def _purelib(installed_python) -> Path:
    return Path(subprocess.run([installed_python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                               capture_output=True, text=True, check=True).stdout.strip())


def _inside_site_packages(installed_python) -> Path:
    """A folder inside site-packages that holds a copy of every package."""
    inner = _purelib(installed_python) / "a_copy_inside"
    _write_instruments(inner, ROOT_PROOFS, ROOT_FILES)
    return inner


BAD_ROOTS = ["missing", "a_file", "dir_without_the_package", "package_without_init", "links_to_the_installed_copy",
             "site_packages_itself", "inside_site_packages", "symlink_to_site_packages", "plain_copy_not_git"]


@pytest.fixture
def bad_root(request, tmp_path, installed_python):
    return {"missing": lambda: _missing(tmp_path), "a_file": lambda: _a_file(tmp_path),
            "dir_without_the_package": lambda: _empty_dir(tmp_path),
            "package_without_init": lambda: _without_init(tmp_path),
            "links_to_the_installed_copy": lambda: _link_to_installed(tmp_path, installed_python),
            "site_packages_itself": lambda: _purelib(installed_python),
            "inside_site_packages": lambda: _inside_site_packages(installed_python),
            "symlink_to_site_packages": lambda: _symlink_to(tmp_path, _purelib(installed_python)),
            "plain_copy_not_git": lambda: _plain_copy(tmp_path)}[request.param]()


PACKAGES = ["ghost_buster", "swizzle", "assay_production"]


# -- the check itself ------------------------------------------------------------------------------

def test_the_installed_copy_is_really_there(installed_python):
    """Sanity: without a root the interpreter finds the installed copies, which is the thing being kept out."""
    for package in PACKAGES:
        found = locate_module(package, None, python=installed_python)
        assert found is not None and "site-packages" in found.parts


@pytest.mark.parametrize("bad_root", BAD_ROOTS, indirect=True)
@pytest.mark.parametrize("package", PACKAGES)
def test_a_bad_root_is_refused_although_the_package_is_installed(package, bad_root, installed_python):
    with pytest.raises(InstrumentRootError) as err:
        verify_root(package, bad_root, python=installed_python)
    assert err.value.package == package and "Nothing was run" in str(err.value)


@pytest.mark.parametrize("package", PACKAGES)
def test_no_root_at_all_is_refused_rather_than_using_the_installed_copy(package, installed_python):
    with pytest.raises(InstrumentRootError):
        verify_root(package, None, python=installed_python)


@pytest.mark.parametrize("package", PACKAGES)
def test_a_good_root_wins_over_the_installed_copy(package, checkout, installed_python):
    found = verify_root(package, checkout, python=installed_python)
    assert found == (checkout / package / "__init__.py").resolve()


def test_a_relative_root_is_made_absolute_before_it_is_checked(checkout, installed_python, monkeypatch):
    monkeypatch.chdir(checkout.parent)
    assert verify_root("swizzle", Path("checkout"), python=installed_python).is_relative_to(checkout.resolve())


def test_run_instrument_refuses_before_running_anything(tmp_path, installed_python):
    marker = tmp_path / "ran"
    cmd = [installed_python, "-c", f"open({str(marker)!r}, 'w').write('x')"]
    with pytest.raises(InstrumentRootError):
        run_instrument(cmd, roots=[_missing(tmp_path)], timeout=30, packages={"ghost_buster": _missing(tmp_path)})
    assert not marker.exists()


# -- Ghost Tools -----------------------------------------------------------------------------------

@pytest.mark.parametrize("bad_root", BAD_ROOTS, indirect=True)
def test_a_scan_with_a_bad_ghost_root_fails_although_ghost_is_installed(bad_root, tmp_path, installed_python):
    with pytest.raises(InstrumentRootError):
        scan(tmp_path, ghost_tools_root=bad_root, python=installed_python)


def test_a_scan_with_no_ghost_root_fails_although_ghost_is_installed(tmp_path, installed_python):
    with pytest.raises(InstrumentRootError):
        scan(tmp_path, python=installed_python)


def test_a_scan_with_a_good_ghost_root_runs_that_checkout_not_the_installed_copy(checkout, tmp_path, installed_python):
    found = scan(tmp_path, ghost_tools_root=checkout, python=installed_python)
    assert found.scan_counts["files_scanned"] == ROOT_FILES


# -- SWIZZLE ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad_root", BAD_ROOTS, indirect=True)
def test_a_bad_swizzle_root_proves_nothing_although_swizzle_is_installed(bad_root, installed_python):
    holds, why = swizzle_contract_holds(swizzle_root=bad_root, python=installed_python)
    assert holds is False and "SWIZZLE contract not confirmed" in why
    holds, why = swizzle_proofs_hold(swizzle_root=bad_root, python=installed_python)
    assert holds is False and f"{INSTALLED_PROOFS} of {INSTALLED_PROOFS}" not in why
    holds, why = swizzle_proofs_hold(swizzle_root=bad_root, python=installed_python, check_contract=False)
    assert holds is False and "SWIZZLE proofs could not run" in why and "Nothing was run" in why


@pytest.mark.parametrize("bad_root", BAD_ROOTS, indirect=True)
def test_attacks_on_the_governor_are_not_measured_with_a_bad_swizzle_root(bad_root, installed_python, tmp_path):
    notes: list[str] = []
    assert governor_attacks(swizzle_root=bad_root, warden_root=tmp_path, python=installed_python, note=notes) is None
    assert notes and "not measured" in notes[0] and "Nothing was run" in notes[0]


def test_a_good_swizzle_root_is_the_one_that_proves_and_attacks(checkout, installed_python, tmp_path):
    assert swizzle_proofs_hold(swizzle_root=checkout, python=installed_python) == (
        True, f"SWIZZLE proofs: {ROOT_PROOFS} of {ROOT_PROOFS} proofs hold.")
    got = governor_attacks(swizzle_root=checkout, warden_root=tmp_path, python=installed_python)
    assert got is not None and got[0]["scenario"] == f"s{ROOT_PROOFS}"


# -- ASSAY (graded by SWIZZLE, which is handed ASSAY's and Ghost's roots) --------------------------

@pytest.mark.parametrize("bad_root", BAD_ROOTS, indirect=True)
def test_grading_with_a_bad_assay_root_fails_closed_although_assay_is_installed(bad_root, checkout, installed_python):
    state, score, why = assay_score(swizzle_root=checkout, assay_root=bad_root, python=installed_python)
    assert state is False and score == {} and "Nothing was run" in why


@pytest.mark.parametrize("bad_root", BAD_ROOTS, indirect=True)
def test_grading_with_a_bad_ghost_root_fails_closed_although_ghost_is_installed(bad_root, checkout, installed_python):
    state, score, why = assay_score(swizzle_root=checkout, assay_root=checkout, ghost_root=bad_root,
                                    python=installed_python)
    assert state is False and score == {} and "Nothing was run" in why


@pytest.mark.parametrize("bad_root", BAD_ROOTS, indirect=True)
def test_grading_with_a_bad_swizzle_root_does_not_run_at_all(bad_root, checkout, installed_python):
    state, score, why = assay_score(swizzle_root=bad_root, assay_root=checkout, python=installed_python)
    assert state is None and score == {} and "could not run" in why


def test_grading_with_good_roots_still_works(checkout, installed_python):
    state, score, _ = assay_score(swizzle_root=checkout, assay_root=checkout, ghost_root=checkout,
                                  python=installed_python)
    assert state is True and score["caught"] == 1 and score["proof"] == f"{ROOT_PROOFS} claims hold"


# -- the whole run ---------------------------------------------------------------------------------

@pytest.fixture
def suite_can_import_pytest(monkeypatch):
    """The target's own suite runs with the interpreter given as `python=` (the venv with no pytest in it). The suite,
    unlike an instrument, keeps the caller's PYTHONPATH, so pointing it at this environment's packages lets it run."""
    import sysconfig
    monkeypatch.setenv("PYTHONPATH", sysconfig.get_paths()["purelib"])


def _target(tmp_path) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    _repo(target)
    commit_all(target)
    return target


def test_a_run_with_a_bad_assay_root_stops_inconclusive_and_writes_nothing(tmp_path, checkout, installed_python):
    target = _target(tmp_path)
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), ghost_tools_root=checkout, swizzle_root=checkout,
                   assay_root=_missing(tmp_path))
    result = team.run(target, authorization=_auth(target), findings=[], python=installed_python)
    assert result.decision == "INCONCLUSIVE" and "answer key could not be used" in result.reason
    assert "assay" in result.unmeasured
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_a_run_with_a_bad_ghost_root_stops_inconclusive_with_ghost_unmeasured(tmp_path, checkout, installed_python):
    target = _target(tmp_path)
    team = TagTeam(drafter=FakeDrafter(steps=("new\n",)), ghost_tools_root=_missing(tmp_path))
    result = team.run(target, authorization=_auth(target), python=installed_python)
    assert result.decision == "INCONCLUSIVE" and "ghost" in result.unmeasured
    assert "does not exist" in result.reason and not any("observed" in n for n in result.notes)


# -- the command line, as the audit reproduced it ----------------------------------------------------

def _warden(installed_python, tmp_path, *args):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT), str(CNS_DIR)]), HOME=str(home),
               XDG_STATE_HOME=str(home / "state"))
    env.pop("WARDEN_LOG_LEVEL", None)
    done = subprocess.run([installed_python, "-m", "warden.cli", *map(str, args)], capture_output=True, text=True,
                          env=env, cwd=str(tmp_path), timeout=300)
    try:
        return done.returncode, json.loads(done.stdout), done.stderr
    except ValueError:
        pytest.fail(f"stdout was not JSON:\n{done.stdout!r}\n{done.stderr[-600:]}")


@pytest.mark.parametrize("where", ["missing", "etc_like"])
def test_cli_ghost_root_that_is_not_ghost_does_not_scan_with_the_installed_copy(where, tmp_path, installed_python):
    target = _target(tmp_path)
    root = _missing(tmp_path) if where == "missing" else _empty_dir(tmp_path)
    code, out, _ = _warden(installed_python, tmp_path, "tagteam", target, "--ghost-root", root)
    assert out["decision"] == "INCONCLUSIVE" and code == 6
    assert "ghost" in out["unmeasured"]
    assert not any("Ghost Tools observed" in n for n in out["notes"])
    ghost = out["versions"]["ghost_tools"]
    assert ghost["module_in_root"] is False and "site-packages" in ghost["module"]


def test_cli_swizzle_root_that_is_not_there_does_not_prove_with_the_installed_copy(tmp_path, installed_python):
    target = _target(tmp_path)
    code, out, _ = _warden(installed_python, tmp_path, "tagteam", target, "--swizzle-root", _missing(tmp_path))
    assert out["swizzle_sound"] is False and code == 2 and "swizzle" in out["unmeasured"]
    assert not any("proofs hold" in n for n in out["notes"])
    assert out["versions"]["swizzle"]["module_in_root"] is False


def test_cli_assay_root_that_is_not_there_is_not_graded_with_the_installed_copy(tmp_path, checkout, installed_python):
    target = _target(tmp_path)
    code, out, _ = _warden(installed_python, tmp_path, "tagteam", target, "--swizzle-root", checkout,
                           "--assay-root", _missing(tmp_path))
    assert "assay" in out["unmeasured"]
    assert any("ASSAY grading failed" in n and "Nothing was run" in n for n in out["notes"])
    assert out["versions"]["assay"]["module_in_root"] is False


def test_cli_good_roots_are_the_ones_used_and_the_record_says_where_they_loaded_from(tmp_path, checkout,
                                                                                      installed_python):
    target = _target(tmp_path)
    code, out, _ = _warden(installed_python, tmp_path, "tagteam", target, "--ghost-root", checkout,
                           "--swizzle-root", checkout, "--assay-root", checkout)
    assert out["swizzle_sound"] is True
    assert any(f"{ROOT_PROOFS} of {ROOT_PROOFS} proofs hold" in n for n in out["notes"])
    assert "assay" not in out["unmeasured"] and "ghost" not in out["unmeasured"]
    for name, package in (("ghost_tools", "ghost_buster"), ("swizzle", "swizzle"), ("assay", "assay_production")):
        entry = out["versions"][name]
        assert entry["module_in_root"] is True
        assert Path(entry["module"]) == (checkout / package / "__init__.py").resolve()


def test_cli_stack_folders_that_are_not_checkouts_fail_closed(tmp_path, installed_python):
    target = _stack_target(tmp_path / "t")
    commit_all(target)
    stack = _stack(tmp_path / "stack")      # ghost_tools, swizzle and assay are empty folders
    code, out, _ = _warden(installed_python, tmp_path, "tagteam", target, "--stack", stack)
    assert out["decision"] == "INCONCLUSIVE" and out["swizzle_sound"] is False and code == 2
    assert {"ghost", "swizzle", "assay"} <= set(out["unmeasured"])
    assert any("SWIZZLE contract not confirmed" in n for n in out["notes"])
    assert not any("Ghost Tools observed" in n or "proofs hold" in n for n in out["notes"])
    for name in ("ghost_tools", "swizzle", "assay"):
        assert out["versions"][name]["module_in_root"] is False


def test_cli_audit_with_a_bad_ghost_root_reads_nothing_from_the_installed_copy(tmp_path, installed_python):
    target = _target(tmp_path)
    done = subprocess.run(
        [installed_python, "-m", "warden.cli", "audit", str(target), "--ghost-root", str(_missing(tmp_path))],
        capture_output=True, text=True, cwd=str(tmp_path), timeout=300,
        env=dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT), str(CNS_DIR)]), HOME=str(tmp_path)))
    assert done.returncode == 2 and done.stdout == "" and "could not be read" in done.stderr


# -- the version in the record ---------------------------------------------------------------------

def test_the_record_names_the_module_an_instrument_loaded_from(checkout):
    got = versions.instrument(checkout, "swizzle")
    assert got["module"] == str((checkout / "swizzle" / "__init__.py").resolve()) and got["module_in_root"] is True
    assert "module" not in versions.instrument(checkout)          # without a package nothing about it is claimed



# -- the audit's case: the installed copy named as the root ------------------------------------------

class _Stamp(FakeJudge):
    """A rubber-stamp Judge: ACCEPT whatever it is shown."""


def _full_team(tmp_path, ghost, swizzle, assay, judge=None, **kw):
    return TagTeam(drafter=FakeDrafter(steps=("one\n",)), judge=judge or _Stamp("ACCEPT"), ghost_tools_root=ghost,
                   swizzle_root=swizzle, assay_root=assay, assay_floor=1, **kw)


def test_the_audits_run_with_site_packages_as_both_roots_is_not_an_accept(tmp_path, checkout, installed_python):
    """--ghost-root SITE --swizzle-root SITE --assay-root <real ASSAY> with a rubber-stamp Judge: it used to be an
    ACCEPT, exit 0, nothing unmeasured, with commit and version null in the record."""
    site = _purelib(installed_python)
    target = _target(tmp_path)
    result = _full_team(tmp_path, site, site, checkout).run(
        target, authorization=_auth(target), findings=[], python=installed_python)
    assert result.decision == "INCONCLUSIVE" and result.swizzle_sound is False
    assert "installed copy" in " ".join(result.notes)
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "old\n"


def test_a_good_checkout_with_a_rubber_stamp_judge_is_still_a_plain_accept(tmp_path, checkout, installed_python, suite_can_import_pytest):
    """The control: the same run with real checkouts is unchanged (nothing here weakens a good path)."""
    target = _target(tmp_path)
    result = _full_team(tmp_path, checkout, checkout, checkout).run(
        target, authorization=_auth(target), python=installed_python)
    assert result.decision == "ACCEPT" and result.unmeasured == (), (result.decision, result.reason, result.notes)


def test_a_plain_copy_is_refused_by_default_and_never_a_plain_accept_when_allowed(
        tmp_path, plain_copy, installed_python, suite_can_import_pytest):
    target = _target(tmp_path)
    refused = _full_team(tmp_path, plain_copy, plain_copy, plain_copy).run(
        target, authorization=_auth(target), python=installed_python)
    assert refused.decision == "INCONCLUSIVE" and refused.swizzle_sound is False
    assert (target / "NOTE.md").read_text(encoding="utf-8") == "old\n"
    allowed = _full_team(tmp_path, plain_copy, plain_copy, plain_copy, allow_uncommitted_instruments=True).run(
        target, authorization=_auth(target), python=installed_python)
    assert allowed.decision == "ACCEPT_UNVERIFIED", (allowed.decision, allowed.reason)
    assert "instrument_provenance" in allowed.unmeasured and allowed.swizzle_sound is True
    assert any("--allow-uncommitted-instruments" in n for n in allowed.notes)


def test_the_flag_does_not_open_site_packages(tmp_path, installed_python, checkout):
    site = _purelib(installed_python)
    target = _target(tmp_path)
    result = _full_team(tmp_path, site, site, site, allow_uncommitted_instruments=True).run(
        target, authorization=_auth(target), findings=[], python=installed_python)
    assert result.decision == "INCONCLUSIVE" and result.swizzle_sound is False


@pytest.mark.parametrize("bad_root", ["site_packages_itself", "inside_site_packages", "symlink_to_site_packages"],
                         indirect=True)
@pytest.mark.parametrize("package", PACKAGES)
def test_an_installed_location_is_refused_even_when_uncommitted_roots_are_allowed(package, bad_root,
                                                                                installed_python):
    with pytest.raises(InstrumentRootError) as err:
        verify_root(package, bad_root, python=installed_python, allow_uncommitted=True)
    assert "installed copy" in str(err.value)


@pytest.mark.parametrize("package", PACKAGES)
def test_a_plain_copy_runs_only_when_allowed(package, plain_copy, installed_python):
    with pytest.raises(InstrumentRootError) as err:
        verify_root(package, plain_copy, python=installed_python)
    assert "git commit" in str(err.value) and "version" in str(err.value) and "--allow-uncommitted" in str(err.value)
    assert verify_root(package, plain_copy, python=installed_python, allow_uncommitted=True).is_relative_to(
        plain_copy.resolve())


def test_a_checkout_with_a_commit_but_no_version_or_a_version_but_no_commit_is_not_enough(tmp_path, installed_python):
    only_commit = tmp_path / "only_commit"
    _write_instruments(only_commit, ROOT_PROOFS, ROOT_FILES)
    commit_all(only_commit)
    only_version = tmp_path / "only_version"
    _write_instruments(only_version, ROOT_PROOFS, ROOT_FILES)
    (only_version / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0"\n', encoding="utf-8")
    for root, missing in ((only_commit, "version"), (only_version, "git commit")):
        with pytest.raises(InstrumentRootError) as err:
            verify_root("swizzle", root, python=installed_python)
        assert missing in str(err.value)


def test_a_checkout_installed_in_editable_mode_is_still_a_checkout(checkout, tmp_path):
    """A real checkout whose folder is also on the path (pip install -e) is not an 'installed copy'."""
    venv_dir = tmp_path / "editable-venv"
    venv.create(venv_dir, with_pip=False, symlinks=True)
    exe = str(venv_dir / "bin" / "python")
    purelib = _purelib(exe)
    (purelib / "editable.pth").write_text(str(checkout) + "\n", encoding="utf-8")
    assert verify_root("swizzle", checkout, python=exe).is_relative_to(checkout.resolve())


def test_cli_a_plain_copy_is_refused_without_the_flag_and_recorded_with_it(tmp_path, plain_copy, installed_python):
    target = _target(tmp_path)
    code, out, _ = _warden(installed_python, tmp_path, "tagteam", target, "--swizzle-root", plain_copy)
    assert out["swizzle_sound"] is False and code == 2 and out["allow_uncommitted_instruments"] is False
    code, out, _ = _warden(installed_python, tmp_path, "tagteam", target, "--swizzle-root", plain_copy,
                           "--ghost-root", plain_copy, "--assay-root", plain_copy,
                           "--allow-uncommitted-instruments")
    assert out["swizzle_sound"] is True and out["allow_uncommitted_instruments"] is True
    assert "instrument_provenance" in out["unmeasured"] and out["decision"] != "ACCEPT"
    assert any("--allow-uncommitted-instruments" in n for n in out["notes"])


def test_cli_site_packages_as_a_root_is_refused_with_the_flag_too(tmp_path, installed_python):
    site = _purelib(installed_python)
    target = _target(tmp_path)
    for extra in ((), ("--allow-uncommitted-instruments",)):
        code, out, _ = _warden(installed_python, tmp_path, "tagteam", target, "--ghost-root", site,
                               "--swizzle-root", site, "--assay-root", site, *extra)
        assert out["swizzle_sound"] is False and code == 2 and out["decision"] == "INCONCLUSIVE"
        assert out["versions"]["swizzle"]["commit"] is None      # the record never claimed a checkout


# -- smaller findings of the same audit -------------------------------------------------------------

def test_a_bad_ghost_root_beside_a_good_swizzle_still_says_whether_the_proofs_held(tmp_path, checkout,
                                                                                     installed_python):
    """swizzle_sound used to be null here although the notes said the proofs held; it is the proofs' answer, and the
    Ghost failure is recorded separately (decision, reason, unmeasured)."""
    target = _target(tmp_path)
    code, out, _ = _warden(installed_python, tmp_path, "tagteam", target, "--swizzle-root", checkout,
                           "--ghost-root", _missing(tmp_path))
    assert out["swizzle_sound"] is True
    assert any("proofs hold" in n for n in out["notes"])
    assert out["decision"] == "INCONCLUSIVE" and "ghost" in out["unmeasured"] and "swizzle" not in out["unmeasured"]
    assert "Ghost" in out["reason"] and code == 6
