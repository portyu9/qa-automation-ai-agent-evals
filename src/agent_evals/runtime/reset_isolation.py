"""Evaluator-owned reset/isolation transition receipts for repeated campaigns."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SCHEMA: Literal["agent-evals/reset-isolation-receipt/v1"] = (
    "agent-evals/reset-isolation-receipt/v1"
)
_ROOT_DOMAIN = b"agent-evals/reset-isolation-receipt/v1\0"
_CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ResetIsolationError(ValueError):
    """A requested verified reset/isolation control relation could not be established."""


@dataclass(frozen=True, slots=True)
class ResetIsolationContext:
    """Bounded evaluator context supplied to one between-attempt reset control."""

    campaign_id: str
    attempt_index: int
    previous_trial_id: str
    next_trial_id: str
    subject_identity: str
    scenario_identity: str
    runtime_adapter_name: str
    subject_adapter: str
    subject_adapter_version: str
    previous_evidence_root: str


@dataclass(frozen=True, slots=True)
class ResetIsolationObservation:
    """Digest-only observation returned by the separately supplied reset control."""

    control_evidence_identity: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.control_evidence_identity, str)
            or _SHA256_RE.fullmatch(self.control_evidence_identity) is None
        ):
            raise ValueError("control_evidence_identity must be a lowercase SHA-256 hex digest")


class ResetIsolationControl(Protocol):
    """Evaluator/operator control boundary invoked between repeated subject attempts."""

    @property
    def strategy_name(self) -> str: ...

    @property
    def strategy_version(self) -> str: ...

    async def reset(
        self,
        *,
        context: ResetIsolationContext,
    ) -> ResetIsolationObservation: ...


class ResetIsolationReceipt(BaseModel):
    """Integrity-bound evidence for one declared between-attempt control relation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/reset-isolation-receipt/v1"] = _SCHEMA
    campaign_id: str = Field(min_length=1, max_length=128)
    attempt_index: int = Field(ge=1, le=1_000_000, strict=True)
    previous_trial_id: str = Field(min_length=1, max_length=256)
    next_trial_id: str = Field(min_length=1, max_length=256)
    subject_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_adapter_name: str = Field(min_length=1, max_length=256)
    subject_adapter: str = Field(min_length=1, max_length=512)
    subject_adapter_version: str = Field(min_length=1, max_length=512)
    reset_strategy_name: str = Field(min_length=1, max_length=256)
    reset_strategy_version: str = Field(min_length=1, max_length=256)
    previous_evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    control_evidence_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("campaign_id")
    @classmethod
    def validate_campaign_id(cls, value: str) -> str:
        if _CAMPAIGN_ID_RE.fullmatch(value) is None:
            raise ValueError("reset receipt campaign_id is not canonical")
        return value

    @field_validator(
        "runtime_adapter_name",
        "reset_strategy_name",
        "reset_strategy_version",
    )
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(
                "reset receipt control identities must not contain surrounding whitespace"
            )
        return value

    @model_validator(mode="after")
    def validate_transition_and_root(self) -> Self:
        expected_previous = _campaign_trial_id(self.campaign_id, self.attempt_index - 1)
        expected_next = _campaign_trial_id(self.campaign_id, self.attempt_index)
        if self.previous_trial_id != expected_previous:
            raise ValueError("reset receipt previous trial ID does not match campaign transition")
        if self.next_trial_id != expected_next:
            raise ValueError("reset receipt next trial ID does not match campaign transition")
        expected_root = _receipt_root(self.model_dump(mode="python", exclude={"receipt_root"}))
        if self.receipt_root != expected_root:
            raise ValueError("reset/isolation receipt root mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        context: ResetIsolationContext,
        reset_strategy_name: str,
        reset_strategy_version: str,
        control_evidence_identity: str,
    ) -> ResetIsolationReceipt:
        unsigned: dict[str, Any] = {
            "schema_version": _SCHEMA,
            "campaign_id": context.campaign_id,
            "attempt_index": context.attempt_index,
            "previous_trial_id": context.previous_trial_id,
            "next_trial_id": context.next_trial_id,
            "subject_identity": context.subject_identity,
            "scenario_identity": context.scenario_identity,
            "runtime_adapter_name": context.runtime_adapter_name,
            "subject_adapter": context.subject_adapter,
            "subject_adapter_version": context.subject_adapter_version,
            "reset_strategy_name": reset_strategy_name,
            "reset_strategy_version": reset_strategy_version,
            "previous_evidence_root": context.previous_evidence_root,
            "control_evidence_identity": control_evidence_identity,
        }
        return cls.model_validate({**unsigned, "receipt_root": _receipt_root(unsigned)})


