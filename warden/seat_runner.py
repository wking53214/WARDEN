"""The program a seat runs in when Warden isolates it (`warden tagteam --isolate-seats`).

Warden starts this in a new process and talks to it in single-line JSON messages on standard input and output
(see `seatwire`). It closes the process in with `sandbox.apply` before it imports any seat code, loads the one
seat it was told to, and then answers calls until it is told to stop or Warden goes away.

Standard output is given to Warden for messages only. The seat's own prints go to standard error, so a seat
that prints cannot forge or corrupt a message. The seat still decides its own answers, and Warden still
checks every answer; this program only carries them.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

from . import sandbox, seatwire

#: The only calls Warden may make on a seat, and the only attributes it may set.
METHODS = frozenset({"propose", "finish", "decide"})
ATTRIBUTES = frozenset({"scope"})


def _reply(out, message: dict) -> None:
    out.write(seatwire.dumps(message) + "\n")
    out.flush()


def _inside(place: Any, target: Path) -> bool:
    return bool(place) and Path(place).resolve().is_relative_to(target)


def _load(request: dict) -> tuple[Any, dict]:
    """Import and build the seat. Returns (seat, what to tell Warden). Raises _Refused to refuse it."""
    spec = request["spec"]
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise _Refused("error", "expected MODULE:FACTORY")
    target = Path(request["target"]).resolve()
    module = importlib.import_module(module_name)
    seat = getattr(module, attr)()
    places = [getattr(module, "__file__", None), *list(getattr(module, "__path__", []) or []),
              getattr(sys.modules.get(type(seat).__module__), "__file__", None)]
    for place in places:
        if _inside(place, target):
            raise _Refused("shadowed", f"The seat {spec} was loaded from {place}, which is inside the folder "
                                       "being governed, not from an installed seat. Warden will not run a seat "
                                       "the run could edit. Nothing was run.")
    wanted, contract = getattr(seat, "requires_contract", None), request["contract"]
    if wanted is None:
        raise _Refused("contract", f"The seat {spec} does not say which Warden contract it was written for, so "
                                   f"its fit with this Warden (contract {contract!r}) cannot be checked. Nothing "
                                   f'was run. Add requires_contract = "{contract}" to the seat.')
    if not isinstance(wanted, str) or wanted != contract:
        raise _Refused("contract", f"The seat {spec} was written for Warden contract {wanted!r} but this Warden "
                                   f"is contract {contract!r}. Nothing was run.")
    return seat, {"requires_contract": wanted, "module_file": getattr(module, "__file__", None),
                  "class": type(seat).__name__}


class _Refused(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def main() -> None:
    # Take the message channel for Warden alone, then point everything else at standard error and nothing.
    channel_in = os.fdopen(os.dup(0), "r", encoding="utf-8", newline="\n")
    channel_out = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    try:
        request = seatwire.loads(channel_in.readline())
        if request.get("op") != "load":
            raise _Refused("error", "the first message was not a load")
        sys.path[:] = [p for p in request["sys_path"] if p]
        sandbox.apply(read=[request["target"], *request["read"]], scratch=request["scratch"],
                      cpu_seconds=request.get("cpu_seconds"))
        os.chdir(request["scratch"])
        seat, info = _load(request)
    except _Refused as exc:
        _reply(channel_out, {"ok": False, "kind": exc.kind, "error": str(exc)})
        return
    except BaseException as exc:  # noqa: BLE001 - a seat that will not load is named, never a traceback
        _reply(channel_out, {"ok": False, "kind": "error", "error": f"{type(exc).__name__}: {exc}"})
        return
    _reply(channel_out, {"ok": True, **info})

    for line in channel_in:
        try:
            message = seatwire.loads(line)
            op = message.get("op")
            if op == "close":
                return
            if op == "set":
                if message["name"] not in ATTRIBUTES:
                    raise ValueError(f"{message['name']!r} is not an attribute Warden sets")
                setattr(seat, message["name"], seatwire.from_wire(message["value"]))
                _reply(channel_out, {"ok": True})
            elif op == "call":
                if message["method"] not in METHODS:
                    raise ValueError(f"{message['method']!r} is not a call Warden makes on a seat")
                args = [seatwire.from_wire(a) for a in message["args"]]
                if message["method"] in ("propose", "finish"):
                    args[0] = Path(args[0])  # the folder travels as text and is a Path again for the seat
                answer = getattr(seat, message["method"])(*args)
                _reply(channel_out, {"ok": True, "result": seatwire.to_wire(answer)})
            else:
                raise ValueError(f"unknown message {op!r}")
        except Exception as exc:  # noqa: BLE001 - whatever the seat raised is Warden's to name
            _reply(channel_out, {"ok": False, "kind": "error", "error": f"{type(exc).__name__}: {exc}"})
