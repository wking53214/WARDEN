"""The Rust suite runner: cargo's own summary is read, green needs cargo's exit status 0, and a
Rust-only target is measured by cargo while a Python target keeps pytest."""

import shutil
import time
from pathlib import Path

import pytest

from warden.suite import SuiteRun, preserved, run_cargo, run_suite, runner_for
from warden.tagteam import _source_hash

pytestmark = pytest.mark.skipif(shutil.which("cargo") is None, reason="cargo is not installed")


def _crate(root: Path, lib: str) -> Path:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "Cargo.toml").write_text('[package]\nname = "probe"\nversion = "0.1.0"\nedition = "2021"\n',
                                     encoding="utf-8")
    (root / "src" / "lib.rs").write_text(lib, encoding="utf-8")
    return root


GREEN = """
pub fn two() -> u32 { 2 }
#[cfg(test)]
mod tests {
    #[test]
    fn a() { assert_eq!(super::two(), 2); }
    #[test]
    fn b() { assert!(super::two() > 1); }
}
"""


def test_a_rust_only_target_is_measured_by_cargo(tmp_path):
    assert runner_for(_crate(tmp_path, GREEN)) == "cargo"


def test_a_target_with_python_tests_keeps_pytest(tmp_path):
    _crate(tmp_path, GREEN)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    assert runner_for(tmp_path) == "pytest"


def test_a_passing_crate_is_green_with_counts_from_cargo(tmp_path):
    run = run_suite(_crate(tmp_path, GREEN), "python3")
    assert run.green and run.runner == "cargo"
    assert (run.passed, run.failed, run.errors) == (2, 0, 0)


def test_a_failing_test_is_not_green(tmp_path):
    lib = GREEN + "\n#[test]\nfn c() { assert!(false); }\n"
    run = run_cargo(_crate(tmp_path, lib))
    assert run.ran and not run.green and run.failed == 1 and run.passed == 2
    assert run.exit_code != 0


def test_ignored_tests_are_counted_as_skipped_not_failed(tmp_path):
    lib = GREEN + "\n#[test]\n#[ignore]\nfn d() { assert!(false); }\n"
    run = run_cargo(_crate(tmp_path, lib))
    assert run.green and run.skipped == 1 and run.failed == 0


def test_a_summary_line_printed_by_a_failing_test_cannot_make_the_run_green(tmp_path):
    lib = ('#[test]\nfn e() { println!("test result: ok. 99 passed; 0 failed; 0 ignored"); assert!(false); }\n')
    run = run_cargo(_crate(tmp_path, lib))
    assert not run.green and run.failed == 1


def test_a_crate_that_does_not_build_is_not_green(tmp_path):
    run = run_cargo(_crate(tmp_path, "pub fn broken() -> u32 { \"not a number\" }\n"))
    assert not run.green and not run.ran


def test_a_crate_with_no_tests_is_not_a_run(tmp_path):
    run = run_cargo(_crate(tmp_path, "pub fn one() -> u32 { 1 }\n"))
    assert not run.ran and "no tests" in run.reason


def test_a_run_past_the_timeout_did_not_run(tmp_path):
    lib = "#[test]\nfn slow() { std::thread::sleep(std::time::Duration::from_secs(300)); }\n"
    started = time.time()
    run = run_cargo(_crate(tmp_path, lib), timeout=20)
    assert not run.ran and "timed out" in run.reason and time.time() - started < 60


def test_a_change_that_breaks_a_rust_test_is_not_preserved(tmp_path):
    before = run_cargo(_crate(tmp_path, GREEN))
    after = run_cargo(_crate(tmp_path / "after", GREEN.replace("2 }", "3 }")))
    assert before.green and preserved(before, after) is not None


def test_a_rust_edit_changes_the_source_hash_but_build_output_does_not(tmp_path):
    _crate(tmp_path, GREEN)
    base = _source_hash(tmp_path)
    (tmp_path / "target" / "debug").mkdir(parents=True)
    (tmp_path / "target" / "debug" / "out.rs").write_text("// generated", encoding="utf-8")
    (tmp_path / "Cargo.lock").write_text("lock", encoding="utf-8")
    assert _source_hash(tmp_path) == base
    (tmp_path / "src" / "lib.rs").write_text(GREEN.replace("2 }", "5 }"), encoding="utf-8")
    assert _source_hash(tmp_path) != base


def test_a_suite_run_describes_its_runner():
    assert "cargo exited 101" in SuiteRun(ran=True, passed=1, exit_code=101, runner="cargo").describe()
