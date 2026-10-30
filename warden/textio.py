"""Reading and writing files without changing what the author wrote.

Python's text mode quietly turns CRLF into LF when it reads, and writes LF
back. A file that came in with Windows line endings would leave with
different ones. These helpers keep the line-ending style of a file that
already exists, and refuse a file that is not valid UTF-8 instead of
crashing on it or guessing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


ELLIPSIS = " ..."


def clip(text: str, limit: int) -> str:
    """`text` shortened to at most `limit` characters for a message, never mid-word without saying so.

    Text that fits is returned as it is. Longer text is cut at the last space that leaves at least a third of the
    allowance, trailing punctuation is dropped, and an explicit ` ...` marks the cut. Text with no space to cut at
    (one long path, say) is cut at the limit and marked the same way, so a reader always knows it was shortened."""
    text = str(text)
    if len(text) <= limit:
        return text
    room = max(limit - len(ELLIPSIS), 1)
    cut = text[:room]
    space = cut.rfind(" ")
    if space >= room // 3 and text[room] != " ":
        cut = cut[:space]
    return cut.rstrip(" ,;:(-") + ELLIPSIS


class Undecodable(ValueError):
    """A file is not valid UTF-8, so Warden will not edit it."""


def _is_crlf(raw: bytes) -> bool:
    """True when every line ending in the file is CRLF (and there is at least one)."""
    return b"\r\n" in raw and raw.count(b"\r\n") == raw.count(b"\n") and b"\r" not in raw.replace(b"\r\n", b"")


def decode(raw: bytes, label: str = "file") -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Undecodable(f"{label} is not valid UTF-8, so it will not be edited") from exc


def read_text(path: Path, label: str = "") -> str:
    """The file's text, with a pure CRLF file shown with LF so edits can match it."""
    raw = Path(path).read_bytes()
    text = decode(raw, label or str(path))
    return text.replace("\r\n", "\n") if _is_crlf(raw) else text


def is_decodable(path: Path) -> bool:
    try:
        decode(Path(path).read_bytes())
    except (Undecodable, OSError):
        return False
    return True


def encode_like(path: Path, text: str) -> bytes:
    """`text` as bytes, in CRLF if the file already there uses CRLF throughout."""
    path = Path(path)
    if path.is_file() and _is_crlf(path.read_bytes()):
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    return text.encode("utf-8")


def write_bytes_with_mode(path: Path, data: bytes, mode: Optional[int]) -> None:
    """Write `data`; when `mode` is given the file is created with it and chmod-ed to it after the write (the
    process umask must not change what was recorded). Used to put a file back as it was, executable bit included."""
    path = Path(path)
    if mode is None:
        path.write_bytes(data)
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(path, mode)


def write_text(path: Path, text: str) -> None:
    """Write `text`, keeping the line endings of the file it replaces."""
    path = Path(path)
    data = encode_like(path, text)
    path.write_bytes(data)
