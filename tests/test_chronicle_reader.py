"""`warden chronicle DIR` (the reader) refuses an unreadable chronicle file the way the run path does.

A non-UTF-8 file gave a traceback and exit 1, and a line that was not valid JSON, or was valid JSON but not an object, was
skipped without a word, so a damaged chain printed as a shorter one. Now the reader exits 2 naming the file and the line.
"""

import json
from pathlib import Path

import pytest

from warden import chronicle
from warden.cli import main

GOOD = json.dumps({"kind": "run", "when": "2026-10-30T00:00:00+00:00", "key": {"origin": "o", "base_commit": "b",
                                                                              "claimed_commit": "c"},
                   "decision": "ACCEPT_UNVERIFIED", "promises": [], "settled": []})


def _folder(tmp_path: Path, name: str, data: bytes) -> Path:
    folder = tmp_path / "chronicle"
    folder.mkdir(exist_ok=True)
    (folder / name).write_bytes(data)
    return folder


def test_a_clean_chronicle_still_prints_with_exit_0(tmp_path, capsys):
    folder = _folder(tmp_path, "origin-aaaa.jsonl", (GOOD + "\n\n" + GOOD + "\n").encode())
    assert main(["chronicle", str(folder)]) == 0
    out, err = capsys.readouterr()
    assert out.strip() and "Traceback" not in err


def test_a_file_that_is_not_utf8_is_exit_2_naming_the_file(tmp_path, capsys):
    folder = _folder(tmp_path, "origin-aaaa.jsonl", b'{"kind": "run"}\n\xff\xfe\n')
    code = main(["chronicle", str(folder)])
    out, err = capsys.readouterr()
    assert code == 2 and "origin-aaaa.jsonl" in err and "UTF-8" in err
    assert "Traceback" not in err and out == ""


@pytest.mark.parametrize("bad", ["{not json", '{"kind": ', "[1, 2]", '"a string"', "7", "null"])
def test_a_bad_line_is_exit_2_naming_the_file_and_the_line(tmp_path, capsys, bad):
    folder = _folder(tmp_path, "origin-bbbb.jsonl", (GOOD + "\n\n" + bad + "\n" + GOOD + "\n").encode())
    code = main(["chronicle", str(folder)])
    out, err = capsys.readouterr()
    assert code == 2, (out, err)
    assert "origin-bbbb.jsonl" in err and "line 3" in err
    assert out == ""


def test_the_reader_uses_the_run_paths_refusal_for_bad_json(tmp_path):
    folder = _folder(tmp_path, "origin-cccc.jsonl", b"{not json\n")
    with pytest.raises(chronicle.ChronicleError) as caught:
        chronicle.read_file(folder / "origin-cccc.jsonl")
    assert "line 1" in str(caught.value) and "origin-cccc.jsonl" in str(caught.value)


def test_asking_for_one_origin_does_not_read_another_origins_damaged_file(tmp_path, capsys):
    folder = _folder(tmp_path, "origin-dddd.jsonl", b"{not json\n")
    assert main(["chronicle", str(folder), "--origin", "https://example.org/none"]) == 0
    assert "Traceback" not in capsys.readouterr().err
