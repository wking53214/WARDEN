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

The grant's scope ("documentation" or "code") is Warden's to know and the makers'
to respect. A Drafter or Finisher that keeps a `scope` attribute is told the
grant's scope before it is first asked (Warden sets the attribute), so it can
leave out-of-scope proposals unmade instead of having them declined. A seat
without the attribute is asked as before; its proposals are checked against the
grant either way. Optional, and additive: the contract stays "1".

Warden never imports the repositories that fill these seats; they import
Warden's data shapes. The tests prove it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from .models import Defect, Transformation
from cns.seat import Evidence, Facts, Verdict  # the shared seat rows: cns 1.9.0



@runtime_checkable
class Drafter(Protocol):
    """Called once per loop cycle. Returns None when it has nothing left to propose.

    May keep a `scope` attribute; if it does, Warden sets it to the grant's scope first.
    """

    def propose(self, target: Path, observed: tuple[Defect, ...], baseline: str) -> Optional[Transformation]: ...


@runtime_checkable
class Finisher(Protocol):
    """Called once, after the loop has converged. Returns None if nothing to finish.

    May keep a `scope` attribute; if it does, Warden sets it to the grant's scope first.
    """

    def finish(self, target: Path, baseline: str, facts: Facts) -> Optional[Transformation]: ...






@runtime_checkable
class Judge(Protocol):
    """Called once, at the very end. It reads evidence; it does not measure or write."""

    def decide(self, evidence: Evidence) -> Verdict: ...
