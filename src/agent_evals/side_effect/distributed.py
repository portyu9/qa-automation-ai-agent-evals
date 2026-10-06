"""Distributed side-effect assurance for retries, races, redelivery, crashes and acknowledgements."""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from agent_evals._receipt_validation import (
    is_receipt_construction,
    validate_receipt_construction,
)

_POLICY_SCHEMA: Literal["agent-evals/distributed-side-effect-policy/v1"] = (
    "agent-evals/distributed-side-effect-policy/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/distributed-side-effect-receipt/v1"] = (
    "agent-evals/distributed-side-effect-receipt/v1"
)
_ACK_SCHEMA: Literal["agent-evals/target-effect-acknowledgement/v1"] = (
    "agent-evals/target-effect-acknowledgement/v1"
)
_RECEIPT_DOMAIN = b"agent-evals/distributed-side-effect-receipt/v1\0"
_ACK_DOMAIN = b"agent-evals/target-effect-acknowledgement/v1\0"


class SideEffectAttemptCause(StrEnum):
    INITIAL = "initial"
    CONCURRENT_DUPLICATE = "concurrent-duplicate"
    TIMEOUT_RETRY = "timeout-retry"
    CANCELLATION_RETRY = "cancellation-retry"
    CRASH_RECOVERY = "crash-recovery"
    QUEUE_REDELIVERY = "queue-redelivery"
    MULTI_WORKER_RACE = "multi-worker-race"


class SideEffectAttemptOutcome(StrEnum):
    COMMITTED = "committed"
    DUPLICATE_REJECTED = "duplicate-rejected"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"
    CRASHED = "crashed"
    ROLLED_BACK = "rolled-back"


class DistributedSideEffectPolicy(BaseModel):
    """Non-compensatory physical-mutation policy for one logical operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/distributed-side-effect-policy/v1"] = _POLICY_SCHEMA
    max_committed_mutations: int = Field(default=1, ge=0, le=10, strict=True)
    require_unique_transaction: bool = Field(default=True, strict=True)
    require_unique_delivery_ids: bool = Field(default=True, strict=True)
    require_duplicate_rejection: bool = Field(default=True, strict=True)


class DistributedSideEffectAttempt(BaseModel):
    """One observed worker/delivery attempt for a logical side effect."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    worker_id: str = Field(min_length=1, max_length=256)
    delivery_id: str = Field(min_length=1, max_length=256)
    cause: SideEffectAttemptCause
    outcome: SideEffectAttemptOutcome
    transaction_id: str | None = Field(default=None, min_length=1, max_length=256)
    mutation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    started_tick: int = Field(ge=0, strict=True)
    completed_tick: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def validate_attempt(self) -> Self:
        if self.completed_tick < self.started_tick:
            raise ValueError("side-effect attempt cannot complete before it starts")
        if self.outcome is SideEffectAttemptOutcome.COMMITTED:
            if self.transaction_id is None or self.mutation_sha256 is None:
                raise ValueError("committed side effect requires transaction and mutation identity")
        elif self.mutation_sha256 is not None:
            raise ValueError("non-committed side-effect attempt cannot claim physical mutation")
        return self