def verify_reset_isolation_sequence(
    receipts: tuple[ResetIsolationReceipt, ...],
    *,
    campaign_id: str,
    subject_identity: str,
    scenario_identity: str,
    runtime_adapter_name: str,
    subject_adapter: str,
    subject_adapter_version: str,
    reset_strategy_name: str,
    reset_strategy_version: str,
    trial_ids: tuple[str, ...],
    evidence_roots: tuple[str, ...],
) -> None:
    """Revalidate the complete ordered reset chain against finalized session evidence."""
    if len(trial_ids) != len(evidence_roots):
        raise ResetIsolationError("trial IDs and evidence roots must have equal length")
    if len(trial_ids) < 2:
        raise ResetIsolationError("verified independence requires at least two trials")
    if len(receipts) != len(trial_ids) - 1:
        raise ResetIsolationError("verified campaign requires exactly trials - 1 reset receipts")
    if any(type(receipt) is not ResetIsolationReceipt for receipt in receipts):
        raise ResetIsolationError("reset receipts must be exact ResetIsolationReceipt instances")
    if len({receipt.receipt_root for receipt in receipts}) != len(receipts):
        raise ResetIsolationError("reset receipt roots must be unique across attempt transitions")

    for attempt_index, receipt in enumerate(receipts, start=1):
        context = ResetIsolationContext(
            campaign_id=campaign_id,
            attempt_index=attempt_index,
            previous_trial_id=trial_ids[attempt_index - 1],
            next_trial_id=trial_ids[attempt_index],
            subject_identity=subject_identity,
            scenario_identity=scenario_identity,
            runtime_adapter_name=runtime_adapter_name,
            subject_adapter=subject_adapter,
            subject_adapter_version=subject_adapter_version,
            previous_evidence_root=evidence_roots[attempt_index - 1],
        )
        try:
            expected = ResetIsolationReceipt.create(
                context=context,
                reset_strategy_name=reset_strategy_name,
                reset_strategy_version=reset_strategy_version,
                control_evidence_identity=receipt.control_evidence_identity,
            )
        except ValueError as exc:
            raise ResetIsolationError(
                f"reset receipt {attempt_index} could not be reconstructed"
            ) from exc
        if receipt != expected:
            raise ResetIsolationError(
                f"reset receipt {attempt_index} does not match the finalized campaign transition"
            )


def validate_reset_strategy_identity(name: object, version: object) -> tuple[str, str]:
    """Validate bounded strategy metadata before any subject trial executes."""
    if not isinstance(name, str) or not name or name != name.strip():
        raise ResetIsolationError(
            "reset strategy name must be a non-empty, whitespace-trimmed string"
        )
    if len(name) > 256:
        raise ResetIsolationError("reset strategy name must be at most 256 characters")
    if not isinstance(version, str) or not version or version != version.strip():
        raise ResetIsolationError(
            "reset strategy version must be a non-empty, whitespace-trimmed string"
        )
    if len(version) > 256:
        raise ResetIsolationError("reset strategy version must be at most 256 characters")
    return name, version


def _campaign_trial_id(campaign_id: str, attempt_index: int) -> str:
    return f"campaign:{campaign_id}:attempt:{attempt_index:04d}"


def _receipt_root(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_ROOT_DOMAIN + canonical).hexdigest()
