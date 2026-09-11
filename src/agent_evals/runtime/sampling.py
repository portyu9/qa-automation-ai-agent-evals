"""Versioned repeated-trial sampling, randomness, and stopping provenance."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_SAMPLING_SCHEMA: Literal["agent-evals/session-sampling/v1"] = "agent-evals/session-sampling/v1"
_RANDOMNESS_RECEIPT_SCHEMA: Literal["agent-evals/randomness-control-receipt/v1"] = (
    "agent-evals/randomness-control-receipt/v1"
)
_RANDOMNESS_ROOT_DOMAIN = b"agent-evals/randomness-control-receipt/v1\0"
_CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_BASIS_LENGTH = 2_000


class SamplingProvenanceError(ValueError):
    """Repeated-trial sampling provenance is malformed, incomplete, or inapplicable."""


class SamplingPolicy(StrEnum):
    """How attempts entered the repeated-trial sample."""

    PREDECLARED_ALL_ATTEMPTS = "predeclared_all_attempts"
    EXTERNAL_SELECTION = "external_selection"
    UNKNOWN = "unknown"


class RandomnessStatus(StrEnum):
    """Evaluator knowledge of the runtime/provider randomness control boundary."""

    EVALUATOR_CONTROLLED = "evaluator_controlled"
    EXTERNALLY_CONTROLLED = "externally_controlled"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class StoppingRule(StrEnum):
    """How the repeated-trial campaign decided when to stop observing attempts."""

    FIXED_HORIZON = "fixed_horizon"
    ADAPTIVE_SEQUENTIAL = "adaptive_sequential"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RandomnessControlContext:
    """Bounded evaluator context supplied before one subject attempt."""

    campaign_id: str
    attempt_index: int
    trial_id: str
    subject_identity: str
    scenario_identity: str
    runtime_adapter_name: str
    subject_adapter: str
    subject_adapter_version: str


@dataclass(frozen=True, slots=True)
class RandomnessControlObservation:
    """Digest-only observation returned by a separately supplied randomness control."""

    seed_identity: str
    control_evidence_identity: str

    def __post_init__(self) -> None:
        for label, value in (
            ("seed_identity", self.seed_identity),
            ("control_evidence_identity", self.control_evidence_identity),
        ):
            if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
                raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


class RandomnessControl(Protocol):
    """Evaluator/operator boundary invoked before each evaluator-controlled attempt."""

    @property
    def strategy_name(self) -> str: ...

    @property
    def strategy_version(self) -> str: ...

    async def prepare(
        self,
        *,
        context: RandomnessControlContext,
    ) -> RandomnessControlObservation: ...


class RandomnessControlReceipt(BaseModel):
    """Integrity-bound record of one evaluator-invoked randomness-control relation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/randomness-control-receipt/v1"] = (
        _RANDOMNESS_RECEIPT_SCHEMA
    )
    campaign_id: str = Field(min_length=1, max_length=128)
    attempt_index: int = Field(ge=0, le=1_000_000, strict=True)
    trial_id: str = Field(min_length=1, max_length=256)
    subject_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_adapter_name: str = Field(min_length=1, max_length=256)
    subject_adapter: str = Field(min_length=1, max_length=512)
    subject_adapter_version: str = Field(min_length=1, max_length=512)
    randomness_strategy_name: str = Field(min_length=1, max_length=256)
    randomness_strategy_version: str = Field(min_length=1, max_length=256)
    seed_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    control_evidence_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("campaign_id")
    @classmethod
    def validate_campaign_id(cls, value: str) -> str:
        if _CAMPAIGN_ID_RE.fullmatch(value) is None:
            raise ValueError("randomness receipt campaign_id is not canonical")
        return value

    @field_validator(
        "runtime_adapter_name",
        "randomness_strategy_name",
        "randomness_strategy_version",
    )
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(
                "randomness receipt control identities must not contain surrounding whitespace"
            )
        return value

    @model_validator(mode="after")
    def validate_attempt_and_root(self) -> Self:
        expected_trial = _campaign_trial_id(self.campaign_id, self.attempt_index)
        if self.trial_id != expected_trial:
            raise ValueError("randomness receipt trial ID does not match campaign attempt")
        expected_root = _receipt_root(self.model_dump(mode="python", exclude={"receipt_root"}))
        if self.receipt_root != expected_root:
            raise ValueError("randomness control receipt root mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        context: RandomnessControlContext,
        randomness_strategy_name: str,
        randomness_strategy_version: str,
        seed_identity: str,
        control_evidence_identity: str,
    ) -> RandomnessControlReceipt:
        unsigned: dict[str, Any] = {
            "schema_version": _RANDOMNESS_RECEIPT_SCHEMA,
            "campaign_id": context.campaign_id,
            "attempt_index": context.attempt_index,
            "trial_id": context.trial_id,
            "subject_identity": context.subject_identity,
            "scenario_identity": context.scenario_identity,
            "runtime_adapter_name": context.runtime_adapter_name,
            "subject_adapter": context.subject_adapter,
            "subject_adapter_version": context.subject_adapter_version,
            "randomness_strategy_name": randomness_strategy_name,
            "randomness_strategy_version": randomness_strategy_version,
            "seed_identity": seed_identity,
            "control_evidence_identity": control_evidence_identity,
        }
        return cls.model_validate({**unsigned, "receipt_root": _receipt_root(unsigned)})


