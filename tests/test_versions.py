"""`versions` reads commits and version strings from files, and says None when it cannot."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from warden import versions


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(cwd)})


def _repo(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "one")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True,
                          check=True).stdout.strip()


def test_the_commit_and_version_of_a_checkout_are_read_without_running_git(tmp_path):
    sha = _repo(tmp_path)
    got = versions.instrument(tmp_path)
    assert got == {"path": str(tmp_path.resolve()), "commit": sha, "version": "1.2.3", "dirty": False}


def test_a_commit_is_found_from_packed_refs_and_from_a_subfolder(tmp_path):
    sha = _repo(tmp_path)
    _git(tmp_path, "pack-refs", "--all")
    (tmp_path / "sub").mkdir()
    assert versions.git_commit(tmp_path / "sub") == sha


def test_a_detached_head_is_read(tmp_path):
    sha = _repo(tmp_path)
    _git(tmp_path, "checkout", "-q", "--detach")
    assert versions.git_commit(tmp_path) == sha


def test_a_folder_that_is_not_a_checkout_reports_none_not_a_guess(tmp_path):
    got = versions.instrument(tmp_path)
    assert got["commit"] is None and got["version"] is None


def test_nothing_given_is_none():
    assert versions.instrument(None) is None
    assert versions.seat(None, object()) is None


def test_a_broken_pyproject_is_none(tmp_path):
    (tmp_path / "pyproject.toml").write_text("not [ toml", encoding="utf-8")
    assert versions.project_version(tmp_path) is None


# -- round 3: a root's own commit only, a dirty flag, and nothing borrowed from the target ----------

def test_a_folder_inside_someone_elses_repo_does_not_borrow_that_repos_commit(tmp_path):
    sha = _repo(tmp_path)
    inner = tmp_path / "vendored_instrument"
    inner.mkdir()
    (inner / "pyproject.toml").write_text('[project]\nname = "i"\nversion = "9.9.9"\n', encoding="utf-8")
    got = versions.instrument(inner)
    assert got["commit"] is None and got["dirty"] is None and got["version"] == "9.9.9"
    assert versions.instrument(tmp_path)["commit"] == sha


def test_dirty_is_true_when_the_checkout_has_uncommitted_work(tmp_path):
    _repo(tmp_path)
    (tmp_path / "scratch.txt").write_text("x", encoding="utf-8")
    assert versions.instrument(tmp_path)["dirty"] is True


def test_a_seat_in_the_target_never_reports_the_targets_commit(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "judgeseat_t.py").write_text("class J: requires_contract = '1'\n", encoding="utf-8")
    (target / "pyproject.toml").write_text('[project]\nname = "t"\nversion = "1.0.0"\n', encoding="utf-8")
    sha = _repo(target)
    import sys
    sys.path.insert(0, str(target))
    try:
        got = versions.seat("judgeseat_t:J", object(), target)
    finally:
        sys.path.remove(str(target))
        sys.modules.pop("judgeseat_t", None)
    assert sha and got["commit"] is None and got["dirty"] is None


# -- a version that is declared dynamic is read from its module's source, never by running it -----------

ASSAY_LIKE = '''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "assay"
dynamic = ["version"]

[tool.setuptools]
packages = ["assay_production"]

[tool.setuptools.dynamic]
version = { attr = "assay_production._version.__version__" }
'''


def _dynamic(tmp_path, source, *, pyproject=ASSAY_LIKE, module="assay_production/_version.py"):
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    path = tmp_path / module
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return tmp_path


def test_a_static_version_is_used_as_written_and_wins_over_a_dynamic_declaration(tmp_path):
    _dynamic(tmp_path, '__version__ = "9.9.9"\n', pyproject=ASSAY_LIKE.replace(
        'dynamic = ["version"]', 'version = "1.2.3"'))
    assert versions.project_version(tmp_path) == "1.2.3"


def test_a_dynamic_attr_version_is_read_from_the_module_like_assays(tmp_path):
    _dynamic(tmp_path, '"""The one place the version is written."""\n__version__ = "0.11.1"\n')
    assert versions.project_version(tmp_path) == "0.11.1"
    assert versions.instrument(tmp_path)["version"] == "0.11.1"


def test_the_version_module_is_read_not_run(tmp_path):
    marker = tmp_path / "ran.txt"
    _dynamic(tmp_path, f'open({str(marker)!r}, "w").write("executed")\nraise SystemExit(3)\n__version__ = "1.0.0"\n')
    assert versions.project_version(tmp_path) == "1.0.0"
    assert not marker.exists()


def test_an_attr_that_names_a_package_or_a_src_layout_is_found(tmp_path):
    pyproject = ASSAY_LIKE.replace("assay_production._version.__version__", "pkg.__version__")
    _dynamic(tmp_path, '__version__ = "2.0.0"\n', pyproject=pyproject, module="pkg/__init__.py")
    assert versions.project_version(tmp_path) == "2.0.0"
    other = tmp_path / "srcdir"
    other.mkdir()
    _dynamic(other, '__version__ = "3.0.0"\n', module="src/assay_production/_version.py")
    assert versions.project_version(other) == "3.0.0"


@pytest.mark.parametrize("source", [
    '__version__ = get_version()\n',                       # a call: would need running it
    'import os\n__version__ = os.environ["V"]\n',          # a lookup
    '__version__ = f"{MAJOR}.1"\n',                        # an f-string
    '__version__ = "1." + "2"\n',                          # an expression, not a literal
    '__version__ = 1.2\n',                                 # not a string
    '__version__ = ("1", "2")\n',                          # a tuple
    '__version__ = ""\n',                                  # empty
    '__version__: str = "1.0"\n',                          # annotated assignment is not the plain form
    '__version__ = "1.0"\n__version__ += ".1"\n',          # changed afterwards
    '__version__ = "1.0"\n__version__ = "2.0"\n',          # two different answers
    '__version__ = other = "1.0"\n',                       # chained assignment
    'if True:\n    __version__ = "1.0"\n',                 # not at the top level
    'VERSION = "1.0"\n',                                   # the named attribute is absent
    '__version__ = \n',                                    # does not parse
    '\x00',                                                # not source at all
    '',                                                    # empty file
])
def test_a_dynamic_version_that_is_not_a_plain_string_literal_is_none_not_a_guess(tmp_path, source):
    _dynamic(tmp_path, source)
    assert versions.project_version(tmp_path) is None


@pytest.mark.parametrize("pyproject", [
    ASSAY_LIKE.replace('dynamic = ["version"]', 'dynamic = ["readme"]'),                 # version not declared dynamic
    ASSAY_LIKE.replace('{ attr = "assay_production._version.__version__" }', '{ file = "VERSION" }'),
    ASSAY_LIKE.replace("assay_production._version.__version__", "__version__"),           # no module part
    ASSAY_LIKE.replace("assay_production._version.__version__", "assay_production/../x.__version__"),
    ASSAY_LIKE.replace("assay_production._version.__version__", "..evil.__version__"),
    ASSAY_LIKE.replace('{ attr = "assay_production._version.__version__" }', '"assay_production._version"'),
    ASSAY_LIKE.replace('{ attr = "assay_production._version.__version__" }', '{ attr = 7 }'),
    ASSAY_LIKE.replace("[tool.setuptools.dynamic]", "[tool.something.else]"),
])
def test_a_dynamic_declaration_that_cannot_be_followed_is_none(tmp_path, pyproject):
    _dynamic(tmp_path, '__version__ = "1.0.0"\n', pyproject=pyproject)
    assert versions.project_version(tmp_path) is None


def test_a_version_module_that_is_missing_or_a_link_out_of_the_checkout_is_none(tmp_path):
    (tmp_path / "pyproject.toml").write_text(ASSAY_LIKE, encoding="utf-8")
    assert versions.project_version(tmp_path) is None
    outside = tmp_path / "outside.py"
    outside.write_text('__version__ = "6.6.6"\n', encoding="utf-8")
    checkout = tmp_path / "checkout"
    (checkout / "assay_production").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text(ASSAY_LIKE, encoding="utf-8")
    (checkout / "assay_production" / "_version.py").symlink_to(outside)
    assert versions.project_version(checkout) is None


def test_a_huge_version_module_is_not_read(tmp_path):
    _dynamic(tmp_path, '__version__ = "1.0.0"\n' + "# pad\n" * 60000)
    assert versions.project_version(tmp_path) is None


@pytest.mark.skipif(not os.environ.get("ASSAY_ROOT"), reason="set ASSAY_ROOT to an ASSAY checkout")
def test_the_live_assay_checkout_reports_the_version_it_documents():
    """ASSAY's version is dynamic. Its documented way to read it is importing the package; Warden's static
    reading must agree with that, and must not need to import it."""
    root = os.environ["ASSAY_ROOT"]
    done = subprocess.run([sys.executable, "-P", "-c", "import assay_production; print(assay_production.__version__)"],
                          capture_output=True, text=True, check=True, env={"PYTHONPATH": root, "PATH": ""})
    assert versions.project_version(Path(root)) == done.stdout.strip() != ""
