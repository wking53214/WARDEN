"""Four Horsemen interface for Warden.

"Four Horsemen" is the older name of this interface; the circuit now has five seats.
"""
from .contracts import Handoff, HandoffKind, EpistemicLabel
from .authorization_scope import (
    ScopedGrant, ScopeSpec, ChangeClass, grant_scoped, validate_scoped, ScopeViolation,
)
from .adapters import (
    AssayAdapter, GhostToolsAdapter, SwizzleAdapter,
    SpecimenRef, GhostFinding, SwizzleVerdict, AssayUnavailable,
)
from .workflow import HorsemenWorkflow, WorkflowPhase, WorkflowState
from .receipt import ProductionReceipt, emit_receipt
from .circuit import receipt_for_run

__all__ = [
    "Handoff", "HandoffKind", "EpistemicLabel",
    "ScopedGrant", "ScopeSpec", "ChangeClass", "grant_scoped", "validate_scoped", "ScopeViolation",
    "AssayAdapter", "GhostToolsAdapter", "SwizzleAdapter",
    "SpecimenRef", "GhostFinding", "SwizzleVerdict", "AssayUnavailable",
    "HorsemenWorkflow", "WorkflowPhase", "WorkflowState",
    "ProductionReceipt", "emit_receipt", "receipt_for_run",
]
