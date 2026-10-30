"""`tagteam._fingerprint` hashes the number of files, and per file its length-prefixed path, its executable bit and its
length-prefixed bytes. Warden 0.16.2 and earlier hashed path then bytes with no delimiter, so a shift of the boundary
between a path and its content, or between two files, gave two different trees the same hash."""

from warden.tagteam import _fingerprint


def _tree(root, files, executable=()):
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if name in executable else 0o644)
    return root


def test_a_boundary_shift_between_a_path_and_its_content_gives_a_different_fingerprint(tmp_path):
    one = _tree(tmp_path / "one", {"a": b"bc"})
    two = _tree(tmp_path / "two", {"ab": b"c"})
    assert _fingerprint(one) != _fingerprint(two)


def test_a_boundary_shift_between_two_files_gives_a_different_fingerprint(tmp_path):
    one = _tree(tmp_path / "one", {"a": b"xb", "c": b"y"})
    two = _tree(tmp_path / "two", {"a": b"x", "bc": b"y"})
    assert _fingerprint(one) != _fingerprint(two)


def test_a_file_moved_between_the_content_of_its_neighbour_gives_a_different_fingerprint(tmp_path):
    one = _tree(tmp_path / "one", {"a": b"1", "b": b"23"})
    two = _tree(tmp_path / "two", {"a": b"12", "b": b"3"})
    assert _fingerprint(one) != _fingerprint(two)


def test_an_executable_bit_alone_gives_a_different_fingerprint(tmp_path):
    plain = _tree(tmp_path / "plain", {"run.sh": b"echo hi\n"})
    marked = _tree(tmp_path / "marked", {"run.sh": b"echo hi\n"}, executable=("run.sh",))
    assert _fingerprint(plain) != _fingerprint(marked)


def test_the_same_tree_hashes_the_same_and_the_hash_stays_sixteen_hex_digits(tmp_path):
    files = {"pkg/__init__.py": b"VALUE = 1\n", "README.md": b"# demo\n", "run.sh": b"echo hi\n"}
    one = _tree(tmp_path / "one", files, executable=("run.sh",))
    two = _tree(tmp_path / "two", files, executable=("run.sh",))
    first = _fingerprint(one)
    assert first == _fingerprint(two) == _fingerprint(one)
    assert len(first) == 16 and set(first) <= set("0123456789abcdef")


def test_an_empty_tree_and_a_tree_of_one_empty_file_differ(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    one = _tree(tmp_path / "one", {"a": b""})
    assert _fingerprint(empty) != _fingerprint(one)
