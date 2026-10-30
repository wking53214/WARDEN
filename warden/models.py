"""Transformation and defect representations.

A transformation is a *proposal* until an Authorization grants it. Applying
without that grant is a bug in the caller, and this module refuses.

Defect identity: Ghost Tools already owns machine identity (`ghost-<hash>`).
Warden preserves those IDs. Human-readable C1/H1/M1/L1 labels are assigned
only when no Ghost identity exists, and they are labels, not a second authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Any, Mapping, Optional, Sequence

from . import textio
from .authorization import Authorization, Unauthorized, canonical, is_stack_actor
from .epistemic import EpistemicState
from cns.defect import Defect, DefectLifecycle, DefectSeverity  # the shared rows: cns 2.0.0
from cns.seat import FileEdit

_UNSAFE_ID = re.compile(r"[^A-Za-z0-9_.:-]")


def safe_id(value: object) -> str:
    """A Ghost id made safe to write into a file or a note.

    Only letters, digits and _ . : - survive; everything else, newlines
    included, becomes "?". One line, at most 64 characters. An id is data from
    outside Warden, and a newline in one could otherwise put live code in a file.
    """
    return _UNSAFE_ID.sub("?", str(value))[:64]






class InvalidDefectTransition(ValueError):
    """A defect was moved to a state its lifecycle does not allow."""


# Only the moves the code makes today. A state with no entry has no allowed
# next step, so any move out of it is refused.
VALID_DEFECT_TRANSITIONS: dict[DefectLifecycle, frozenset[DefectLifecycle]] = {
    DefectLifecycle.PROPOSED: frozenset(
        {DefectLifecycle.AUTHORIZED, DefectLifecycle.MODIFIED}
    ),
    DefectLifecycle.AUTHORIZED: frozenset({DefectLifecycle.MODIFIED}),
}


def _move_defect(defect: Any, target: DefectLifecycle) -> None:
    allowed = VALID_DEFECT_TRANSITIONS.get(defect.lifecycle, frozenset())
    if target not in allowed:
        raise InvalidDefectTransition(
            f"defect cannot move from {defect.lifecycle.value} "
            f"to {target.value}"
        )
    defect.lifecycle = target


class TransformationStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    AUTHORIZED = "authorized"
    APPLIED = "applied"
    REJECTED = "rejected"
    DEFERRED = "deferred"


_SEVERITY_PREFIX = {
    DefectSeverity.CRITICAL: "C",
    DefectSeverity.HIGH: "H",
    DefectSeverity.MEDIUM: "M",
    DefectSeverity.LOW: "L",
}


def human_label(severity: DefectSeverity, index: int) -> str:
    if index < 1:
        raise ValueError("defect index is 1-based")
    return f"{_SEVERITY_PREFIX[severity]}{index}"


def ghost_severity_to_warden(value: str) -> DefectSeverity:
    """Map Ghost Tools severity onto Warden's four-level scale.

    Ghost uses critical/major/minor/informational. Warden uses
    critical/high/medium/low. This is a documented translation, not a claim
    that the two scales are identical.
    """
    v = value.lower()
    if v == "critical":
        return DefectSeverity.CRITICAL
    if v == "major":
        return DefectSeverity.HIGH
    if v == "minor":
        return DefectSeverity.MEDIUM
    if v in {"informational", "info"}:
        return DefectSeverity.LOW
    return DefectSeverity.MEDIUM




def _require_external_actor(auth: Authorization) -> None:
    """Reject reserved or canonically empty actors at the model boundary."""
    if is_stack_actor(auth.actor) or not canonical(auth.actor):
        raise Unauthorized(
            f"{auth.actor!r} cannot authorize a transformation; "
            "a human or external governor must."
        )


@dataclass
class Transformation:
    """One intentional change, with a reason, a baseline, and a preservation expectation.

    Warden must not silently alter code. `apply` requires a granted
    Authorization whose operation and subject match this transformation.
    """

    target: str
    intent: str
    architectural_reason: str
    affected_files: tuple[str, ...]
    expected_behavior: str
    preservation_requirements: tuple[str, ...]
    known_defects: tuple[Defect, ...]
    transformation_scope: str
    baseline_reference: str
    evidence: tuple[str, ...]
    edits: tuple["FileEdit", ...] = ()
    status: TransformationStatus = TransformationStatus.PROPOSED
    authorization: Optional[Authorization] = None
    result: Optional[str] = None
    #: Set by the claim seat (`warden.claim`): the real change this proposal is, as facts (commit, parent,
    #: tree, diff sha256 and size, each file's sha256 before and after). None for every other proposer.
    claim: Optional[Mapping[str, Any]] = None

    def authorize(self, auth: Authorization) -> "Transformation":
        _require_external_actor(auth)
        if not auth.permits("transform", self.target):
            raise Unauthorized(
                f"authorization does not permit transform on {self.target!r} "
                f"(actor={auth.actor!r} granted={auth.granted})"
            )
        self.authorization = auth
        self.status = TransformationStatus.AUTHORIZED
        for d in self.known_defects:
            if d.lifecycle == DefectLifecycle.PROPOSED:
                _move_defect(d, DefectLifecycle.AUTHORIZED)
        return self

    def apply(self, root: Path) -> Mapping[str, Any]:
        root_p = Path(root)
        if self.authorization is None or not self.authorization.granted:
            raise Unauthorized(
                "refusing to apply: no granted authorization. "
                "Warden proposes; a human authorizes."
            )
        _require_external_actor(self.authorization)
        if self.status not in {TransformationStatus.AUTHORIZED, TransformationStatus.APPLIED}:
            raise Unauthorized(f"refusing to apply in status {self.status.value}")
        written = []
        for edit in self.edits:
            if Path(edit.path).is_absolute() or not (root_p / edit.path).resolve().is_relative_to(root_p.resolve()):
                raise Unauthorized(f"refusing edit outside the target: {edit.path!r}")
            path = root_p / edit.path
            if edit.kind == "replace":
                if not path.is_file():
                    raise FileNotFoundError(edit.path)
                original = textio.read_text(path, edit.path)
                old, new_text = (edit.old, edit.new) if "\r" in original else (_lf(edit.old), _lf(edit.new))
                if old not in original:
                    raise ValueError(
                        f"{edit.path}: preservation check failed; expected text not found. "
                        "The baseline has drifted; this transformation must be re-proposed."
                    )
                if original.count(old) != 1 and not edit.replace_all:
                    raise ValueError(
                        f"{edit.path}: expected text occurs {original.count(old)} times; "
                        "refusing an ambiguous replace (one intentional change)."
                    )
                new = original.replace(old, new_text) if edit.replace_all else original.replace(old, new_text, 1)
                textio.write_text(path, new)
            elif edit.kind == "write":
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.is_file() and not textio.is_decodable(path):
                    raise textio.Undecodable(f"{edit.path} is not valid UTF-8, so it will not be edited")
                if self.claim is not None:
                    # The claim seat: the actor's bytes are the thing governed, so they land exactly, with no
                    # adaptation to the line endings of the file they replace (a Drafter's or Finisher's write
                    # keeps them).
                    path.write_bytes(edit.new.encode("utf-8"))
                else:
                    textio.write_text(path, edit.new)
            elif edit.kind == "delete":
                if not path.is_file():
                    raise FileNotFoundError(edit.path)
                path.unlink()
            else:
                raise ValueError(f"unknown edit kind {edit.kind!r}")
            written.append(edit.path)
        self.status = TransformationStatus.APPLIED
        self.result = f"wrote {len(written)} file(s)"
        for d in self.known_defects:
            if d.lifecycle in {DefectLifecycle.AUTHORIZED, DefectLifecycle.PROPOSED}:
                _move_defect(d, DefectLifecycle.MODIFIED)
        return {"written": written, "status": self.status.value}

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "intent": self.intent,
            "architectural_reason": self.architectural_reason,
            "affected_files": list(self.affected_files),
            "expected_behavior": self.expected_behavior,
            "preservation_requirements": list(self.preservation_requirements),
            "known_defects": [
                {
                    "identity": d.identity,
                    "ghost_id": d.ghost_id,
                    "human_id": d.human_id,
                    "summary": d.summary,
                    "severity": d.severity.value,
                    "lifecycle": d.lifecycle.value,
                    "ghost_status": d.ghost_status,
                    "epistemic": d.epistemic.value,
                    "file": d.file,
                    "evidence": list(d.evidence),
                }
                for d in self.known_defects
            ],
            "transformation_scope": self.transformation_scope,
            "baseline_reference": self.baseline_reference,
            "evidence": list(self.evidence),
            "status": self.status.value,
            "authorization": None if self.authorization is None else {
                "actor": self.authorization.actor,
                "operation": self.authorization.operation,
                "subject": self.authorization.subject,
                "scope": self.authorization.scope,
                "reason": self.authorization.reason,
                "granted": self.authorization.granted,
                "at": self.authorization.at,
                "policy_version": self.authorization.policy_version,
            },
            "result": self.result,
        }


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")




def defects_from_ghost(findings: Sequence[Mapping[str, Any]]) -> tuple[Defect, ...]:
    """Consume Ghost Tools findings. Preserve their identity. Do not re-hash."""
    out: list[Defect] = []
    counters = {s: 0 for s in DefectSeverity}
    for raw in findings:
        sev = ghost_severity_to_warden(str(raw.get("severity", "minor")))
        counters[sev] += 1
        status = raw.get("status")
        epistemic = EpistemicState.VERIFIED if status == "confirmed" else EpistemicState.UNKNOWN
        if status == "reasoned":
            epistemic = EpistemicState.ASSUMED
        ev = raw.get("evidence") or {}
        out.append(
            Defect(
                summary=str(raw.get("summary", "")),
                severity=sev,
                lifecycle=DefectLifecycle.IDENTIFIED,
                ghost_id=raw.get("id"),
                human_id=human_label(sev, counters[sev]),
                evidence=tuple(filter(None, [raw.get("detail", ""), ev.get("snippet") or ""])),
                file=ev.get("file"),
                epistemic=epistemic,
                ghost_status=status,
                detector=raw.get("detector"),
                line=ev.get("line_start"),
                attributes=dict(raw.get("attributes") or {}),
            )
        )
    return tuple(out)
