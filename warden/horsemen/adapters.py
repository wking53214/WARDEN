"""Adapters that consume other horsemen without becoming them."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
from .contracts import EpistemicLabel, Handoff, HandoffKind

@dataclass
class SpecimenRef:
    specimen_id: str
    specimen_class: str
    path: str
    expected_verdict: str
    epistemic_status: str
    isolation_required: bool = True

class AssayUnavailable(RuntimeError):
    """ASSAY's answer key could not be read. Never treated as 'no specimens'."""


class AssayAdapter:
    def __init__(self, assay_root=None):
        self.root = Path(assay_root) if assay_root else None

    def load_registry(self, registry_path=None):
        """Read ASSAY's published answer key (assay_production/registry.json).

        Fails loudly rather than returning an empty list: an empty specimen
        set looks exactly like "nothing to check" and cannot be told apart
        from a broken link. Silence is the defect.
        """
        if registry_path is None:
            if self.root is None:
                raise AssayUnavailable(
                    "no ASSAY root configured; pass assay_root or registry_path")
            registry_path = self.root / "assay_production" / "registry.json"
        registry_path = Path(registry_path)
        if not registry_path.is_file():
            raise AssayUnavailable(
                f"ASSAY registry not found at {registry_path}; generate it in ASSAY with "
                "`python3 -m assay_production.manifest_registry --write`")
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data:
            raise AssayUnavailable(f"ASSAY registry at {registry_path} is empty or malformed")
        base = self.root if self.root is not None else registry_path.parent.parent
        missing = [d.get("path", "") for d in data.values()
                   if not isinstance(d, dict) or not d.get("path") or not (base / d["path"]).is_file()]
        if missing:
            raise AssayUnavailable(
                f"ASSAY registry names {len(missing)} specimen file(s) that do not exist, "
                f"e.g. {missing[0]!r}")
        out = []
        for sid, d in data.items():
            out.append(SpecimenRef(
                specimen_id=d.get("specimen_id", sid),
                specimen_class=d.get("specimen_class", "UNKNOWN"),
                path=d.get("path", ""),
                expected_verdict=d.get("expected_verdict", "UNKNOWN"),
                epistemic_status=d.get("epistemic_status", "UNKNOWN"),
                isolation_required=bool(d.get("isolation_required", True)),
            ))
        return out

    def handoff_specimens(self, specimens, *, repository, repository_sha, baseline_id):
        return Handoff.make(
            producer="ASSAY", consumer="Warden", kind=HandoffKind.SPECIMEN,
            repository=repository, repository_sha=repository_sha, baseline_id=baseline_id,
            epistemic_state=EpistemicLabel.REASONED if specimens else EpistemicLabel.UNKNOWN,
            result="SPECIMENS_PROVIDED" if specimens else "NO_SPECIMENS_UNKNOWN",
            payload={"specimens": [
                {"specimen_id": s.specimen_id, "specimen_class": s.specimen_class,
                 "path": s.path, "expected_verdict": s.expected_verdict,
                 "epistemic_status": s.epistemic_status}
                for s in specimens
            ]},
            provenance="ASSAY specimen registry",
        )

@dataclass
class GhostFinding:
    finding_id: str
    summary: str
    severity: str
    path: Optional[str] = None
    classification: str = "UNKNOWN"
    epistemic_state: str = "REASONED"
    raw: Dict[str, Any] = field(default_factory=dict)

