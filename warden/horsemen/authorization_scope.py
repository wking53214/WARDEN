"""Scoped authorization for horsemen transformations."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid
from ..authorization import Authorization, Unauthorized, grant as base_grant

class ChangeClass(str, Enum):
    CLEANUP = "CLEANUP"
    CONSOLIDATION = "CONSOLIDATION"
    BUG_FIX = "BUG_FIX"
    ARCHITECTURAL_REFACTOR = "ARCHITECTURAL_REFACTOR"
    CNS_ADAPTER_CREATION = "CNS_ADAPTER_CREATION"
    CNS_ADAPTER_MODIFICATION = "CNS_ADAPTER_MODIFICATION"
    SECURITY_HARDENING = "SECURITY_HARDENING"
    TEST_ONLY = "TEST_ONLY"
    DOCUMENTATION_ONLY = "DOCUMENTATION_ONLY"

HIGH_RISK_CLASSES = frozenset({
    ChangeClass.ARCHITECTURAL_REFACTOR,
    ChangeClass.CNS_ADAPTER_CREATION,
    ChangeClass.CNS_ADAPTER_MODIFICATION,
    ChangeClass.SECURITY_HARDENING,
})

class ScopeViolation(Unauthorized):
    pass

@dataclass(frozen=True)
class ScopeSpec:
    repository: str
    baseline_id: str
    operations: tuple
    subjects: tuple
    change_classes: tuple
    constraints: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ScopedGrant:
    authorization_id: str
    base: Authorization
    scope: ScopeSpec
    change_class: ChangeClass
    proposal_id: str
    adversarial_verdict_id: Optional[str] = None
    expiration: Optional[str] = None
    delegation_chain: tuple = ()
    authority_source: str = "human_operator"
    authority_provenance: str = ""

    def permits(self, operation, subject, baseline_id, change_class=None,
                now=None, repository=None):
        if not self.base.granted:
            return False
        now = now or datetime.now(timezone.utc)
        if self.expiration:
            exp = datetime.fromisoformat(self.expiration.replace("Z", "+00:00"))
            if now > exp:
                return False
        if baseline_id != self.scope.baseline_id:
            return False
        if repository is None or repository != self.scope.repository:
            return False
        # The base grant and the scope must independently permit access.
        # Empty allowlists deny access rather than widening the grant.
        if operation != self.base.operation:
            return False
        if operation not in self.scope.operations:
            return False
        if subject != self.base.subject:
            return False
        if subject not in self.scope.subjects:
            return False
        # Reject strings and other unexpected types before accessing .value.
        if not isinstance(change_class, ChangeClass):
            return False
        if change_class != self.change_class:
            return False
        if change_class.value not in self.scope.change_classes:
            return False
        return True

def grant_scoped(*, actor, operation, subject, scope, change_class, proposal_id, reason,
                 adversarial_verdict_id=None, authority_source="human_operator",
                 authority_provenance="", expiration=None, delegation_chain=()):
    if change_class in HIGH_RISK_CLASSES and not adversarial_verdict_id:
        raise Unauthorized(
            f"High-risk change class {change_class.value} requires a prior adversarial verdict id (SWIZZLE)."
        )
    if not authority_provenance.strip() and authority_source == "human_operator":
        authority_provenance = f"human grant by {actor}"
    base = base_grant(
        actor=actor, operation=operation, subject=subject,
        scope=f"{scope.repository}:{scope.baseline_id}:{change_class.value}",
        reason=reason,
    )
    return ScopedGrant(
        authorization_id=f"auth_{uuid.uuid4().hex[:12]}",
        base=base, scope=scope, change_class=change_class, proposal_id=proposal_id,
        adversarial_verdict_id=adversarial_verdict_id, expiration=expiration,
        delegation_chain=tuple(delegation_chain),
        authority_source=authority_source, authority_provenance=authority_provenance,
    )

def validate_scoped(grant, *, operation, subject, baseline_id, change_class,
                    repository):
    if not grant.permits(
        operation, subject, baseline_id, change_class, repository=repository
    ):
        raise ScopeViolation(
            f"Authorization {grant.authorization_id} does not permit "
            f"op={operation!r} subject={subject!r} baseline={baseline_id!r} "
            f"repository={repository!r} class={getattr(change_class, 'value', None)!r}"
        )
