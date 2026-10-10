"""Things a run must keep outside the target and outside the temp directory: a lock and a journal.

WHERE   A per-target state folder, found the same way by every run no matter what TMPDIR or HOME
        are set to:
          - a target inside a git work tree: `<git folder>/warden-state/<key>/`
          - anything else: `<home from the password database>/.local/state/warden-state/<key>/`
        `<key>` is a hash of the target's real path. The folder is made private (mode 0700) and a
        symlink or a folder owned by someone else at either level is refused, never followed.

THE LOCK     Two runs on one target would interleave their edits and test runs. A lock file in the
             state folder, held for the whole run. It is opened without following symlinks.
THE JOURNAL  The keep test makes code raise on purpose and puts it back afterward. If the process
             is killed in between, the trap stays in the user's source. Before any trap is
             written, the original bytes and the exact trap bytes of every file are saved here.
             A later run that carries a human authorization restores a file only if it still holds
             exactly the trap; a file the user has changed since is left alone and named in a
             warning. A run with no authorization never touches the tree.

Also here: the handlers that turn SIGTERM, SIGHUP and SIGINT into an orderly stop, the timer that
stops a hung seat, and the redirect of file descriptor 1 while seats run.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import secrets
import signal
import stat
import sys
import threading
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from . import gitstate

INTERRUPTED_NOTE = "A previous run was interrupted during the keep test; its trap code was removed."
BUSY_NOTE = "another Warden run is using this target"
PENDING_NOTE = ("A previous run was interrupted during the keep test and may have left trap code in the source. "
                "Nothing was changed because this run has no human authorization; run again with --authorize "
                "to restore it.")

#: A line the keep test writes into trapped code. Used only when a journal does not say what the trap was.
_TRAP_MARK = b"warden keep-test:"


class StateUnavailable(OSError):
    """The place for the lock and journal could not be made safely."""


class Interrupted(BaseException):
    """SIGTERM, SIGHUP or SIGINT arrived. A BaseException so a seat's `except Exception` cannot swallow it."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.signal_name = name


class SeatTimedOut(BaseException):
    """A seat did not answer in time. A BaseException for the same reason as `Interrupted`."""

    def __init__(self, who: str, seconds: float) -> None:
        super().__init__(f"{who} did not answer within {seconds:g} seconds")
        self.seat = who
        self.seconds = seconds


# -- where state lives --------------------------------------------------------------------------

def _key(target: Path) -> str:
    return hashlib.sha256(str(Path(target).resolve()).encode("utf-8")).hexdigest()[:20]


def _home() -> Path:
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (KeyError, OSError):
        return Path.home()


def _private_dir(path: Path) -> None:
    """Make `path` (one level) if missing, then insist it is a real folder that is ours and private."""
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise StateUnavailable(f"{path} is a link or not a folder; Warden will not use it for its state")
    if info.st_uid != os.getuid():
        raise StateUnavailable(f"{path} belongs to someone else; Warden will not use it for its state")
    if info.st_mode & 0o077:
        raise StateUnavailable(f"{path} is open to other users; Warden will not use it for its state")


_cache: Dict[str, Path] = {}


def state_dir(target: Path) -> Path:
    """The folder holding this target's lock and journal, made on first use."""
    key = _key(target)
    cached = _cache.get(key)
    if cached is not None and cached.is_dir() and not cached.is_symlink():
        return cached
    errors: List[str] = []
    bases: List[Path] = []
    git_dir = gitstate.absolute_git_dir(Path(target))
    if git_dir is not None and git_dir.is_dir():
        bases.append(git_dir)
    home_base = _home() / ".local" / "state"
    bases.append(home_base)
    for base in bases:
        try:
            if base == home_base:
                base.mkdir(parents=True, exist_ok=True)
            if base != home_base and (os.lstat(base).st_uid != os.getuid()):
                raise StateUnavailable(f"{base} belongs to someone else")
            top = base / "warden-state"
            _private_dir(top)
            leaf = top / key
            _private_dir(leaf)
            _cache[key] = leaf
            return leaf
        except OSError as exc:
            errors.append(f"{base}: {exc}")
    raise StateUnavailable("Warden could not make a safe place for its lock and journal (" + "; ".join(errors)[:300] + ")")


def lock_path(target: Path) -> Path:
    return state_dir(target) / "lock"


def journal_path(target: Path) -> Path:
    return state_dir(target) / "journal.json"


# -- the lock ----------------------------------------------------------------------------------

class TargetLock:
    """An exclusive, non-blocking lock on one target for the length of a run."""

    def __init__(self, target: Path) -> None:
        self.target = Path(target)
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        """True when the lock is held. False when another run holds it. Raises StateUnavailable when the
        lock file cannot be opened safely (for example a symlink was planted at its name)."""
        path = lock_path(self.target)
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        except OSError as exc:
            raise StateUnavailable(f"the lock file could not be opened safely ({exc.strerror or type(exc).__name__})") from exc
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            os.close(fd)
            raise StateUnavailable("the lock file is not an ordinary file of ours; Warden will not use it")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


