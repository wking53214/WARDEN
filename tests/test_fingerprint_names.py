"""A tree holding a file whose name is not valid UTF-8 can be fingerprinted.

`_fingerprint` encoded each relative path with `str.encode()`, which raises UnicodeEncodeError for a name that carries a
surrogate-escaped byte, so such a tree ended the run as ERROR (exit 4). Names are encoded with `os.fsencode` now. The hash
of a tree whose names are all valid UTF-8 is unchanged.
"""

import hashlib
import os
import stat

import pytest

from warden.tagteam import _fingerprint


ATTEMPTS: list = []


def _make_bad_name(root, data: bytes = b"x = 1\n") -> bool:
    """Create `bad\\xff.py` under root by its bytes. True when it exists; False when the filesystem refused."""
    name = os.fsencode(str(root)) + b"/bad\xff.py"
    ATTEMPTS.append(name)
    try:
        with open(name, "wb") as fh:
            fh.write(data)
    except OSError:
        return False
    return True


def test_a_tree_with_a_non_utf8_file_name_fingerprints(tmp_path):
    created = _make_bad_name(tmp_path)
    assert ATTEMPTS and ATTEMPTS[-1].endswith(b"bad\xff.py"), "the file must have been attempted before any skip"
    if not created:
        pytest.skip("this filesystem cannot create a file name that is not valid UTF-8 (the attempt was made)")
    first = _fingerprint(tmp_path)
    assert len(first) == 16
    (tmp_path / "other.py").write_text("y = 2\n", encoding="utf-8")
    assert _fingerprint(tmp_path) != first


def test_two_trees_that_differ_only_in_the_bytes_of_such_a_file_differ(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    made = [_make_bad_name(one, b"a\n"), _make_bad_name(two, b"b\n")]
    assert len(ATTEMPTS) >= 2, "both files must have been attempted before any skip"
    if not all(made):
        pytest.skip("this filesystem cannot create a file name that is not valid UTF-8 (the attempt was made)")
    assert _fingerprint(one) != _fingerprint(two)


def test_the_hash_of_a_tree_with_ordinary_names_is_unchanged(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "run.sh").chmod(0o755)
    digest = hashlib.sha256()
    entries = [("a.py", b"\x00", b"x = 1\n"), ("run.sh", b"\x01", b"#!/bin/sh\n")]
    digest.update(len(entries).to_bytes(8, "big"))
    for name, exec_bit, data in entries:
        encoded = name.encode()
        digest.update(len(encoded).to_bytes(8, "big") + encoded + exec_bit + len(data).to_bytes(8, "big") + data)
    assert stat.S_IMODE((tmp_path / "run.sh").stat().st_mode) & 0o100
    assert _fingerprint(tmp_path) == digest.hexdigest()[:16]
