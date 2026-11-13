"""Warden's side of an isolated seat: start the seat's own program, send it questions, read its answers.

`IsolatedSeat` stands where the real seat object stood. Warden calls `decide` (or `propose`, `finish`) on it
exactly as before; the call becomes a message, the answer comes back as a message, and the answer is rebuilt
into the same rows. The seat itself runs in `warden.seat_runner`, closed in by `warden.sandbox`.

A seat that does not answer in time is killed with everything it started, however it is stuck. A seat whose
program ends, or answers in a form Warden cannot read, ends the run as ERROR like any seat that fails.
"""

from __future__ import annotations

import contextlib
import logging
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from . import runstate, sandbox, seatwire

logger = logging.getLogger("warden.seatproc")

_BOOT = "import sys; sys.path.insert(0, {root!r}); from warden import seat_runner; seat_runner.main()"
_MAX_REPLY = 64 << 20  # a reply larger than this is a seat misbehaving, not an answer


class SeatRefused(Exception):
    """The seat was loaded and refused: shadowed, wrong contract, or not buildable. Nothing was run."""


class SeatFailed(RuntimeError):
    """The seat's program failed or answered in a form Warden could not read."""


def _kill_group(proc: subprocess.Popen) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)


class IsolatedSeat:
    """A seat running in its own process. Build it with `start`; `close` it when the run is over."""

    isolated = True

    def __init__(self, spec: str, who: str, timeout: float) -> None:
        self.spec, self.who, self.timeout = spec, who, timeout
        self.requires_contract: Optional[str] = None
        self.isolated_module_file: Optional[str] = None
        self._proc: Optional[subprocess.Popen] = None
        self._scratch: Optional[str] = None
        self._buffer = b""

    # -- starting and stopping --------------------------------------------------------------------

    def start(self, *, target: Path, sys_path: list[str], contract: str) -> "IsolatedSeat":
        reason = sandbox.unavailable()
        if reason:
            raise SeatRefused(f"{reason}. Warden will not run a seat unprotected in this mode. Nothing was run.")
        import warden
        root = str(Path(warden.__file__).resolve().parents[1])
        self._scratch = tempfile.mkdtemp(prefix="warden-seat-")
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self._scratch, "TMPDIR": self._scratch,
               "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", _BOOT.format(root=root)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, cwd=self._scratch, env=env, start_new_session=True, close_fds=True)
        except OSError as exc:
            self.close()
            raise SeatFailed(f"{self.who}'s program could not be started: {exc}") from None
        read = [p for p in sys_path if p and os.path.isdir(p)] + [root]
        try:
            self._send({"op": "load", "spec": self.spec, "target": str(target), "sys_path": sys_path,
                        "read": read, "scratch": self._scratch, "contract": contract,
                        "cpu_seconds": int(self.timeout) + 60})
            reply = self._receive(f"{self.who} while it was being loaded")
        except BaseException:
            self.close()
            raise
        if not reply.get("ok"):
            self.close()
            message = str(reply.get("error", "no reason given"))
            if reply.get("kind") in ("shadowed", "contract"):
                raise SeatRefused(message)
            raise SeatFailed(f"{self.who} could not be loaded: {message}")
        self.requires_contract = reply.get("requires_contract")
        self.isolated_module_file = reply.get("module_file")
        logger.info("seat loaded in its own process: %s (%s)", self.spec, reply.get("class"))
        return self

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            with contextlib.suppress(Exception):
                self._send_to(proc, {"op": "close"})
            with contextlib.suppress(Exception):
                proc.stdin.close()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            _kill_group(proc)  # anything the seat left running
            with contextlib.suppress(Exception):
                proc.stdout.close()
        scratch, self._scratch = self._scratch, None
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)

    # -- the seat's calls ---------------------------------------------------------------------------

    def _call(self, method: str, *args: Any) -> Any:
        try:
            self._send({"op": "call", "method": method, "args": [seatwire.to_wire(a) for a in args]})
            reply = self._receive(self.who)
        except BaseException:
            self.close()  # whatever state the seat is in, it is not trusted to carry on
            raise
        if not reply.get("ok"):
            raise SeatFailed(str(reply.get("error", "the seat failed without saying why")))
        try:
            return seatwire.from_wire(reply.get("result"))
        except Exception as exc:  # noqa: BLE001
            raise SeatFailed(f"{self.who}'s answer could not be read ({type(exc).__name__}: {exc})") from None

    def propose(self, target, observed, baseline):
        return self._call("propose", str(target), observed, baseline)

    def finish(self, target, baseline, facts):
        return self._call("finish", str(target), baseline, facts)

    def decide(self, evidence):
        return self._call("decide", evidence)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "scope" and getattr(self, "_proc", None) is not None:
            try:
                self._send({"op": "set", "name": "scope", "value": seatwire.to_wire(value)})
                reply = self._receive(self.who)
            except BaseException:
                self.close()
                raise
            if not reply.get("ok"):
                raise SeatFailed(str(reply.get("error")))
            return
        object.__setattr__(self, name, value)

    # -- the wire -----------------------------------------------------------------------------------

    def _send(self, message: dict) -> None:
        if self._proc is None:
            raise SeatFailed(f"{self.who}'s program is not running")
        self._send_to(self._proc, message)

    @staticmethod
    def _send_to(proc: subprocess.Popen, message: dict) -> None:
        try:
            proc.stdin.write((seatwire.dumps(message) + "\n").encode("ascii"))
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise SeatFailed("the seat's program is gone") from None

    def _receive(self, who: str) -> dict:
        proc = self._proc
        if proc is None:
            raise SeatFailed(f"{self.who}'s program is not running")
        deadline = time.monotonic() + self.timeout
        fd = proc.stdout.fileno()
        while b"\n" not in self._buffer:
            left = deadline - time.monotonic()
            if left <= 0:
                _kill_group(proc)
                raise runstate.SeatTimedOut(who, self.timeout)
            ready, _, _ = select.select([fd], [], [], min(left, 1.0))
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:
                code = proc.poll()
                raise SeatFailed(f"{self.who}'s program ended without answering"
                                 + (f" (exit {code})" if code is not None else ""))
            self._buffer += chunk
            if len(self._buffer) > _MAX_REPLY:
                _kill_group(proc)
                raise SeatFailed(f"{self.who} answered with more than {_MAX_REPLY >> 20} MB")
        line, _, self._buffer = self._buffer.partition(b"\n")
        try:
            return seatwire.loads(line.decode("utf-8"))
        except (ValueError, seatwire.WireError) as exc:
            raise SeatFailed(f"{self.who}'s answer could not be read: {exc}") from None