# -- the journal -------------------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def write_journal(target: Path, originals: Dict[str, bytes], trapped: Optional[Dict[str, bytes]] = None) -> None:
    """Record every file, its original bytes and the exact trap bytes about to be written.

    Written to a new file created exclusively (a symlink at its name is an error, not a path to
    follow), flushed to disk, then moved into place.
    """
    trapped = trapped or {}
    payload = {"version": 2, "target": str(Path(target).resolve()),
               "files": {rel: {"original": _b64(data),
                               "trapped": _b64(trapped[rel]) if rel in trapped else None}
                         for rel, data in originals.items()}}
    path = journal_path(target)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def clear_journal(target: Path) -> None:
    try:
        journal_path(target).unlink(missing_ok=True)
    except OSError:
        pass


def has_journal(target: Path) -> bool:
    try:
        return journal_path(target).exists()
    except OSError:
        return False


def _read_journal(target: Path) -> Optional[dict]:
    path = journal_path(target)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        return None
    with open(path, "rb") as handle:
        payload = json.loads(handle.read(64 * 1024 * 1024).decode("utf-8"))
    return payload if isinstance(payload, dict) and payload.get("target") == str(Path(target).resolve()) else None


def recover(target: Path) -> List[str]:
    """Put back files an interrupted keep test left trapped. Returns plain-language notes.

    Call only after the human authorization check. A file is restored only if it still holds the
    trap exactly as the journal recorded it. A file that is already the original needs nothing. A
    file that is neither was changed by someone since: it is not overwritten, and a warning says so.
    """
    notes: List[str] = []
    if not has_journal(target):
        return notes
    root = Path(target).resolve()
    try:
        payload = _read_journal(target)
        if payload is None:
            return [f"WARNING: a recovery journal for this target exists but is not one Warden can trust; "
                    f"it was left alone ({journal_path(target)})."]
        raw = payload["files"]
        entries = {}
        for rel, item in raw.items():
            if isinstance(item, dict):
                original = base64.b64decode(item["original"])
                trap = base64.b64decode(item["trapped"]) if item.get("trapped") else None
            else:  # a journal written by an older Warden: the trap bytes are not known
                original, trap = base64.b64decode(item), None
            entries[rel] = (original, trap)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return [f"WARNING: a recovery journal for this target exists but could not be read; it was left alone "
                f"({journal_path(target)})."]
    restored = False
    for rel, (original, trap) in entries.items():
        dest = root / rel
        if (not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts
                or dest.is_symlink() or not dest.resolve().is_relative_to(root)):
            notes.append(f"WARNING: the journal named {rel!r}, which is not a plain file inside the target; "
                         "it was skipped.")
            continue
        try:
            current = dest.read_bytes() if dest.is_file() else None
        except OSError:
            current = None
        if current is None:
            notes.append(f"WARNING: {rel} is gone, so the interrupted keep test's trap could not be checked there.")
            continue
        if current == original:
            continue  # the trap was never written, or someone already put it right
        still_trap = current == trap if trap is not None else (_TRAP_MARK in current)
        if not still_trap:
            notes.append(f"WARNING: {rel} was changed after an interrupted keep test, so Warden did not "
                         "overwrite it. It may still contain trap code (a line that raises 'warden keep-test'); "
                         "check it by hand.")
            continue
        dest.write_bytes(original)
        restored = True
    if restored:
        notes.insert(0, INTERRUPTED_NOTE)
    clear_journal(target)
    return notes


# -- signals, timers, file descriptors -------------------------------------------------------

@contextlib.contextmanager
def interrupts() -> Iterator[None]:
    """While active, SIGTERM, SIGHUP and SIGINT raise `Interrupted` in the main thread.

    After the first one, further ones are ignored until the block ends, so cleanup is not cut short.
    Does nothing outside the main thread (signal handlers can only be set there).
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    names = [n for n in ("SIGTERM", "SIGHUP", "SIGINT") if hasattr(signal, n)]
    previous = {}

    def handler(signum, _frame):
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        raise Interrupted(signal.Signals(signum).name)

    try:
        for name in names:
            sig = getattr(signal, name)
            previous[sig] = signal.signal(sig, handler)
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


@contextlib.contextmanager
def seat_timer(seconds: Optional[float], who: str) -> Iterator[None]:
    """Raise `SeatTimedOut` in the main thread if the block runs longer than `seconds`."""
    if (not seconds or seconds <= 0 or not hasattr(signal, "setitimer")
            or threading.current_thread() is not threading.main_thread()):
        yield
        return

    def handler(_signum, _frame):
        raise SeatTimedOut(who, seconds)

    old = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


@contextlib.contextmanager
def stdout_to_stderr() -> Iterator[None]:
    """Send anything written to stdout (Python's `sys.stdout` AND the real file descriptor 1) to stderr.

    A seat that prints, or a C extension or child process that writes straight to fd 1, cannot then
    corrupt the JSON Warden prints on stdout afterwards.
    """
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    saved: Optional[int] = None
    try:
        saved = os.dup(1)
        os.dup2(2, 1)
    except OSError:
        saved = None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            yield
    finally:
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                stream.flush()
        if saved is not None:
            os.dup2(saved, 1)
            os.close(saved)
