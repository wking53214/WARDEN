"""The files a suite says are its own are named to the Judge, whatever they are called.

Protecting tests by name misses a project that keeps them in `checks/` or compares against a plain data file. The suite
run itself says which files hold its tests and which data it read. An applied edit to such a file is named to the Judge, which
holds the run for a person. Added code that names the test runner's reporting surface is named the same way.
"""

import sys
from pathlib import Path

import pytest

import warden.tagteam as tagteam
from warden.authorization import grant
from warden.models import FileEdit, Transformation, TransformationStatus
from warden.suite import run_suite
from warden.tagteam import TagTeam

from fakes import FakeJudge

CHECKS = {
    "pkg/__init__.py": "def answer():\n    return 42\n",
    "data/expected.txt": "42\n",
    "checks/check_pkg.py": ("from pathlib import Path\nfrom pkg import answer\n\n"
                            "def test_answer():\n    want = int(Path(__file__).parent.parent.joinpath('data/expected.txt').read_text())\n"
                            "    assert answer() == want\n"),
    "checks/helpers.py": "HELPER = 1\n",
    "pyproject.toml": ('[project]\nname = "d"\nversion = "0.0.1"\n\n[tool.pytest.ini_options]\n'
                       'testpaths = ["checks"]\npython_files = ["check_*.py"]\n'),
}


def _make(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


class Edits:
    """Proposes the given edits once, in one change, under a code grant."""

    def __init__(self, edits):
        self.edits, self.done = edits, False

    def propose(self, target, observed, baseline):
        if self.done:
            return None
        self.done = True
        return Transformation(
            target=str(Path(target).resolve()), intent="test", architectural_reason="test",
            affected_files=tuple(e.path for e in self.edits), expected_behavior="none", preservation_requirements=(),
            known_defects=(), transformation_scope="code", baseline_reference=baseline, evidence=(),
            edits=tuple(self.edits), status=TransformationStatus.PROPOSED)


@pytest.fixture
def measured(monkeypatch):
    monkeypatch.setattr(tagteam, "ghost_scan", lambda target, **kw: ())
    monkeypatch.setattr(TagTeam, "_calibrate", lambda self, python, notes: True)
    monkeypatch.setattr(tagteam, "assay_score", lambda **kw: (True, {"key_proven": True, "failure_modes": 5, "caught": 3}, "ok"))
    monkeypatch.setattr(tagteam, "governor_attacks", lambda **kw: ({"scenario": "a", "severity": "high", "status": "held"},))


def _judged(root: Path, edits) -> FakeJudge:
    judge = FakeJudge("ACCEPT", ("fine",))
    TagTeam(drafter=Edits(edits), judge=judge, ghost_tools_root=Path("."), swizzle_root=Path("."), assay_root=Path(".")).run(
        root, findings=[], authorization=grant("william", "transform", str(root.resolve()), "code", "material test"))
    assert judge.calls == 1, "the Judge was never asked"
    return judge


def test_the_suite_names_its_test_files_and_the_data_it_read(tmp_path):
    root = _make(tmp_path, dict(CHECKS, **{"conftest.py": "", "notes.md": "unread\n"}))
    run = run_suite(root, sys.executable)
    assert run.ran and run.passed == 1, run.describe()
    assert "checks/check_pkg.py" in run.test_files and "conftest.py" in run.test_files
    assert "data/expected.txt" in run.read_files
    assert "notes.md" not in run.read_files and not any(p.endswith(".py") for p in run.read_files)


def test_a_file_the_suite_only_wrote_is_not_named_as_data(tmp_path):
    files = dict(CHECKS, **{"checks/check_write.py": (
        "def test_w(tmp_path):\n    (tmp_path / 'x.txt').write_text('1')\n"
        "    open('written.txt', 'w').close()\n")})
    run = run_suite(_make(tmp_path, files), sys.executable)
    assert run.ran, run.describe()
    assert "written.txt" not in run.read_files


def test_the_answer_file_is_named_to_the_judge_whatever_it_is_called(tmp_path, measured):
    root = _make(tmp_path, CHECKS)
    judge = _judged(root, [FileEdit(path="pkg/__init__.py", kind="write", new="def answer():\n    return 41\n",
                                    old="def answer():\n    return 42\n"),
                           FileEdit(path="data/expected.txt", kind="write", new="41\n", old="42\n")])
    assert "data/expected.txt" in judge.evidence.judging_files_touched
    assert "pkg/__init__.py" not in judge.evidence.judging_files_touched


def test_a_test_in_a_folder_the_project_chose_is_named_to_the_judge(tmp_path, measured):
    root = _make(tmp_path, CHECKS)
    judge = _judged(root, [FileEdit(path="checks/check_pkg.py", kind="write", new=CHECKS["checks/check_pkg.py"] + "\n",
                                    old=CHECKS["checks/check_pkg.py"]),
                           FileEdit(path="checks/helpers.py", kind="write", new="HELPER = 2\n", old="HELPER = 1\n")])
    assert {"checks/check_pkg.py", "checks/helpers.py"} <= set(judge.evidence.judging_files_touched)


@pytest.mark.parametrize("added", [
    "import os\nVALUE = os.environ.get('WARDEN_SUITE_REPORT')\n",
    "import atexit\natexit.register(print)\n",
    "import os\n\n\ndef stop():\n    os._exit(0)\n",
    "def pytest_sessionfinish(session, exitstatus):\n    pass\n",
])
def test_added_code_that_names_the_reporting_surface_is_named_to_the_judge(tmp_path, measured, added):
    root = _make(tmp_path, CHECKS)
    judge = _judged(root, [FileEdit(path="pkg/__init__.py", kind="write", new="def answer():\n    return 42\n" + added,
                                    old="def answer():\n    return 42\n")])
    assert "pkg/__init__.py" in judge.evidence.judging_files_touched
    assert any("reporting surface" in n for n in judge.evidence.notes)


def test_a_plain_code_change_is_not_named_to_the_judge(tmp_path, measured):
    root = _make(tmp_path, CHECKS)
    judge = _judged(root, [FileEdit(path="pkg/__init__.py", kind="write", new="def answer():\n    return 42  # kept\n",
                                    old="def answer():\n    return 42\n")])
    assert judge.evidence.judging_files_touched == ()


def test_an_old_line_that_already_names_the_surface_is_not_added_code(tmp_path, measured):
    old = "import atexit\n\ndef answer():\n    return 42\n"
    files = dict(CHECKS, **{"pkg/__init__.py": old})
    root = _make(tmp_path, files)
    judge = _judged(root, [FileEdit(path="pkg/__init__.py", kind="write", new=old.replace("42", "42  # same"), old=old)])
    assert "pkg/__init__.py" not in judge.evidence.judging_files_touched
