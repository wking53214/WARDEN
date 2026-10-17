"""The horsemen interface as Warden's own command line uses it.

`warden tagteam ... --receipt FILE` calls `receipt_for_run` after a run. It walks a real
`HorsemenWorkflow` through the handoffs the run produced, with the adapters doing the reading:

  ASSAY        `AssayAdapter.load_registry` reads the published answer key (when `--assay-root` is given);
               an unusable key is recorded as UNKNOWN, never as "no specimens"
  ghost_tools  `GhostToolsAdapter.handoff_findings` for what Ghost saw before and after
  SWIZZLE      `SwizzleAdapter.handoff_verdicts` for the proofs and the attacks on the governor
  Warden       the proposal, the scoped human grant, the transformation and the production receipt

Nothing here decides anything: the run's decision was made by `warden.tagteam`, and the receipt
only records it. A run with no human grant has no receipt (`finalize` refuses to write one).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from ..authorization import Authorization
from .adapters import (AssayAdapter, AssayUnavailable, GhostFinding, GhostToolsAdapter, SwizzleAdapter,
                       SwizzleVerdict)
from .authorization_scope import ChangeClass
from .receipt import ProductionReceipt
from .workflow import HorsemenWorkflow

logger = logging.getLogger("warden.horsemen")

#: The `--scope` values of the command line, as change classes.
SCOPE_CLASSES = {"documentation": ChangeClass.DOCUMENTATION_ONLY, "code": ChangeClass.CLEANUP}

#: Warden's decision, as the verdict a receipt carries. Only a plain ACCEPT is approved.
_FINAL_VERDICTS = {"ACCEPT": "APPROVED"}


def _finding(defect: Any) -> GhostFinding:
    return GhostFinding(
        finding_id=str(getattr(defect, "ghost_id", "") or ""),
        summary=str(getattr(defect, "summary", "") or ""),
        severity=str(getattr(getattr(defect, "severity", ""), "value", getattr(defect, "severity", "")) or "medium"),
        path=getattr(defect, "file", None),
        classification=str(getattr(defect, "detector", "") or "UNKNOWN"),
        epistemic_state="REASONED",
    )


def _swizzle_verdicts(result: Any) -> list[SwizzleVerdict]:
    verdicts = []
    if result.swizzle_sound is not None:
        verdicts.append(SwizzleVerdict(
            verdict_id="swizzle.proofs", result="PASSED" if result.swizzle_sound else "FAILED",
            summary="SWIZZLE's own planted-defect proofs", oracle_basis="INSTRUMENT_CALIBRATION"))
    for attack in result.attacks or ():
        status = str(attack.get("status", "")).lower() if isinstance(attack, dict) else ""
        verdicts.append(SwizzleVerdict(
            verdict_id=str(attack.get("scenario", "")) if isinstance(attack, dict) else "",
            result={"held": "PASSED", "violated": "FAILED"}.get(status, "UNKNOWN"),
            summary=f"attack on the governor, severity {attack.get('severity', '?')}"
            if isinstance(attack, dict) else ""))
    return verdicts


def receipt_for_run(*, result: Any, target: Path, authorization: Optional[Authorization],
                    baseline_sha: str, assay_root: Optional[Path] = None) -> ProductionReceipt:
    """The production receipt for one finished `TagTeamResult`.

    Raises `Unauthorized` when the run had no human grant, because a receipt without an authorization
    is not a record of a governed change.
    """
    from ..authorization import Unauthorized
    if authorization is None or not authorization.granted:
        raise Unauthorized("A receipt is written only for a run that had a human grant.")
    change_class = SCOPE_CLASSES.get(authorization.scope, ChangeClass.CLEANUP)
    assay, ghost, swizzle = AssayAdapter(assay_root), GhostToolsAdapter(), SwizzleAdapter()
    flow = HorsemenWorkflow(assay=assay, ghost=ghost, swizzle=swizzle)
    repository = str(Path(target).resolve())
    state = flow.start(repository=repository, baseline_id=result.baseline or "unfingerprinted",
                       baseline_sha=baseline_sha, change_class=change_class)
    wid = state.workflow_id

    specimens = []
    if assay_root is not None:
        try:
            specimens = assay.load_registry()
        except AssayUnavailable as err:
            state.notes.append(f"UNKNOWN: ASSAY's answer key could not be read ({err})")
            logger.warning("receipt: ASSAY registry unavailable: %s", err)
    else:
        state.notes.append("UNKNOWN: no ASSAY root was given, so no specimens were read")
    flow.ingest_specimens(wid, specimens)
    flow.ingest_findings(wid, [_finding(d) for d in result.observed])
    flow.ingest_adversarial(wid, _swizzle_verdicts(result))

    proposals = [c.proposal for c in result.cycles if c.proposal is not None]
    flow.propose(wid, {"cycles": len(result.cycles), "proposals": len(proposals),
                       "intents": [p.intent for p in proposals][:20]})
    flow.authorize(wid, actor=authorization.actor, operation=authorization.operation,
                   subject=authorization.subject, reason=authorization.reason)

    changed = sorted({e.path for c in result.cycles if c.applied and c.proposal for e in c.proposal.edits}
                     | {e.path for e in (result.finish.edits if result.finish is not None and result.finished else ())})
    if changed:
        flow.transform(wid, current_sha=baseline_sha, operation=authorization.operation,
                       subject=authorization.subject, edit_fn=lambda: changed)
    flow.ingest_findings(wid, [_finding(d) for d in result.reobserved], phase="reinspect")
    if result.put_back:
        state.notes.append("UNKNOWN: the changes were put back, so nothing stands in the tree")
    unmeasured = [f"UNKNOWN: {name} was not measured" for name in result.unmeasured]
    state.notes.extend(unmeasured)

    after = baseline_sha + ("+uncommitted" if changed and not result.put_back else "")
    verdict = _FINAL_VERDICTS.get(result.decision, result.decision)
    receipt = flow.finalize(wid, after_revision=after, final_verdict=verdict, cns_readiness="UNKNOWN")
    logger.info("receipt %s: %s, %d handoff(s)", receipt.receipt_id, receipt.final_verdict, len(receipt.handoff_ids))
    return receipt