class DistributedSideEffectReceipt(BaseModel):
    """Recompute exactly-once physical mutation under distributed retry/race causes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/distributed-side-effect-receipt/v1"] = _RECEIPT_SCHEMA
    policy: DistributedSideEffectPolicy
    attempts: tuple[DistributedSideEffectAttempt, ...] = Field(min_length=1, max_length=10_000)
    committed_mutations: int = Field(ge=0, le=10_000, strict=True)
    covered_causes: tuple[SideEffectAttemptCause, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: DistributedSideEffectPolicy,
        attempts: tuple[DistributedSideEffectAttempt, ...],
    ) -> Self:
        _require_exact(policy, DistributedSideEffectPolicy, "distributed side-effect policy")
        checked_policy = DistributedSideEffectPolicy.model_validate_json(policy.model_dump_json())
        checked: list[DistributedSideEffectAttempt] = []
        for item in attempts:
            _require_exact(item, DistributedSideEffectAttempt, "distributed side-effect attempt")
            checked.append(DistributedSideEffectAttempt.model_validate_json(item.model_dump_json()))
        if not checked:
            raise ValueError("distributed side-effect receipt requires attempts")
        operation_ids = {item.operation_identity for item in checked}
        keys = {item.idempotency_key_sha256 for item in checked}
        if len(operation_ids) != 1 or len(keys) != 1:
            raise ValueError(
                "distributed side-effect attempts must bind one operation and idempotency key"
            )
        attempt_ids = [item.attempt_id for item in checked]
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("distributed side-effect attempt IDs must be unique")
        if checked_policy.require_unique_delivery_ids:
            delivery_ids = [item.delivery_id for item in checked]
            if len(set(delivery_ids)) != len(delivery_ids):
                raise ValueError("distributed side-effect delivery IDs must be unique")

        committed = [item for item in checked if item.outcome is SideEffectAttemptOutcome.COMMITTED]
        if checked_policy.require_unique_transaction:
            transactions = [item.transaction_id for item in committed]
            if len(set(transactions)) != len(transactions):
                raise ValueError("committed side effects must have unique transaction identities")

        covered = tuple(sorted({item.cause for item in checked}, key=lambda item: item.value))
        duplicate_causes = {
            SideEffectAttemptCause.CONCURRENT_DUPLICATE,
            SideEffectAttemptCause.TIMEOUT_RETRY,
            SideEffectAttemptCause.CANCELLATION_RETRY,
            SideEffectAttemptCause.CRASH_RECOVERY,
            SideEffectAttemptCause.QUEUE_REDELIVERY,
            SideEffectAttemptCause.MULTI_WORKER_RACE,
        }
        duplicate_attempts = [item for item in checked if item.cause in duplicate_causes]
        duplicates_safe = not checked_policy.require_duplicate_rejection or all(
            item.outcome
            in {
                SideEffectAttemptOutcome.DUPLICATE_REJECTED,
                SideEffectAttemptOutcome.TIMED_OUT,
                SideEffectAttemptOutcome.CANCELLED,
                SideEffectAttemptOutcome.CRASHED,
                SideEffectAttemptOutcome.ROLLED_BACK,
            }
            for item in duplicate_attempts
            if item.outcome is not SideEffectAttemptOutcome.COMMITTED
        )
        accepted = len(committed) <= checked_policy.max_committed_mutations and duplicates_safe
        material = {
            "schema_version": _RECEIPT_SCHEMA,
            "policy": checked_policy.model_dump(mode="json"),
            "attempts": [item.model_dump(mode="json") for item in checked],
            "committed_mutations": len(committed),
            "covered_causes": [item.value for item in covered],
            "accepted": accepted,
        }
        return validate_receipt_construction(
            cls,
            policy=checked_policy,
            attempts=tuple(checked),
            committed_mutations=len(committed),
            covered_causes=covered,
            accepted=accepted,
            receipt_root=_domain_root(_RECEIPT_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self, info: ValidationInfo) -> Self:
        if is_receipt_construction(info):
            return self
        rebuilt = type(self).create(policy=self.policy, attempts=self.attempts)
        if (
            self.committed_mutations != rebuilt.committed_mutations
            or self.covered_causes != rebuilt.covered_causes
            or self.accepted != rebuilt.accepted
            or not hmac.compare_digest(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("distributed side-effect receipt does not recompute")
        return self


class TargetEffectAcknowledgement(BaseModel):
    """Externally verified target-system acknowledgement for one physical effect.

    The cryptographically_verified field is an input from an external signature/MAC verifier.
    This model never treats its own SHA-256 root as authentication.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/target-effect-acknowledgement/v1"] = _ACK_SCHEMA
    target_system_identity: str = Field(min_length=1, max_length=512)
    operation_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    effect_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledgement_id: str = Field(min_length=1, max_length=256)
    verification_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    algorithm: str = Field(min_length=1, max_length=128)
    cryptographically_verified: bool = Field(strict=True)
    observed_at_unix_ms: int = Field(ge=0, le=9_999_999_999_999, strict=True)
    acknowledgement_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        target_system_identity: str,
        operation_identity: str,
        effect_sha256: str,
        acknowledgement_id: str,
        verification_key_sha256: str,
        algorithm: str,
        cryptographically_verified: bool,
        observed_at_unix_ms: int,
    ) -> Self:
        material = {
            "schema_version": _ACK_SCHEMA,
            "target_system_identity": target_system_identity,
            "operation_identity": operation_identity,
            "effect_sha256": effect_sha256,
            "acknowledgement_id": acknowledgement_id,
            "verification_key_sha256": verification_key_sha256,
            "algorithm": algorithm,
            "cryptographically_verified": cryptographically_verified,
            "observed_at_unix_ms": observed_at_unix_ms,
        }
        return cls(**material, acknowledgement_root=_domain_root(_ACK_DOMAIN, material))

    @model_validator(mode="after")
    def verify_root(self) -> Self:
        expected = _domain_root(
            _ACK_DOMAIN,
            self.model_dump(mode="json", exclude={"acknowledgement_root"}),
        )
        if not hmac.compare_digest(self.acknowledgement_root, expected):
            raise ValueError("target effect acknowledgement root mismatch")
        return self


def verify_target_acknowledgement(
    *,
    receipt: DistributedSideEffectReceipt,
    acknowledgement: TargetEffectAcknowledgement,
) -> None:
    """Require one externally verified acknowledgement to match the unique committed effect."""

    _require_exact(receipt, DistributedSideEffectReceipt, "distributed side-effect receipt")
    _require_exact(acknowledgement, TargetEffectAcknowledgement, "target acknowledgement")
    checked_receipt = DistributedSideEffectReceipt.model_validate_json(receipt.model_dump_json())
    checked_ack = TargetEffectAcknowledgement.model_validate_json(acknowledgement.model_dump_json())
    if not checked_ack.cryptographically_verified:
        raise ValueError("target acknowledgement lacks external cryptographic verification")
    committed = [
        item
        for item in checked_receipt.attempts
        if item.outcome is SideEffectAttemptOutcome.COMMITTED
    ]
    if len(committed) != 1:
        raise ValueError("target acknowledgement requires exactly one committed side effect")
    commit = committed[0]
    if (
        checked_ack.operation_identity != commit.operation_identity
        or checked_ack.effect_sha256 != commit.mutation_sha256
    ):
        raise ValueError("target acknowledgement does not bind the committed side effect")


def _require_exact(value: object, expected: type[object], label: str) -> None:
    if type(value) is not expected:
        raise ValueError(f"{label} requires exact {expected.__name__}")


def _domain_root(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "side-effect assurance material must be finite JSON-compatible data"
        ) from exc


__all__ = [
    "DistributedSideEffectAttempt",
    "DistributedSideEffectPolicy",
    "DistributedSideEffectReceipt",
    "SideEffectAttemptCause",
    "SideEffectAttemptOutcome",
    "TargetEffectAcknowledgement",
    "verify_target_acknowledgement",
]
