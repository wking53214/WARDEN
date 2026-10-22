"""Truthful epistemic language.

Warden uses this vocabulary for *its own* claims about architecture and
documentation. When Ghost Tools already has a stronger native vocabulary
(CONFIRMED / REASONED / SUPPRESSED), Warden preserves that vocabulary on
consumed findings and does not rename it for cosmetic consistency.

These states are not a confidence score. They are a contract about what
kind of evidence exists.
"""

from __future__ import annotations

from cns.epistemic import EpistemicState as EpistemicState  # shared with CNS 2.0.0; re-exported here



# Ghost Tools forensic vocabulary, consumed not replaced.
GHOST_STATUS = frozenset({"confirmed", "reasoned", "confirmed_by_review", "rejected", "suppressed"})
