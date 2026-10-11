"""Held results: an unverified run's final state, kept for a human to approve.

When a run ends ACCEPT_UNVERIFIED, Warden does not let the changes stand. It saves the
exact final state here, puts the tree back as it was found, and reports a digest (a
fingerprint of the saved state). A named human can then approve that digest with a
grant. Only that grant, for that digest, applies the saved state, and only if the tree
is still exactly as the run started. Nothing here runs a suite, Ghost, or the Judge:
the approval is a human decision about a result that was reviewed, not a new check.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Optional

from . import runstate
from .authorization import Authorization, is_stack_actor
from .guard import Snapshot

#: The operation a human grants to keep one held result. Distinct from "transform".
KEEP_OPERATION = "keep_unverified"


class HeldError(RuntimeError):
    """A held result cannot be kept. The message says why, in plain words."""


def _dir(target: Path) -> Path:
    path = runstate.state_dir(target) / "held"
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _b64(files: Dict[str, bytes]) -> Dict[str, str]:
    return {k: base64.b64encode(v).decode("ascii") for k, v in files.items()}


def _unb64(files: Dict[str, str]) -> Dict[str, bytes]:
    return {k: base64.b64decode(v.encode("ascii")) for k, v in files.items()}


def digest_of(files: Dict[str, bytes], git: Dict[str, bytes]) -> str:
    """A fingerprint of the exact saved state: every file path and its bytes, in order."""
    body = json.dumps({"files": _b64(files), "git": _b64(git)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def hold(target: Path, final: Snapshot, baseline: str, decision: str, reason: str,
         unmeasured: tuple[str, ...]) -> Optional[str]:
    """Save the final state of a run. Returns its digest, or None when it is too large to save."""
    if not final.restorable:
        return None
    digest = digest_of(final.files, final.git)
    record = {
        "digest": digest,
        "target": str(Path(target).resolve()),
        "baseline": baseline,
        "decision": decision,
        "reason": reason,
        "unmeasured": list(unmeasured),
        "files": _b64(final.files),
        "git": _b64(final.git),
    }
    path = _dir(Path(target)) / f"{digest}.json"
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh)
    os.replace(tmp, path)
    return digest


def load(target: Path, digest: str) -> dict:
    """The saved record for `digest`, checked: its contents must still produce that digest."""
    if not digest or not all(c in "0123456789abcdef" for c in digest) or len(digest) != 64:
        raise HeldError("That is not a held-result digest.")
    path = _dir(Path(target)) / f"{digest}.json"
    if not path.is_file():
        raise HeldError("No held result has that digest for this folder.")
    record = json.loads(path.read_text(encoding="utf-8"))
    files, git = _unb64(record["files"]), _unb64(record["git"])
    if digest_of(files, git) != digest or record.get("digest") != digest:
        raise HeldError("The saved result does not match its digest, so it was not applied.")
    if record.get("target") != str(Path(target).resolve()):
        raise HeldError("The saved result belongs to a different folder.")
    return record


def keep(target: Path, digest: str, authorization: Optional[Authorization]) -> dict:
    """Apply one held result, only with a human grant for this exact digest and folder."""
    from .tagteam import _fingerprint  # local import: tagteam imports this module

    target = Path(target).resolve()
    if authorization is None or not authorization.granted:
        raise HeldError("No granted authorization was given, so nothing was kept.")
    if authorization.operation != KEEP_OPERATION:
        raise HeldError(f"The grant is for {authorization.operation!r}, not {KEEP_OPERATION!r}.")
    if authorization.subject != f"{target}@{digest}":
        raise HeldError("The grant names a different result or folder, so nothing was kept.")
    if not authorization.actor.strip() or is_stack_actor(authorization.actor):
        raise HeldError("A part of the stack cannot approve keeping a result; a human must.")

    record = load(target, digest)
    lock = runstate.TargetLock(target)
    try:
        held = lock.acquire()
    except runstate.StateUnavailable as exc:
        raise HeldError(f"Warden could not set up its lock for this folder ({exc}).") from exc
    if not held:
        raise HeldError(runstate.BUSY_NOTE + ". Nothing was kept.")
    try:
        if _fingerprint(target) != record["baseline"]:
            raise HeldError("The folder is not in the state the run started from, so the held result "
                            "cannot be applied safely. Nothing was kept.")
        before = Snapshot(target)
        runstate.write_journal(target, {**before.files, **before.git})
        plan = Snapshot(target)
        plan.files = _unb64(record["files"])
        plan.git = _unb64(record["git"])
        plan.restorable = True
        try:
            plan.restore()
            after = Snapshot(target)
            if after.files != plan.files or after.git != plan.git:
                raise HeldError("Applying the held result did not give the reviewed state; it was undone.")
        except Exception:
            before.restore()
            raise
        runstate.clear_journal(target)
        return {"decision": "KEPT", "digest": digest, "reason":
                "The reviewed unverified result was kept under a human grant for this exact digest. "
                "The checks it lacked (" + (", ".join(record["unmeasured"]) or "none recorded") + ") "
                "were NOT run and nothing here says they would have passed."}
    finally:
        lock.release()
