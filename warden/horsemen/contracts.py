"""Handoff envelopes between horsemen."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid

class EpistemicLabel(str, Enum):
    CONFIRMED = "CONFIRMED"
    REASONED = "REASONED"
    UNKNOWN = "UNKNOWN"

class HandoffKind(str, Enum):
    BASELINE = "BASELINE"
    SPECIMEN = "SPECIMEN"
    FINDING = "FINDING"
    OBSERVATION = "OBSERVATION"
    PROPOSAL = "PROPOSAL"
    AUTHORIZATION = "AUTHORIZATION"
    TRANSFORMATION = "TRANSFORMATION"
    VERDICT = "VERDICT"
    RECEIPT = "RECEIPT"

@dataclass
class Handoff:
    handoff_id: str
    producer: str
    consumer: str
    kind: HandoffKind
    repository: str
    repository_sha: str
    baseline_id: str
    epistemic_state: EpistemicLabel
    payload: Dict[str, Any]
    schema_version: str = "1.0.0"
    scope: Optional[str] = None
    provenance: Optional[str] = None
    result: Optional[str] = None
    evidence_refs: tuple = ()
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def make(cls, *, producer, consumer, kind, repository, repository_sha, baseline_id,
             epistemic_state, payload, **kwargs):
        return cls(
            handoff_id=f"hof_{uuid.uuid4().hex[:12]}",
            producer=producer, consumer=consumer, kind=kind,
            repository=repository, repository_sha=repository_sha,
            baseline_id=baseline_id, epistemic_state=epistemic_state,
            payload=payload, **kwargs,
        )

    def to_dict(self):
        return {
            "handoff_id": self.handoff_id, "producer": self.producer, "consumer": self.consumer,
            "kind": self.kind.value, "repository": self.repository,
            "repository_sha": self.repository_sha, "baseline_id": self.baseline_id,
            "epistemic_state": self.epistemic_state.value, "payload": self.payload,
            "schema_version": self.schema_version, "scope": self.scope,
            "provenance": self.provenance, "result": self.result,
            "evidence_refs": list(self.evidence_refs), "timestamp": self.timestamp,
        }

    def assert_not_unknown_as_confirmed(self):
        if self.epistemic_state == EpistemicLabel.UNKNOWN and self.result in {
            "CONFIRMED", "CNS_READY", "APPROVED",
        }:
            raise ValueError(
                f"FORBIDDEN: handoff {self.handoff_id} has epistemic UNKNOWN but result={self.result!r}"
            )
