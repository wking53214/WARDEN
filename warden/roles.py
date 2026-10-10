"""The two seats Warden seats other repositories in.

Warden is the governor. It is the only thing that writes, and it decides when
the loop is done. It does not know what a good fix looks like, and it does not
know what beautiful code looks like. Two other repositories answer those:

  Drafter    in the loop. Looks at what Ghost found and proposes ONE change.
              A proposal is data. A Drafter never writes.
  Finisher    after the loop, once. Beautifies the converged code and writes
              the final README. Its output is also a proposal; Warden applies
              it under the same gate (grant, green suite, Ghost no worse).

A third seat decides. The Judge is handed the evidence of the whole run and
returns a verdict; it measures nothing and writes nothing, and Warden may not
say ACCEPT without it:

  Judge      at the end, once. Reads the evidence and says ACCEPT, REJECT or
              INSUFFICIENT. REJECT puts the whole tree back as it was found.

Neither maker seat may decide that it is right. Warden checks the suite and Ghost
checks the result, so no one grades their own work.

Warden never imports the repositories that fill these seats; they import
Warden's data shapes. The tests prove it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Protocol, runtime_checkable

from .models import Defect, Transformation
from .suite import SuiteRun


@dataclass(frozen=True)
class Facts:
    """What Warden and Ghost measured at the converged state, handed to the Finisher.

    The Finisher counts and detects nothing itself. If it states a test result
    or a remaining problem, it is quoting this.
    """

    #: The target's own suite, run by Warden after the loop. None: it was not run.
    suite: Optional[SuiteRun]
    #: What Ghost still reports. Converged means no proposals are left, not that this is empty.
    remaining: tuple[Defect, ...]
    #: How many loop cycles ran.
    cycles: int
    #: Checks that did not run ("ghost", "swizzle", "suite"). Empty `remaining` with
    #: "ghost" here means Ghost was never asked, not that nothing is wrong.
    unmeasured: tuple[str, ...] = ()


@runtime_checkable
class Drafter(Protocol):
    """Called once per loop cycle. Returns None when it has nothing left to propose."""

    def propose(self, target: Path, observed: tuple[Defect, ...], baseline: str) -> Optional[Transformation]: ...


@runtime_checkable
class Finisher(Protocol):
    """Called once, after the loop has converged. Returns None if nothing to finish."""

    def finish(self, target: Path, baseline: str, facts: Facts) -> Optional[Transformation]: ...


@dataclass(frozen=True)
class Evidence:
    """Everything a Judge may rely on, measured by someone other than the Judge.

    Warden assembles it. Ghost, the suite and SWIZZLE produced the numbers.
    None means "not measured", which is never the same as "fine".
    """

    target: str
    #: The human grant's scope: "documentation" or "code".
    scope: str
    #: (cycle number, outcome) for every cycle that ran.
    cycles: tuple[tuple[int, str], ...]
    #: (path, kind) of every edit that was actually applied, finishing included.
    changed: tuple[tuple[str, str], ...]
    #: Of those, the paths that decide acceptability (tests, test config, CI).
    judging_files_touched: tuple[str, ...]
    suite_before: Optional[SuiteRun]
    suite_after: Optional[SuiteRun]
    #: Ghost finding identities at the start and at the end. None: Ghost never ran.
    ghost_before: Optional[tuple[str, ...]]
    ghost_after: Optional[tuple[str, ...]]
    #: Removals that failed a test and were left in place.
    declined: tuple[str, ...]
    #: True: SWIZZLE's own proofs held. False: they did not. None: not run.
    swizzle_proofs: Optional[bool]
    #: SWIZZLE's attacks on the governor, as reported ({scenario, severity, status}). None: not run.
    attacks: Optional[tuple[Mapping[str, str], ...]]
    #: Checks that never ran, by name.
    unmeasured: tuple[str, ...]
    notes: tuple[str, ...] = field(default=())
    #: Ghost graded against ASSAY's answer key: key_proven, failure_modes, caught,
    #: escaped, misnamed, floor (the fewest failure modes Ghost must catch). None: not run.
    assay: Optional[Mapping[str, object]] = None
    #: Ghost's own account of its baseline file (findings it was told to ignore), as {path, suppressed},
    #: at the first observation and at the last. None: Ghost did not say (old Ghost, or no usable count).
    #: A Judge compares them; growth means findings were hidden. Added without changing CONTRACT "1".
    ghost_baseline_before: Optional[Mapping[str, object]] = None
    ghost_baseline_after: Optional[Mapping[str, object]] = None


@dataclass(frozen=True)
class Verdict:
    """The Judge's decision. ACCEPT, REJECT, or INSUFFICIENT (cannot decide on this evidence)."""

    decision: str
    reasons: tuple[str, ...]
    judge: str = ""


@runtime_checkable
class Judge(Protocol):
    """Called once, at the very end. It reads evidence; it does not measure or write."""

    def decide(self, evidence: Evidence) -> Verdict: ...
