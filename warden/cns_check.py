"""Check only: do the records Warden reads meet the CNS rows, and say so in the notes.

WHY THIS EXISTS

Warden reads two records written by other repositories: Ghost Tools' findings and
SWIZZLE's attack results. The CNS rows `cns.finding` and `cns.attack` say what those
records should hold. Until now nothing compared the two, so a record that drifted from
the contract was read quietly and the drift was found, if ever, by a broken run.

WHAT THIS DOES

It reads each record against its row and returns a note for each kind that does not
meet it. A clean record returns no note, so a clean run's notes are unchanged.

WHAT THIS DOES NOT DO

It decides nothing. The records are still read exactly as before, and no decision,
verdict or exit code depends on what this returns. Turning a failed check into a refusal
is a separate change, made on purpose, after a run shows the rows hold on real data.
"""

from __future__ import annotations

from typing import Any, List, Sequence

from cns.attack import AttackResult
from cns.finding import Finding

__all__ = ["finding_notes", "attack_notes"]

_SHOWN = 3


def finding_notes(findings: Sequence[Any]) -> List[str]:
    """Notes for the Ghost findings that do not meet cns.finding/1. Empty when all do."""
    return _notes(findings, "Ghost Tools finding", "cns.finding/1", Finding.from_dict)


def attack_notes(attacks: Sequence[Any]) -> List[str]:
    """Notes for the SWIZZLE attack results that do not meet cns.attack/1. Empty when all do."""
    return _notes(attacks, "SWIZZLE attack result", "cns.attack/1", AttackResult.from_dict)


def _notes(records: Sequence[Any], kind: str, contract: str, read) -> List[str]:
    bad: List[str] = []
    for raw in records:
        try:
            read(raw)
        except (ValueError, TypeError) as err:
            bad.append(str(err))
    if not bad:
        return []
    shown = "; ".join(bad[:_SHOWN])
    if len(bad) > _SHOWN:
        shown += f"; and {len(bad) - _SHOWN} more"
    return [f"CNS check (nothing decided on it): {len(bad)} of {len(records)} {kind}s do not meet "
            f"{contract}: {shown}"]
