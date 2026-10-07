"""Environment-chaos assurance for bounded injection and outcome classification.

Chaos qualification proves that the evaluator injected and bounded the declared disturbance domains.
It does not convert subject recovery into release authority, and BLOCKED remains distinct from FAIL.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_serializer, model_validator

from agent_evals._receipt_validation import (
    is_receipt_construction,
    validate_receipt_construction,
)

_POLICY_SCHEMA: Literal["agent-evals/chaos-policy/v1"] = "agent-evals/chaos-policy/v1"
_OBSERVATION_SCHEMA: Literal["agent-evals/chaos-observation/v1"] = (
    "agent-evals/chaos-observation/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/chaos-receipt/v1"] = "agent-evals/chaos-receipt/v1"
_RECEIPT_DOMAIN = b"agent-evals/chaos-receipt/v1\0"


class ChaosDomain(StrEnum):
    CLOCK = "clock"
    DNS = "dns"
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    CREDENTIAL_EXPIRY = "credential-expiry"
    LATENCY = "latency"
    RESOURCE_PRESSURE = "resource-pressure"


class ChaosOutcome(StrEnum):
    RECOVERED = "recovered"
    SUBJECT_FAILURE = "subject-failure"
    BLOCKED = "blocked"


class ChaosPolicy(BaseModel):
    """Evaluator ceilings and required disturbance coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/chaos-policy/v1"] = _POLICY_SCHEMA
    required_domains: frozenset[ChaosDomain] = frozenset(ChaosDomain)
    max_recovery_ticks: int = Field(default=10_000, ge=1, le=10_000_000, strict=True)
    max_resource_bytes: int = Field(
        default=512 * 1024 * 1024,
        ge=1,
        le=64 * 1024 * 1024 * 1024,
        strict=True,
    )
    require_secret_suppression: bool = Field(default=True, strict=True)

    @field_serializer("required_domains", when_used="json")
    def serialize_required_domains(self, value: frozenset[ChaosDomain]) -> list[str]:
        return sorted(item.value for item in value)


class ChaosObservation(BaseModel):
    """One bounded chaos injection and its separately classified subject/evaluator outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/chaos-observation/v1"] = _OBSERVATION_SCHEMA
    domain: ChaosDomain
    injection_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    injected: bool = Field(strict=True)
    outcome: ChaosOutcome
    recovery_ticks: int | None = Field(default=None, ge=0, le=10_000_001, strict=True)
    resource_peak_bytes: int = Field(ge=0, le=64 * 1024 * 1024 * 1024 + 1, strict=True)
    secret_exposed: bool = Field(default=False, strict=True)
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if not self.injected:
            raise ValueError("chaos observation must prove disturbance injection")
        if self.outcome is ChaosOutcome.RECOVERED:
            if self.recovery_ticks is None:
                raise ValueError("recovered chaos observation requires recovery ticks")
            if self.error_code is not None:
                raise ValueError("recovered chaos observation cannot carry evaluator error code")
        elif self.outcome is ChaosOutcome.BLOCKED:
            if self.error_code is None:
                raise ValueError("BLOCKED chaos observation requires evaluator error code")
        return self


class ChaosAssuranceReceipt(BaseModel):
    """Coverage/resource qualification with subject outcome counts preserved separately."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/chaos-receipt/v1"] = _RECEIPT_SCHEMA
    policy: ChaosPolicy
    observations: tuple[ChaosObservation, ...] = Field(min_length=1, max_length=100_000)
    covered_domains: tuple[ChaosDomain, ...]
    recovered: int = Field(ge=0, strict=True)
    subject_failures: int = Field(ge=0, strict=True)
    blocked: int = Field(ge=0, strict=True)
    qualification_complete: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: ChaosPolicy,
        observations: tuple[ChaosObservation, ...],
    ) -> Self:
        _require_exact(policy, ChaosPolicy, "chaos policy")
        checked_policy = ChaosPolicy.model_validate_json(policy.model_dump_json())
        checked: list[ChaosObservation] = []
        for item in observations:
            _require_exact(item, ChaosObservation, "chaos observation")
            checked.append(ChaosObservation.model_validate_json(item.model_dump_json()))
        ids = [item.injection_id for item in checked]
        if len(set(ids)) != len(ids):
            raise ValueError("chaos injection IDs must be unique")

        covered = tuple(sorted({item.domain for item in checked}, key=lambda item: item.value))
        recovered = sum(item.outcome is ChaosOutcome.RECOVERED for item in checked)
        subject_failures = sum(item.outcome is ChaosOutcome.SUBJECT_FAILURE for item in checked)
        blocked = sum(item.outcome is ChaosOutcome.BLOCKED for item in checked)
        bounded = all(
            item.resource_peak_bytes <= checked_policy.max_resource_bytes
            and (
                item.recovery_ticks is None
                or item.recovery_ticks <= checked_policy.max_recovery_ticks
            )
            and (not checked_policy.require_secret_suppression or not item.secret_exposed)
            for item in checked
        )
        complete = checked_policy.required_domains <= set(covered) and bounded and blocked == 0
        material = {
            "schema_version": _RECEIPT_SCHEMA,
            "policy": checked_policy.model_dump(mode="json"),
            "observations": [item.model_dump(mode="json") for item in checked],
            "covered_domains": [item.value for item in covered],
            "recovered": recovered,
            "subject_failures": subject_failures,
            "blocked": blocked,
            "qualification_complete": complete,
        }
        return validate_receipt_construction(
            cls,
            policy=checked_policy,
            observations=tuple(checked),
            covered_domains=covered,
            recovered=recovered,
            subject_failures=subject_failures,
            blocked=blocked,
            qualification_complete=complete,
            receipt_root=_domain_root(_RECEIPT_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self, info: ValidationInfo) -> Self:
        if is_receipt_construction(info):
            return self
        rebuilt = type(self).create(policy=self.policy, observations=self.observations)
        fields = (
            "covered_domains",
            "recovered",
            "subject_failures",
            "blocked",
            "qualification_complete",
        )
        if any(getattr(self, field) != getattr(rebuilt, field) for field in fields):
            raise ValueError("chaos assurance receipt metrics do not recompute")
        if not hmac.compare_digest(self.receipt_root, rebuilt.receipt_root):
            raise ValueError("chaos assurance receipt root mismatch")
        return self


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
        raise ValueError("chaos assurance material must be finite JSON-compatible data") from exc


__all__ = [
    "ChaosAssuranceReceipt",
    "ChaosDomain",
    "ChaosObservation",
    "ChaosOutcome",
    "ChaosPolicy",
]
