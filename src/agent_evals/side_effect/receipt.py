"""Integrity-bound receipt for one controlled two-attempt side-effect observation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.side_effect.models import SideEffectIdempotencySpec

_SCHEMA = "agent-evals/side-effect-idempotency-receipt/v1"
_EVENT_SOURCE = "bridge:side-effect-idempotency"
_ROOT_DOMAIN = b"agent-evals/side-effect-idempotency-receipt/v1\0"


class SideEffectReceiptError(ValueError):
    """Observed side-effect material cannot close the configured receipt relation."""


class SideEffectAttemptDigest(BaseModel):
    """Digest-only observation around one physical subject-tool callback invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=1, le=2, strict=True)
    call_id: str = Field(min_length=1, max_length=512)
    arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    before_effect_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_effect_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mutated: bool

    @model_validator(mode="after")
    def validate_mutation_flag(self) -> Self:
        if self.mutated != (self.before_effect_sha256 != self.after_effect_sha256):
            raise ValueError("side-effect mutation flag disagrees with observed effect digests")
        return self


class SideEffectIdempotencyReceipt(BaseModel):
    """Bind two attempts for one logical operation without duplicating raw effect state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/side-effect-idempotency-receipt/v1"] = _SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool: str = Field(min_length=1, max_length=256)
    logical_operation_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempts: tuple[SideEffectAttemptDigest, ...] = Field(min_length=2, max_length=2)
    mutation_count: int = Field(ge=0, le=2, strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_shape_and_root(self) -> Self:
        if [attempt.ordinal for attempt in self.attempts] != [1, 2]:
            raise ValueError("side-effect attempt ordinals must be exactly one then two")
        call_ids = [attempt.call_id for attempt in self.attempts]
        if len(set(call_ids)) != 2:
            raise ValueError("side-effect duplicate attempts require distinct call identities")
        if any(attempt.arguments_sha256 != self.arguments_sha256 for attempt in self.attempts):
            raise ValueError("side-effect attempts must share the bound canonical arguments")
        if any(attempt.key_sha256 != self.key_sha256 for attempt in self.attempts):
            raise ValueError("side-effect attempts must share the bound logical-operation key")
        if self.attempts[0].after_effect_sha256 != self.attempts[1].before_effect_sha256:
            raise ValueError("side-effect observation chronology is discontinuous between attempts")
        expected_mutations = sum(attempt.mutated for attempt in self.attempts)
        if self.mutation_count != expected_mutations:
            raise ValueError("side-effect mutation count disagrees with attempt observations")
        expected_root = _receipt_root(self.model_dump(mode="python", exclude={"receipt_root"}))
        if self.receipt_root != expected_root:
            raise ValueError("side-effect idempotency receipt root mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        scenario_identity: str,
        contract: SideEffectIdempotencySpec,
        attempts: tuple[SideEffectAttemptDigest, SideEffectAttemptDigest],
    ) -> SideEffectIdempotencyReceipt:
        if any(attempt.arguments_sha256 != contract.expected_arguments_sha256 for attempt in attempts):
            raise SideEffectReceiptError(
                "observed side-effect attempts do not match scenario-bound canonical arguments"
            )
        if any(attempt.key_sha256 != contract.key_sha256 for attempt in attempts):
            raise SideEffectReceiptError(
                "observed side-effect attempts do not match scenario-bound logical-operation key"
            )
        unsigned: dict[str, Any] = {
            "schema_version": _SCHEMA,
            "scenario_identity": scenario_identity,
            "contract_identity": contract.identity,
            "tool": contract.tool,
            "logical_operation_identity": contract.logical_operation_identity,
            "arguments_sha256": contract.expected_arguments_sha256,
            "key_sha256": contract.key_sha256,
            "attempts": attempts,
            "mutation_count": sum(attempt.mutated for attempt in attempts),
        }
        return cls.model_validate({**unsigned, "receipt_root": _receipt_root(unsigned)})

    def to_event(self, *, sequence: int) -> EvidenceEvent:
        return EvidenceEvent(
            sequence=sequence,
            kind=EvidenceKind.SIDE_EFFECT_OBSERVATION,
            source=_EVENT_SOURCE,
            payload=self.model_dump(mode="json"),
        )


def expected_event_source() -> str:
    return _EVENT_SOURCE


def _receipt_root(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(_ROOT_DOMAIN + canonical).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"unsupported side-effect receipt value type: {type(value).__name__}")
