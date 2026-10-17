"""Four Horsemen workflow orchestration owned by Warden."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from ..authorization import Unauthorized
from .authorization_scope import (
    ChangeClass, HIGH_RISK_CLASSES, ScopeSpec, ScopedGrant, grant_scoped, validate_scoped,
)
from .adapters import GhostFinding, GhostToolsAdapter, SpecimenRef, SwizzleAdapter, SwizzleVerdict, AssayAdapter
from .contracts import EpistemicLabel, Handoff, HandoffKind
from .receipt import ProductionReceipt, emit_receipt

class WorkflowPhase(str, Enum):
    FREEZE_BASELINE = "FREEZE_BASELINE"
    ASSAY = "ASSAY"
    GHOST_INSPECT = "GHOST_INSPECT"
    PROPOSE = "PROPOSE"
    SWIZZLE_ADVERSARIAL = "SWIZZLE_ADVERSARIAL"
    HUMAN_AUTHORIZE = "HUMAN_AUTHORIZE"
    TRANSFORM = "TRANSFORM"
    GHOST_REINSPECT = "GHOST_REINSPECT"
    SWIZZLE_DIFFERENTIAL = "SWIZZLE_DIFFERENTIAL"
    CNS_AUDIT = "CNS_AUDIT"
    RECEIPT = "RECEIPT"

@dataclass
class PhaseRecord:
    phase: WorkflowPhase
    result: str
    timestamp: str
    handoff_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class WorkflowState:
    workflow_id: str
    repository: str
    baseline_id: str
    baseline_sha: str
    change_class: ChangeClass
    phases: List[PhaseRecord] = field(default_factory=list)
    handoffs: List[Handoff] = field(default_factory=list)
    specimens: List[SpecimenRef] = field(default_factory=list)
    findings_before: List[GhostFinding] = field(default_factory=list)
    findings_after: List[GhostFinding] = field(default_factory=list)
    adversarial_verdicts: List[SwizzleVerdict] = field(default_factory=list)
    differential_verdicts: List[SwizzleVerdict] = field(default_factory=list)
    proposal_id: Optional[str] = None
    proposal_payload: Dict[str, Any] = field(default_factory=dict)
    grant: Optional[ScopedGrant] = None
    files_changed: List[str] = field(default_factory=list)
    cns_recommendation: Optional[str] = None
    receipt: Optional[ProductionReceipt] = None
    status: str = "active"
    notes: List[str] = field(default_factory=list)

    def _record(self, phase, result, handoff=None, **details):
        self.phases.append(PhaseRecord(
            phase=phase, result=result,
            timestamp=datetime.now(timezone.utc).isoformat(),
            handoff_id=handoff.handoff_id if handoff else None, details=details,
        ))
        if handoff:
            handoff.assert_not_unknown_as_confirmed()
            self.handoffs.append(handoff)

class HorsemenWorkflow:
    def __init__(self, *, assay=None, ghost=None, swizzle=None):
        self.assay = assay or AssayAdapter()
        self.ghost = ghost or GhostToolsAdapter()
        self.swizzle = swizzle or SwizzleAdapter()
        self.states = {}

    def start(self, *, repository, baseline_id, baseline_sha, change_class):
        st = WorkflowState(
            workflow_id=f"wf_{uuid.uuid4().hex[:12]}",
            repository=repository, baseline_id=baseline_id,
            baseline_sha=baseline_sha, change_class=change_class,
        )
        st._record(WorkflowPhase.FREEZE_BASELINE, "ok", baseline_id=baseline_id, sha=baseline_sha)
        self.states[st.workflow_id] = st
        return st

    def ingest_specimens(self, workflow_id, specimens):
        st = self.states[workflow_id]
        st.specimens = list(specimens)
        hof = self.assay.handoff_specimens(
            specimens, repository=st.repository, repository_sha=st.baseline_sha, baseline_id=st.baseline_id,
        )
        st._record(WorkflowPhase.ASSAY, hof.result or "ok", hof, count=len(specimens))
        return hof

    def ingest_findings(self, workflow_id, findings, *, phase="inspect"):
        st = self.states[workflow_id]
        if phase == "reinspect":
            st.findings_after = list(findings)
            wf_phase = WorkflowPhase.GHOST_REINSPECT
        else:
            st.findings_before = list(findings)
            wf_phase = WorkflowPhase.GHOST_INSPECT
        hof = self.ghost.handoff_findings(
            findings, repository=st.repository, repository_sha=st.baseline_sha,
            baseline_id=st.baseline_id, phase=phase,
        )
        st._record(wf_phase, hof.result or "ok", hof, count=len(findings))
        return hof

    def propose(self, workflow_id, proposal_payload):
        st = self.states[workflow_id]
        st.proposal_id = proposal_payload.get("proposal_id") or f"prop_{uuid.uuid4().hex[:12]}"
        st.proposal_payload = dict(proposal_payload)
        st.proposal_payload["proposal_id"] = st.proposal_id
        st.proposal_payload["change_class"] = st.change_class.value
        st.proposal_payload["baseline_id"] = st.baseline_id
        hof = Handoff.make(
            producer="Warden", consumer="SWIZZLE", kind=HandoffKind.PROPOSAL,
            repository=st.repository, repository_sha=st.baseline_sha, baseline_id=st.baseline_id,
            epistemic_state=EpistemicLabel.REASONED, payload=st.proposal_payload, result="PROPOSED",
        )
        st._record(WorkflowPhase.PROPOSE, "PROPOSED", hof)
        return hof

    def ingest_adversarial(self, workflow_id, verdicts):
        st = self.states[workflow_id]
        st.adversarial_verdicts = list(verdicts)
        hof = self.swizzle.handoff_verdicts(
            verdicts, repository=st.repository, repository_sha=st.baseline_sha,
            baseline_id=st.baseline_id, phase="adversarial",
        )
        st._record(WorkflowPhase.SWIZZLE_ADVERSARIAL, hof.result or "UNKNOWN", hof)
        return hof

    def ingest_differential(self, workflow_id, verdicts):
        st = self.states[workflow_id]
        st.differential_verdicts = list(verdicts)
        hof = self.swizzle.handoff_verdicts(
            verdicts, repository=st.repository, repository_sha=st.baseline_sha,
            baseline_id=st.baseline_id, phase="differential",
        )
        st._record(WorkflowPhase.SWIZZLE_DIFFERENTIAL, hof.result or "UNKNOWN", hof)
        return hof

    def authorize(self, workflow_id, *, actor, operation, subject, reason, scope=None,
                  authority_source="human_operator", authority_provenance=""):
        st = self.states[workflow_id]
        if not st.proposal_id:
            raise Unauthorized("Cannot authorize without a proposal.")
        if st.change_class in HIGH_RISK_CLASSES:
            adv_hofs = [h for h in st.handoffs
                        if h.kind == HandoffKind.VERDICT and h.payload.get("phase") == "adversarial"]
            if not adv_hofs or not self.swizzle.adversarial_passed(adv_hofs[-1]):
                raise Unauthorized(
                    f"High-risk {st.change_class.value} requires SWIZZLE adversarial PASSED."
                )
            adversarial_verdict_id = adv_hofs[-1].handoff_id
        else:
            adversarial_verdict_id = None
            adv_hofs = [h for h in st.handoffs if h.kind == HandoffKind.VERDICT]
            if adv_hofs:
                adversarial_verdict_id = adv_hofs[-1].handoff_id
        scope = scope or ScopeSpec(
            repository=st.repository, baseline_id=st.baseline_id,
            operations=(operation,), subjects=(subject,),
            change_classes=(st.change_class.value,),
        )
        grant = grant_scoped(
            actor=actor, operation=operation, subject=subject, scope=scope,
            change_class=st.change_class, proposal_id=st.proposal_id, reason=reason,
            adversarial_verdict_id=adversarial_verdict_id,
            authority_source=authority_source, authority_provenance=authority_provenance,
        )
        st.grant = grant
        hof = Handoff.make(
            producer="Warden", consumer="Warden", kind=HandoffKind.AUTHORIZATION,
            repository=st.repository, repository_sha=st.baseline_sha, baseline_id=st.baseline_id,
            epistemic_state=EpistemicLabel.CONFIRMED,
            payload={"authorization_id": grant.authorization_id, "actor": actor,
                     "operation": operation, "subject": subject,
                     "change_class": st.change_class.value,
                     "adversarial_verdict_id": adversarial_verdict_id},
            result="GRANTED", provenance=grant.authority_provenance,
        )
        st._record(WorkflowPhase.HUMAN_AUTHORIZE, "GRANTED", hof)
        return grant

    def transform(self, workflow_id, *, current_sha, operation, subject, edit_fn, invariant_checks=None):
        st = self.states[workflow_id]
        if not st.grant:
            raise Unauthorized("No scoped grant on file.")
        if current_sha != st.baseline_sha:
            raise Unauthorized(f"Baseline drifted: frozen={st.baseline_sha} current={current_sha}. REFUSE.")
        validate_scoped(st.grant, operation=operation, subject=subject,
                        baseline_id=st.baseline_id, change_class=st.change_class)
        files = edit_fn()
        for i, check in enumerate(invariant_checks or ()):
            if not check():
                raise Unauthorized(f"Invariant check {i} failed after edit; treat as refuse.")
        st.files_changed = list(files)
        hof = Handoff.make(
            producer="Warden", consumer="ghost_tools", kind=HandoffKind.TRANSFORMATION,
            repository=st.repository, repository_sha=current_sha, baseline_id=st.baseline_id,
            epistemic_state=EpistemicLabel.CONFIRMED,
            payload={"files_changed": files, "authorization_id": st.grant.authorization_id,
                     "proposal_id": st.proposal_id, "change_class": st.change_class.value},
            result="APPLIED",
        )
        st._record(WorkflowPhase.TRANSFORM, "APPLIED", hof, files=files)
        return files

    def record_cns_audit(self, workflow_id, recommendation, details=None):
        st = self.states[workflow_id]
        st.cns_recommendation = recommendation
        st._record(WorkflowPhase.CNS_AUDIT, recommendation, **(details or {}))
        st.notes.append("CNS audit is recommendation only; cns_modified=NO")

    def finalize(self, workflow_id, *, after_revision, final_verdict="REQUIRES_HUMAN_REVIEW",
                 cns_readiness="UNKNOWN", cns_adapter_location=None):
        st = self.states[workflow_id]
        if not st.grant:
            raise Unauthorized("Cannot emit receipt without authorization.")
        if cns_readiness == "UNKNOWN" and final_verdict == "CNS_READY":
            final_verdict = "UNKNOWN"
        before_ids = {f.finding_id for f in st.findings_before if f.finding_id}
        after_ids = {f.finding_id for f in st.findings_after if f.finding_id}
        receipt = emit_receipt(
            repository=st.repository, before_revision=st.baseline_sha, after_revision=after_revision,
            baseline_id=st.baseline_id, transformation_id=f"xform_{uuid.uuid4().hex[:12]}",
            proposal_id=st.proposal_id or "", authorization_id=st.grant.authorization_id,
            actor=st.grant.base.actor, authority_source=st.grant.authority_source,
            change_class=st.change_class.value, scope_summary=st.grant.base.scope,
            findings_addressed=sorted(before_ids - after_ids), findings_remaining=sorted(after_ids),
            unknowns=[n for n in st.notes if "UNKNOWN" in n],
            specimens_used=[s.specimen_id for s in st.specimens],
            adversarial_cases=[v.verdict_id for v in st.adversarial_verdicts],
            regression_results={v.verdict_id: v.result for v in st.differential_verdicts},
            files_changed=st.files_changed, invariants_checked=[],
            cns_readiness=cns_readiness, cns_adapter_location=cns_adapter_location,
            final_verdict=final_verdict, handoff_ids=[h.handoff_id for h in st.handoffs],
        )
        st.receipt = receipt
        st.status = "complete"
        st._record(WorkflowPhase.RECEIPT, final_verdict, receipt_id=receipt.receipt_id)
        return receipt
