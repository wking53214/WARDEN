"""SWIZZLE consumer: is the adversary's own instrument sound?

SWIZZLE owns adversarial challenge. Warden must not become SWIZZLE. What
Warden asks of it is one calibration question before it will write anything:
do SWIZZLE's own planted defects still all get proven? (`swizzle prove`).

The independent post-change oracle used to live here. It judges documentation,
which is a craft question, so it moved to Burnish with the rest of the
beautification. Warden now receives its verdict through `warden.craft`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .isolation import absolute, run_instrument


def swizzle_proofs_hold(
    *,
    swizzle_root: Optional[Path] = None,
    python: str = sys.executable,
) -> tuple[bool, str]:
    """Whether SWIZZLE's own instrument is sound: every planted defect proven.

    This is a calibration check on the adversary, not a judgement of the
    target. An adversary whose proofs fail cannot back an ACCEPT. Returns
    (holds, one-line summary); a run that cannot start is (False, reason).
    """
    try:
        proc = run_instrument([python, "-m", "swizzle.cli", "prove"],
                              roots=[swizzle_root], timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"SWIZZLE proofs could not run: {exc}"
    return _read_proofs(proc)


#: A whole line, and nothing else on it. Text inside another line does not count.
_PROOFS_LINE = re.compile(r"^[ \t]*(\d+) of (\d+) proofs hold\.?[ \t]*$", re.MULTILINE)


def _read_proofs(proc) -> tuple[bool, str]:
    """Strict reading of `swizzle prove`: exit 0, a whole line 'N of M proofs hold', N == M, M >= 1."""
    counts = [(int(a), int(b)) for a, b in _PROOFS_LINE.findall(proc.stdout)]
    if proc.returncode != 0:
        why = (proc.stderr.strip().splitlines() or proc.stdout.strip().splitlines() or ["no output"])[-1]
        return False, f"SWIZZLE proofs: not sound (exit {proc.returncode}): {why[:200]}"
    if not counts:
        why = (proc.stderr.strip().splitlines() or ["no 'N of M proofs hold' line"])[-1]
        return False, f"SWIZZLE proofs: not sound (no result line): {why[:200]}"
    held, total = counts[-1]
    if total < 1:
        return False, "SWIZZLE proofs: not sound (it ran 0 proofs, which proves nothing)"
    if any(a != b for a, b in counts):
        return False, f"SWIZZLE proofs: not sound ({held} of {total} proofs hold)"
    return True, f"SWIZZLE proofs: {held} of {total} proofs hold."


_STATUSES = {"held", "violated"}


def _tail(text: str, lines: int = 2, width: int = 200) -> str:
    kept = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()][-lines:]
    return " / ".join(kept)[-width:]


def governor_attacks(
    *,
    swizzle_root: Path,
    warden_root: Path,
    python: str = sys.executable,
    note: Optional[list] = None,
) -> Optional[tuple[dict, ...]]:
    """SWIZZLE's report on attacks against this governor, or None if they could not run.

    Report only: each item says whether an invariant held. None is "not
    measured", and a caller must not read it as "no problems". Exit codes 0
    and 1 are the only ones read (2 means something did not run). Every item
    must be a mapping with string scenario, severity and status, and the
    status must be exactly held or violated. When the report is not
    measured, the reason (with the tail of SWIZZLE's own stderr) is appended
    to `note`.
    """
    def unmeasured(why: str, stderr: str = "") -> None:
        if note is not None:
            tail = _tail(stderr)
            note.append(f"SWIZZLE attacks on the governor not measured: {why}" + (f" (SWIZZLE said: {tail})" if tail else ""))

    try:
        proc = run_instrument(
            [python, "-m", "swizzle.cli", "governor", "--warden", str(absolute(warden_root)), "--json"],
            roots=[swizzle_root], timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        unmeasured(f"it could not run ({type(exc).__name__})")
        return None
    if proc.returncode not in (0, 1):
        unmeasured(f"it exited {proc.returncode}, so at least one attack did not run", proc.stderr)
        return None
    try:
        items = json.loads(proc.stdout)
    except ValueError:
        unmeasured("its report was not readable JSON", proc.stderr)
        return None
    if not isinstance(items, list) or not items:
        unmeasured("its report was empty or not a list", proc.stderr)
        return None
    out = []
    for item in items:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("scenario", "severity", "status")):
            unmeasured("an item in its report was malformed", proc.stderr)
            return None
        status = item["status"].strip().lower()
        if status not in _STATUSES:
            unmeasured(f"an attack ended as {item['status'][:30]!r}, not held or violated", proc.stderr)
            return None
        out.append({"scenario": item["scenario"], "severity": item["severity"], "status": status})
    return tuple(out)


_OUTCOMES = {"banished", "escaped", "misnamed"}


def _parse_card(text: str):
    """The ASSAY card as a dict. A banner before the JSON is ignored only if everything after it parses."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    lines = text.splitlines(keepends=True)
    for n, line in enumerate(lines):
        if n and line.lstrip().startswith(("{", "[")):
            try:
                return json.loads("".join(lines[n:]))
            except ValueError:
                continue
    raise ValueError("unreadable")


#: Why the answer-key proof sometimes fails without the key being wrong: ASSAY's verifier could not start or
#: ran out of time. A count that disagrees ("28/29 claims hold") is NOT in this list and is never retried.
_TRANSIENT = re.compile(r"could not run|timed out|timeout|temporarily unavailable|text file busy|resource busy",
                        re.IGNORECASE)


def _read_failure(proc) -> tuple[str, bool]:
    """(the real reason ASSAY grading exited 2, whether it looks temporary).

    SWIZZLE prints its card on stdout before it exits 2, and the card says whether the key was proven and
    why not; its last stderr line only says how many specimens it could not score. Both are relayed.
    """
    said = ""
    transient = False
    try:
        card = _parse_card(proc.stdout)
    except ValueError:
        card = None
    if isinstance(card, dict):
        proof = card.get("proof")
        proof = proof if isinstance(proof, str) else ""
        if card.get("key_proven") is False or proof.startswith("NOT PROVEN"):
            said = "the answer key was not proven: " + " ".join(proof.split())[:300]
            transient = bool(_TRANSIENT.search(proof))
        else:
            stuck = sorted({str(j.get("outcome")) for j in card.get("judgements", [])
                            if isinstance(j, dict) and j.get("outcome") in ("UNMAPPED", "UNSUMMONED")})
            if stuck:
                said = "specimens could not be scored (" + ", ".join(stuck) + ")"
    err = (proc.stderr.strip().splitlines() or [""])[-1].strip()
    if err:
        said = f"{said}; SWIZZLE said: {err[:200]}" if said else err[:200]
    return said or "no reason given", transient


def assay_score(
    *,
    swizzle_root: Path,
    assay_root: Path,
    ghost_root: Optional[Path] = None,
    python: str = sys.executable,
) -> tuple[Optional[bool], dict, str]:
    """Ghost graded against ASSAY's answer key, by SWIZZLE's `assay` command.

    Returns (state, score, one-line summary). state is True when the key was
    proven and every specimen was scored, False when the key is unproven or
    something could not be scored (never read that as a pass), and None when
    the grading could not run at all. Warden only relays; the grading is
    SWIZZLE's and the answers are ASSAY's.
    """
    cmd = [python, "-m", "swizzle.cli", "assay", "--assay", str(absolute(assay_root)), "--json"]
    if ghost_root is not None:
        cmd += ["--ghost-tools", str(absolute(ghost_root))]
    retried = False
    while True:
        try:
            proc = run_instrument(cmd, roots=[swizzle_root], timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, {}, f"ASSAY grading could not run: {exc}"
        if proc.returncode != 2:
            break
        why, transient = _read_failure(proc)
        if transient and not retried:
            retried = True  # the proof is run again exactly as before; it is not weakened or skipped
            continue
        tail = " (the answer key proof was run twice; the first failure looked temporary)" if retried else ""
        return False, {}, f"ASSAY grading failed (key unproven or specimen unscorable): {why}{tail}"
    if proc.returncode != 0:
        return None, {}, f"ASSAY grading exited {proc.returncode}"
    try:
        card = _parse_card(proc.stdout)
        judgements = card["judgements"]
    except (ValueError, KeyError, TypeError):
        return None, {}, "ASSAY grading printed something unreadable"
    if not isinstance(judgements, list) or not judgements or not all(isinstance(j, dict) for j in judgements):
        return None, {}, "ASSAY grading printed judgements that are not a list of records"
    modes = [j for j in judgements if j.get("specimen_class") == "FAILURE_MODE"]
    if not modes:
        return None, {}, "ASSAY grading scored no failure-mode specimens, so Ghost was not graded"
    odd = sorted({str(j.get("outcome"))[:30] for j in modes if j.get("outcome") not in _OUTCOMES})
    if odd:
        return False, {}, f"ASSAY grading gave outcomes Warden does not know ({', '.join(odd)}); Ghost was not graded"
    score = {
        "key_proven": True,
        "failure_modes": len(modes),
        "caught": sum(j["outcome"] == "banished" for j in modes),
        "escaped": sum(j["outcome"] == "escaped" for j in modes),
        "misnamed": sum(j["outcome"] == "misnamed" for j in modes),
        "proof": str(card.get("proof", "")),
    }
    again = " (the answer key proof failed once for a temporary reason and held on the second run)" if retried else ""
    return True, score, (f"ASSAY: Ghost caught {score['caught']} of {score['failure_modes']} "
                         f"known failure modes ({score['proof']}){again}")
