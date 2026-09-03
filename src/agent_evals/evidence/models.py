"""Provenance-bound evidence emitted by adapters, environments, and oracles."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    PASS = "pass"
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
            json.dumps(self.payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("evidence payload must be finite JSON-compatible data") from exc
        return self

    @property
    def digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
            raise ValueError(f"event sequence must be contiguous from zero: expected {expected!r}, got {actual!r}")
        try:
            json.dumps(self.final_state, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("final_state must be finite JSON-compatible data") from exc
        return self

    @property
    def critical_events(self) -> tuple[EvidenceEvent, ...]:
        return tuple(event for event in self.events if event.critical)

    @property
    def evidence_root(self) -> str:
        """Hash-chain root binding event order and terminal state into one trial identity."""
        chain = bytes(32)
        for event in self.events:
            chain = hashlib.sha256(chain + bytes.fromhex(event.digest)).digest()
        terminal = json.dumps(
            {
                "final_state": self.final_state,
                "final_output": self.final_output,
                "elapsed_ms": self.elapsed_ms,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "estimated_cost_usd": self.estimated_cost_usd,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(chain + terminal).hexdigest()
