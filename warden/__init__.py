"""Warden: the discipline of change.

WHAT THIS IS
    The governor of a code change. It decides whether a change may be made,
    whether it stands, and what is recorded. It does not decide what makes code
    a good fix or beautiful code look like; a Drafter (in the loop) and a
    Finisher (once, after it) do, through the seats in `warden.roles`.

WHAT IT OWNS
    Transformation proposals as data, the human authorization boundary, the
    Rule 7 test gate, the Rule 9 audit file, the SWIZZLE proof gate, and the
    tag-team loop that *calls* Ghost Tools, SWIZZLE and a craft without
    becoming any of them.

WHAT IT DOES NOT OWN
    The proposals (Drafter) and the beautifying and final README (Burnish). Forensic inspection (Ghost
    Tools). Adversarial challenge (SWIZZLE). Runtime governance contracts
    (CNS). Live admission, decision, custody.

WHAT IT MUST NEVER DO
    Silently alter code.
    Certify itself.
    Modify CNS.
    Convert UNKNOWN into APPROVED.
    Let a Drafter or Finisher's good opinion outvote a red suite or a missing grant.
"""

from .epistemic import EpistemicState
from .models import Defect, DefectLifecycle, Transformation, TransformationStatus
from .authorization import Authorization, Unauthorized
from .roles import Facts, Finisher, Drafter
from .tagteam import TagTeam, TagTeamResult
from .horsemen import HorsemenWorkflow, ChangeClass, ScopedGrant

__version__ = "0.11.1"

#: The version of the shapes other repositories build against: Evidence, Verdict, Facts and
#: Transformation. Bumped only when one of them changes in a way that breaks a seat written for
#: the old shape. A seat can declare `requires_contract = "1"`; `warden tagteam` refuses a seat
#: whose declared contract is not this one.
CONTRACT = "1"

__all__ = [
    "EpistemicState",
    "Defect",
    "DefectLifecycle",
    "Transformation",
    "TransformationStatus",
    "Authorization",
    "Unauthorized",
    "Drafter",
    "Finisher",
    "Facts",
    "TagTeam",
    "TagTeamResult",
    "HorsemenWorkflow",
    "ChangeClass",
    "ScopedGrant",
    "__version__",
    "CONTRACT",
]
