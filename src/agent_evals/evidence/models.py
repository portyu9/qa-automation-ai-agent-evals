"""Provenance-bound evidence emitted by adapters, environments, and oracles."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

_EVIDENCE_ROOT_DOMAIN = b"agent-evals/trial-evidence/v2\0"


class EvidenceKind(StrEnum):
    TOOL_REQUEST = "tool_request"
    TOOL_RESULT = "tool_result"
    HANDOFF = "handoff"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL = "approval"
    GUARDRAIL = "guardrail"
    STATE = "state"
    OUTPUT = "output"
    POLICY_VIOLATION = "policy_violation"
    RUNTIME_ERROR = "runtime_error"


class TrialVerdict(StrEnum):
    PASS = "pass"  # nosec B105 - public verdict label, never a credential or secret
    FAIL = "fail"
    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"


class EvidenceEvent(BaseModel):
    """One immutable observable event in an evaluation trial."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int = Field(ge=0)
    kind: EvidenceKind
    source: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    critical: bool = False

    @model_validator(mode="after")
    def validate_json_payload(self) -> EvidenceEvent:
        try:
            _canonical_json_bytes(self.payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("evidence payload must be finite JSON-compatible data") from exc
        return self

    @property
    def digest(self) -> str:
        canonical = _canonical_json_bytes(self.model_dump(mode="json"))
        return hashlib.sha256(canonical).hexdigest()


class TrialEvidence(BaseModel):
    """Complete evidence envelope for one scenario attempt.

    The envelope is append-order sensitive. Duplicate or non-contiguous sequence numbers are
    rejected so a later report cannot silently reorder the causal record.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trial_id: str = Field(min_length=1)
    subject_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    events: tuple[EvidenceEvent, ...] = ()
    final_state: dict[str, Any] = Field(default_factory=dict)
    final_output: str | None = None
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_event_sequence(self) -> TrialEvidence:
        expected = list(range(len(self.events)))
        actual = [event.sequence for event in self.events]
        if actual != expected:
            raise ValueError(
                f"event sequence must be contiguous from zero: expected {expected!r}, got {actual!r}"
            )
        try:
            _canonical_json_bytes(self.final_state)
        except (TypeError, ValueError) as exc:
            raise ValueError("final_state must be finite JSON-compatible data") from exc
        return self

    @property
    def critical_events(self) -> tuple[EvidenceEvent, ...]:
        return tuple(event for event in self.events if event.critical)

    @property
    def evidence_root(self) -> str:
        """Bind subject, scenario, trial, event order, and terminal observations into one root."""
        envelope_identity = _canonical_json_bytes(
            {
                "trial_id": self.trial_id,
                "subject_identity": self.subject_identity,
                "scenario_identity": self.scenario_identity,
            }
        )
        chain = hashlib.sha256(_EVIDENCE_ROOT_DOMAIN + envelope_identity).digest()
        for event in self.events:
            chain = hashlib.sha256(chain + bytes.fromhex(event.digest)).digest()
        terminal = _canonical_json_bytes(
            {
                "final_state": self.final_state,
                "final_output": self.final_output,
                "elapsed_ms": self.elapsed_ms,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "estimated_cost_usd": self.estimated_cost_usd,
            }
        )
        return hashlib.sha256(_EVIDENCE_ROOT_DOMAIN + chain + terminal).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