class GhostToolsAdapter:
    def __init__(self, ghost_tools_root=None):
        self.root = Path(ghost_tools_root) if ghost_tools_root else None

    def load_findings_json(self, path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("findings", raw.get("items", []))
        out = []
        for f in items:
            if not isinstance(f, dict):
                continue
            fid = f.get("id") or f.get("finding_id") or f.get("ghost_id") or ""
            out.append(GhostFinding(
                finding_id=str(fid),
                summary=str(f.get("summary") or f.get("message") or ""),
                severity=str(f.get("severity") or "medium"),
                path=f.get("path") or f.get("file"),
                classification=str(f.get("classification") or "UNKNOWN"),
                epistemic_state=str(f.get("epistemic_state") or f.get("status") or "REASONED"),
                raw=f,
            ))
        return out

    def handoff_findings(self, findings, *, repository, repository_sha, baseline_id, phase="inspect"):
        epistemic = EpistemicLabel.REASONED if findings else EpistemicLabel.UNKNOWN
        return Handoff.make(
            producer="ghost_tools", consumer="Warden", kind=HandoffKind.FINDING,
            repository=repository, repository_sha=repository_sha, baseline_id=baseline_id,
            epistemic_state=epistemic,
            payload={"phase": phase, "count": len(findings), "findings": [
                {"finding_id": f.finding_id, "summary": f.summary, "severity": f.severity,
                 "path": f.path, "classification": f.classification,
                 "epistemic_state": f.epistemic_state}
                for f in findings
            ]},
            result="OBSERVED" if findings else "NO_FINDINGS_UNKNOWN",
            provenance=f"ghost_tools {phase}",
        )

#: SWIZZLE results that mean the attack failed to hold, and the ones that mean it held. Anything else
#: is unread, and an unread result is never counted as a pass.
_FAILING = frozenset({"FAILED", "REJECT", "ESCAPED", "VIOLATED"})
_PASSING = frozenset({"PASSED", "PASS", "HELD", "OK"})


@dataclass
class SwizzleVerdict:
    verdict_id: str
    result: str
    attack_class: Optional[str] = None
    oracle_basis: str = "ADVERSARIAL"
    summary: str = ""
    epistemic_state: str = "REASONED"
    details: Dict[str, Any] = field(default_factory=dict)

class SwizzleAdapter:
    def __init__(self, swizzle_root=None):
        self.root = Path(swizzle_root) if swizzle_root else None

    def load_verdict_json(self, path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else raw.get("verdicts", raw.get("cases", [raw]))
        out = []
        for v in items:
            if not isinstance(v, dict):
                continue
            out.append(SwizzleVerdict(
                verdict_id=str(v.get("verdict_id") or v.get("case_id") or v.get("id") or ""),
                result=str(v.get("result") or v.get("outcome") or "UNKNOWN"),
                attack_class=v.get("attack_class"),
                oracle_basis=str(v.get("oracle_basis") or "ADVERSARIAL"),
                summary=str(v.get("summary") or ""),
                epistemic_state=str(v.get("epistemic_state") or "REASONED"),
                details=v,
            ))
        return out

    def handoff_verdicts(self, verdicts, *, repository, repository_sha, baseline_id, phase="adversarial"):
        failed = [v for v in verdicts if v.result.upper() in _FAILING]
        unread = [v for v in verdicts if v.result.upper() not in _FAILING and v.result.upper() not in _PASSING]
        if not verdicts:
            epistemic, result = EpistemicLabel.UNKNOWN, "NOT_TESTED"
        elif failed:
            epistemic, result = EpistemicLabel.CONFIRMED, "FAILED"
        elif unread:
            # A result Warden does not know (UNKNOWN, ERROR, NOT_RUN...) is not a pass.
            epistemic, result = EpistemicLabel.UNKNOWN, "INCONCLUSIVE"
        else:
            epistemic, result = EpistemicLabel.REASONED, "PASSED"
        return Handoff.make(
            producer="SWIZZLE", consumer="Warden", kind=HandoffKind.VERDICT,
            repository=repository, repository_sha=repository_sha, baseline_id=baseline_id,
            epistemic_state=epistemic,
            payload={"phase": phase, "count": len(verdicts), "failed_count": len(failed),
                     "verdicts": [{"verdict_id": v.verdict_id, "result": v.result,
                                   "attack_class": v.attack_class, "oracle_basis": v.oracle_basis,
                                   "summary": v.summary} for v in verdicts]},
            result=result, provenance=f"SWIZZLE {phase}",
        )

    def adversarial_passed(self, handoff):
        if handoff.epistemic_state == EpistemicLabel.UNKNOWN:
            return False
        return handoff.result == "PASSED"
