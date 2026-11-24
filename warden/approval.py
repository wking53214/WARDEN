"""Checking that a person, not a process, approved a change.

Until this module a grant carried only a name. Anything that could type `--authorize "Claude Code agent"`
(or any other name that is not on Warden's short list of seats) produced a receipt reading
`authority_source: human_operator`. The name was never checked, and the receipt said it was.

What changed: a grant is `human_operator` only when `confirm_on_terminal` returned "terminal", that is, when
somebody answered a fresh, random challenge on the controlling terminal. Anything else is an
`unverified_claim`, the receipt says so, and a run with an unverified approver can not reach APPROVED.

What this does NOT do: it is not a signature. A process that owns a pseudo-terminal can answer the challenge. It
raises the bar from "type any name" to "operate the person's terminal"; the real fix is a signed approval
checked against a roster of approvers (HUMANITY and SIGNET), which Warden does not yet call.
"""

from __future__ import annotations

import os
import secrets
from typing import Optional


#: What `Authorization.verified_by` holds after a person answered on the terminal.
TERMINAL = "terminal"


def confirm_on_terminal(actor: str, operation: str, subject: str, reason: str,
                        tty_path: str = "/dev/tty", _ask=None) -> str:
    """"terminal" if a person typed the challenge shown on the controlling terminal, else "".

    The challenge is read from the terminal device itself, never from stdin, so a pipe, a here-document or
    a script's stdin cannot answer it. With no controlling terminal (CI, a service, most agent shells) the
    result is "": the approval stays an unverified claim. `tty_path` and `_ask` exist for tests.
    """
    code = secrets.token_hex(3)
    prompt = (f"\nWarden: approve this change?\n  approver  : {actor}\n  operation : {operation}\n"
              f"  subject   : {subject}\n  reason    : {reason}\n"
              f"Type  approve {code}  to confirm, anything else refuses: ")
    try:
        answer = _ask(prompt) if _ask is not None else _read_tty(prompt, tty_path)
    except OSError:
        return ""
    if answer is None:
        return ""
    return TERMINAL if answer.strip() == f"approve {code}" else ""


def _read_tty(prompt: str, tty_path: str) -> Optional[str]:
    fd = os.open(tty_path, os.O_RDWR | os.O_NOCTTY)
    try:
        if not os.isatty(fd):
            return None
        os.write(fd, prompt.encode("utf-8", "replace"))
        line = b""
        while not line.endswith(b"\n") and len(line) < 256:
            chunk = os.read(fd, 1)
            if not chunk:
                break
            line += chunk
        return line.decode("utf-8", "replace")
    finally:
        os.close(fd)


def describe(actor: str, verified_by: str) -> str:
    """Words for a receipt or a log: who approved and how well that is known."""
    if verified_by:
        return f"approved by {actor}, confirmed on the terminal"
    return f"name given as {actor!r}; NOT verified (nobody confirmed it on a terminal)"