class SessionSamplingMetadata(BaseModel):
    """Versioned repeated-trial sampling/randomness/stopping contract material."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/session-sampling/v1"] = _SAMPLING_SCHEMA
    sampling_policy: SamplingPolicy
    randomness_status: RandomnessStatus
    stopping_rule: StoppingRule
    planned_trials: int | None = Field(default=None, ge=1, le=1_000_000, strict=True)
    sampling_basis: str | None = Field(default=None, max_length=_MAX_BASIS_LENGTH)
    randomness_basis: str | None = Field(default=None, max_length=_MAX_BASIS_LENGTH)
    stopping_basis: str | None = Field(default=None, max_length=_MAX_BASIS_LENGTH)
    randomness_strategy_name: str | None = Field(default=None, max_length=256)
    randomness_strategy_version: str | None = Field(default=None, max_length=256)
    randomness_control_receipts: tuple[RandomnessControlReceipt, ...] = ()

    @field_validator("sampling_basis", "randomness_basis", "stopping_basis")
    @classmethod
    def validate_optional_basis(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("sampling provenance basis strings must be non-empty and trimmed")
        return value

    @field_validator("randomness_strategy_name", "randomness_strategy_version")
    @classmethod
    def validate_optional_strategy_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or value != value.strip():
            raise ValueError("randomness strategy identity must be non-empty and trimmed")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.sampling_policy is SamplingPolicy.PREDECLARED_ALL_ATTEMPTS:
            if self.sampling_basis is not None:
                raise ValueError("predeclared sampling must not carry an external sampling basis")
        elif self.sampling_policy is SamplingPolicy.EXTERNAL_SELECTION:
            if self.sampling_basis is None:
                raise ValueError("external sampling selection requires an explicit basis")
        elif self.sampling_policy is SamplingPolicy.UNKNOWN:
            if self.sampling_basis is not None:
                raise ValueError("unknown sampling policy must not carry an asserted basis")
        else:
            raise ValueError("unsupported sampling policy")

        if self.stopping_rule is StoppingRule.FIXED_HORIZON:
            if self.planned_trials is None:
                raise ValueError("fixed-horizon stopping requires planned_trials")
            if self.stopping_basis is not None:
                raise ValueError("fixed-horizon stopping must not carry an adaptive stopping basis")
        elif self.stopping_rule is StoppingRule.ADAPTIVE_SEQUENTIAL:
            if self.planned_trials is not None:
                raise ValueError("adaptive/sequential stopping must not claim a fixed horizon")
            if self.stopping_basis is None:
                raise ValueError("adaptive/sequential stopping requires an explicit rule basis")
        elif self.stopping_rule is StoppingRule.UNKNOWN:
            if self.planned_trials is not None or self.stopping_basis is not None:
                raise ValueError(
                    "unknown stopping provenance must not claim a horizon or rule basis"
                )
        else:
            raise ValueError("unsupported stopping rule")

        strategy_present = (
            self.randomness_strategy_name is not None
            or self.randomness_strategy_version is not None
        )
        if strategy_present and (
            self.randomness_strategy_name is None or self.randomness_strategy_version is None
        ):
            raise ValueError("randomness strategy name/version must be both present or both absent")

        if self.randomness_status is RandomnessStatus.EVALUATOR_CONTROLLED:
            if self.randomness_basis is not None:
                raise ValueError("evaluator-controlled randomness must not carry an external basis")
            if self.randomness_strategy_name is None or self.randomness_strategy_version is None:
                raise ValueError("evaluator-controlled randomness requires strategy provenance")
            if not self.randomness_control_receipts:
                raise ValueError("evaluator-controlled randomness requires per-attempt receipts")
        elif self.randomness_status in (
            RandomnessStatus.EXTERNALLY_CONTROLLED,
            RandomnessStatus.UNAVAILABLE,
        ):
            if self.randomness_basis is None:
                raise ValueError(
                    f"{self.randomness_status.value} randomness requires an explicit basis"
                )
            if strategy_present or self.randomness_control_receipts:
                raise ValueError(
                    "non-evaluator-controlled randomness must not carry evaluator control provenance"
                )
        elif self.randomness_status is RandomnessStatus.UNKNOWN:
            if (
                self.randomness_basis is not None
                or strategy_present
                or self.randomness_control_receipts
            ):
                raise ValueError("unknown randomness must not carry a seed/control claim")
        else:
            raise ValueError("unsupported randomness status")
        return self


def validate_randomness_request(
    status: object,
    basis: object,
    control: RandomnessControl | None,
) -> None:
    """Validate caller-supplied randomness metadata before subject execution."""
    if type(status) is not RandomnessStatus:
        raise SamplingProvenanceError("randomness_status must be an exact RandomnessStatus member")
    if status is RandomnessStatus.EVALUATOR_CONTROLLED:
        if basis is not None:
            raise SamplingProvenanceError(
                "evaluator-controlled randomness must not carry an external basis"
            )
        if control is None:
            raise SamplingProvenanceError(
                "evaluator-controlled randomness requires a separate randomness control"
            )
        return
    if control is not None:
        raise SamplingProvenanceError(
            "randomness control may be supplied only for evaluator-controlled randomness"
        )
    if status in (RandomnessStatus.EXTERNALLY_CONTROLLED, RandomnessStatus.UNAVAILABLE):
        _validate_basis(basis, label=f"{status.value} randomness")
        return
    if status is RandomnessStatus.UNKNOWN:
        if basis is not None:
            raise SamplingProvenanceError("unknown randomness must not carry an asserted basis")
        return
    raise SamplingProvenanceError("unsupported randomness status")


def validate_randomness_strategy_identity(name: object, version: object) -> tuple[str, str]:
    """Validate bounded control metadata before any subject trial executes."""
    if not isinstance(name, str) or not name or name != name.strip():
        raise SamplingProvenanceError(
            "randomness strategy name must be a non-empty, whitespace-trimmed string"
        )
    if len(name) > 256:
        raise SamplingProvenanceError("randomness strategy name must be at most 256 characters")
    if not isinstance(version, str) or not version or version != version.strip():
        raise SamplingProvenanceError(
            "randomness strategy version must be a non-empty, whitespace-trimmed string"
        )
    if len(version) > 256:
        raise SamplingProvenanceError("randomness strategy version must be at most 256 characters")
    return name, version


def verify_session_sampling_metadata(
    metadata: SessionSamplingMetadata,
    *,
    campaign_id: str | None,
    subject_identity: str,
    scenario_identity: str,
    runtime_adapter_name: str | None,
    subject_adapter: str | None,
    subject_adapter_version: str | None,
    trial_ids: tuple[str, ...],
) -> None:
    """Revalidate sampling/stopping provenance against the finalized trial vector."""
    if type(metadata) is not SessionSamplingMetadata:
        raise SamplingProvenanceError(
            "sampling metadata must be an exact SessionSamplingMetadata instance"
        )
    try:
        metadata = SessionSamplingMetadata.model_validate(metadata.model_dump(mode="python"))
    except ValidationError as exc:
        raise SamplingProvenanceError("session sampling metadata is malformed") from exc

    if metadata.stopping_rule is StoppingRule.FIXED_HORIZON and metadata.planned_trials != len(
        trial_ids
    ):
        raise SamplingProvenanceError(
            "fixed-horizon session trial count does not match the predeclared horizon"
        )

    if metadata.randomness_status is RandomnessStatus.EVALUATOR_CONTROLLED:
        if (
            campaign_id is None
            or runtime_adapter_name is None
            or subject_adapter is None
            or subject_adapter_version is None
            or metadata.randomness_strategy_name is None
            or metadata.randomness_strategy_version is None
        ):
            raise SamplingProvenanceError(
                "evaluator-controlled randomness requires complete campaign/adapter provenance"
            )
        verify_randomness_control_sequence(
            metadata.randomness_control_receipts,
            campaign_id=campaign_id,
            subject_identity=subject_identity,
            scenario_identity=scenario_identity,
            runtime_adapter_name=runtime_adapter_name,
            subject_adapter=subject_adapter,
            subject_adapter_version=subject_adapter_version,
            randomness_strategy_name=metadata.randomness_strategy_name,
            randomness_strategy_version=metadata.randomness_strategy_version,
            trial_ids=trial_ids,
        )


def require_independence_qualifiable_sampling(
    metadata: SessionSamplingMetadata | None,
) -> SessionSamplingMetadata:
    """Require provenance compatible with the current independent-attempt transforms."""
    if metadata is None:
        raise SamplingProvenanceError(
            "independent-attempt metrics require versioned sampling/stopping provenance"
        )
    if metadata.sampling_policy is not SamplingPolicy.PREDECLARED_ALL_ATTEMPTS:
        raise SamplingProvenanceError(
            "independent-attempt metrics require predeclared inclusion of all campaign attempts"
        )
    if metadata.stopping_rule is not StoppingRule.FIXED_HORIZON:
        raise SamplingProvenanceError(
            "independent-attempt metrics require a predeclared fixed-horizon stopping rule"
        )
    return metadata


def verify_randomness_control_sequence(
    receipts: tuple[RandomnessControlReceipt, ...],
    *,
    campaign_id: str,
    subject_identity: str,
    scenario_identity: str,
    runtime_adapter_name: str,
    subject_adapter: str,
    subject_adapter_version: str,
    randomness_strategy_name: str,
    randomness_strategy_version: str,
    trial_ids: tuple[str, ...],
) -> None:
    """Revalidate one exact randomness-control receipt per finalized subject attempt."""
    if not trial_ids:
        raise SamplingProvenanceError("randomness control sequence requires at least one trial")
    if len(receipts) != len(trial_ids):
        raise SamplingProvenanceError(
            "evaluator-controlled randomness requires exactly one receipt per trial"
        )
    if any(type(receipt) is not RandomnessControlReceipt for receipt in receipts):
        raise SamplingProvenanceError(
            "randomness receipts must be exact RandomnessControlReceipt instances"
        )
    if len({receipt.receipt_root for receipt in receipts}) != len(receipts):
        raise SamplingProvenanceError("randomness receipt roots must be unique across attempts")
    if len({receipt.seed_identity for receipt in receipts}) != len(receipts):
        raise SamplingProvenanceError(
            "evaluator-controlled attempt seed identities must be unique across attempts"
        )

    for attempt_index, receipt in enumerate(receipts):
        context = RandomnessControlContext(
            campaign_id=campaign_id,
            attempt_index=attempt_index,
            trial_id=trial_ids[attempt_index],
            subject_identity=subject_identity,
            scenario_identity=scenario_identity,
            runtime_adapter_name=runtime_adapter_name,
            subject_adapter=subject_adapter,
            subject_adapter_version=subject_adapter_version,
        )
        try:
            expected = RandomnessControlReceipt.create(
                context=context,
                randomness_strategy_name=randomness_strategy_name,
                randomness_strategy_version=randomness_strategy_version,
                seed_identity=receipt.seed_identity,
                control_evidence_identity=receipt.control_evidence_identity,
            )
        except ValueError as exc:
            raise SamplingProvenanceError(
                f"randomness receipt {attempt_index} could not be reconstructed"
            ) from exc
        if receipt != expected:
            raise SamplingProvenanceError(
                f"randomness receipt {attempt_index} does not match the finalized campaign attempt"
            )


def _validate_basis(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SamplingProvenanceError(f"{label} requires a non-empty, whitespace-trimmed basis")
    if len(value) > _MAX_BASIS_LENGTH:
        raise SamplingProvenanceError(
            f"{label} basis must be at most {_MAX_BASIS_LENGTH} characters"
        )
    return value


def _campaign_trial_id(campaign_id: str, attempt_index: int) -> str:
    return f"campaign:{campaign_id}:attempt:{attempt_index:04d}"


def _receipt_root(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_RANDOMNESS_ROOT_DOMAIN + canonical).hexdigest()
