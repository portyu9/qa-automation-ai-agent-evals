"""Evaluator-owned monotonic timing provenance for one completed public trial run."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.evidence.models import TrialEvidence

_SCHEMA: Literal["agent-evals/evaluator-timing/v1"] = "agent-evals/evaluator-timing/v1"
_DOMAIN = b"agent-evals/evaluator-timing/v1\0"
_CLOCK: Literal["time.perf_counter"] = "time.perf_counter"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class EvaluatorTimingProvenance(BaseModel):
    """Bind evaluator-observed elapsed time to its monotonic clock and exact evidence root.

    This is local evaluator timing. It is not provider latency, process CPU time, target-side timing,
    provider cancellation proof, or a latency SLA attestation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evaluator-timing/v1"] = _SCHEMA
    trial_id: str = Field(min_length=1, max_length=512)
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    clock_source: Literal["time.perf_counter"] = _CLOCK
    monotonic: Literal[True] = True
    includes_metric_provenance_resolution: Literal[True] = True
    elapsed_ms: float = Field(ge=0.0, allow_inf_nan=False, strict=True)
    timing_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, evidence: TrialEvidence, *, elapsed_ms: float) -> Self:
        if type(evidence) is not TrialEvidence:
            raise ValueError("timing provenance requires exact TrialEvidence")
        if (
            isinstance(elapsed_ms, bool)
            or not isinstance(elapsed_ms, float)
            or elapsed_ms < 0.0
        ):
            raise ValueError("timing provenance elapsed_ms must be a non-negative float")
        unsigned = {
            "schema_version": _SCHEMA,
            "trial_id": evidence.trial_id,
            "evidence_root": evidence.evidence_root,
            "clock_source": _CLOCK,
            "monotonic": True,
            "includes_metric_provenance_resolution": True,
            "elapsed_ms": elapsed_ms,
        }
        root = hashlib.sha256(_DOMAIN + _canonical_bytes(unsigned)).hexdigest()
        return cls(**unsigned, timing_root=root)

    @model_validator(mode="after")
    def verify_timing_root(self) -> Self:
        unsigned = self.model_dump(mode="json", exclude={"timing_root"})
        expected = hashlib.sha256(_DOMAIN + _canonical_bytes(unsigned)).hexdigest()
        if not hmac.compare_digest(self.timing_root, expected):
            raise ValueError("evaluator timing provenance root mismatch")
        return self

    def validate_against_evidence(self, evidence: TrialEvidence) -> None:
        if type(evidence) is not TrialEvidence:
            raise ValueError("timing provenance requires exact TrialEvidence")
        if self.trial_id != evidence.trial_id:
            raise ValueError("timing provenance trial_id does not match evidence")
        if not hmac.compare_digest(self.evidence_root, evidence.evidence_root):
            raise ValueError("timing provenance evidence root does not match")
