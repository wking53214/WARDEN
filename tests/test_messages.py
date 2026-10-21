"""What Warden says: reasons are cut at a word with a marker, grammar is right, and a bad input file is named plainly."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from warden import swizzle, textio
from warden.cli import main
from warden.ghost import _clean

ROOT = Path(__file__).resolve().parents[1]
SENTENCE = ("The Ghost Tools root '/tmp/some/where' has no ghost_buster package, so it is not a Ghost Tools checkout "
            "and an installed copy would not be used in its place")


# -- clip ------------------------------------------------------------------------------------------

def test_text_that_fits_is_returned_untouched():
    assert textio.clip("short", 10) == "short" and textio.clip("x" * 10, 10) == "x" * 10


@pytest.mark.parametrize("limit", [30, 57, 80, 120, 150])
def test_a_long_reason_is_cut_at_a_word_with_a_marker_never_mid_word(limit):
    out = textio.clip(SENTENCE, limit)
    assert len(out) <= limit and out.endswith(" ...")
    kept = out[: -len(" ...")]
    assert SENTENCE.startswith(kept) and SENTENCE[len(kept)] == " ", out        # the cut fell on a space
    assert not kept.endswith((" ", ",", ";", ":", "("))


def test_text_with_no_space_to_cut_at_is_cut_at_the_limit_and_still_marked():
    out = textio.clip("/very/long/path/" + "x" * 200, 40)
    assert len(out) <= 40 and out.endswith(" ...")


def test_the_ghost_text_cleaner_cuts_the_same_way():
    out = _clean("word " * 100, 40)
    assert len(out) <= 40 and out.endswith(" ...") and "wor ..." not in out


def test_swizzle_reasons_are_not_cut_mid_word():
    proc = subprocess.CompletedProcess([], 1, stdout="", stderr="boom " + "explanation " * 40)
    holds, why = swizzle._read_proofs(proc)
    assert holds is False and why.endswith(" ...") and not re.search(r"explanatio\s*\.\.\.$", why)


# -- grammar ---------------------------------------------------------------------------------------

def test_nothing_says_a_before_assay():
    """'an ASSAY', in messages, README, docs and tests alike."""
    wrong = re.compile(r"\b[Aa] " + "ASSAY")
    files = subprocess.run(["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True, check=True).stdout.split()
    offenders = []
    for name in files:
        path = ROOT / name
        if path.suffix in {".py", ".md", ".toml", ".yml", ".json", ".txt"} and path.is_file():
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if wrong.search(line):
                    offenders.append(f"{name}:{number}")
    assert offenders == []


# -- a garbage --from-ghost file ---------------------------------------------------------------------

def _run(tmp_path, capsys, findings: Path):
    target = tmp_path / "t"
    target.mkdir(exist_ok=True)
    code = main(["tagteam", str(target), "--from-ghost", str(findings)])
    return code, json.loads(capsys.readouterr().out)


def test_a_findings_file_that_is_not_json_is_named_and_explained(tmp_path, capsys):
    bad = tmp_path / "garbage.json"
    bad.write_text("{not json", encoding="utf-8")
    code, out = _run(tmp_path, capsys, bad)
    assert code == 4 and out["decision"] == "ERROR"
    assert "garbage.json" in out["reason"] and "not valid JSON" in out["reason"] and "line 1 column 2" in out["reason"]
    assert "JSONDecodeError" not in out["reason"] and out["reason"].endswith("Nothing was run.")


@pytest.mark.parametrize("make,expected", [
    (lambda p: p.write_bytes(b"\xff\xfe\x00bad"), "not valid UTF-8"),
    (lambda p: p.write_text('{"nothing": "here"}', encoding="utf-8"), "not a Ghost Tools findings file"),
    (lambda p: p.write_text('"a string"', encoding="utf-8"), "not a Ghost Tools findings file"),
])
def test_other_unusable_findings_files_are_named_too(tmp_path, capsys, make, expected):
    bad = tmp_path / "odd.json"
    make(bad)
    code, out = _run(tmp_path, capsys, bad)
    assert code == 4 and "odd.json" in out["reason"] and expected in out["reason"], out["reason"]


def test_a_missing_or_unreadable_findings_file_says_so(tmp_path, capsys):
    code, out = _run(tmp_path, capsys, tmp_path / "gone.json")
    assert code == 4 and "gone.json" in out["reason"] and "could not be read" in out["reason"]
    code, out = _run(tmp_path, capsys, tmp_path)               # a folder
    assert code == 4 and "could not be read" in out["reason"]
