"""Stratified semantic calibration qualification above existing v2 calibration receipts.

This module adds explicit development/validation/holdout separation, per-risk FAIL support minima,
and one-sided false-pass confidence bounds. It does not replace SemanticCalibrationReceipt/v2 or
grant semantic judgment deterministic grading authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from math import sqrt
from typing import Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.evidence.limits import RECEIPT_MATERIAL_BUDGET, validate_json_material
from agent_evals.semantic.calibration import (
    SemanticCalibrationObservation,
    SemanticCalibrationPolicy,
    SemanticCalibrationReceipt,
)
from agent_evals.semantic.models import SemanticDecision, SemanticJudgeProfile

_POLICY_SCHEMA: Literal["agent-evals/semantic-stratified-calibration-policy/v1"] = (
    "agent-evals/semantic-stratified-calibration-policy/v1"
)
_OBSERVATION_SCHEMA: Literal["agent-evals/semantic-stratified-calibration-observation/v1"] = (
    "agent-evals/semantic-stratified-calibration-observation/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/semantic-stratified-calibration-receipt/v1"] = (
    "agent-evals/semantic-stratified-calibration-receipt/v1"
)
_RECEIPT_DOMAIN = b"agent-evals/semantic-stratified-calibration-receipt/v1\0"
_DEFAULT_ONE_SIDED_95_Z = 1.6448536269514722


class CalibrationSplit(StrEnum):
    """Declared calibration partition."""

    DEVELOPMENT = "development"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


class CalibrationRiskTagRequirement(BaseModel):
    """Minimum evaluator-FAIL support required for one risk tag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tag: str = Field(min_length=1, max_length=128)
    min_validation_fail_cases: int = Field(default=1, ge=1, le=10_000, strict=True)
    min_holdout_fail_cases: int = Field(default=1, ge=1, le=10_000, strict=True)

    @field_validator("tag")
    @classmethod
    def validate_tag(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("calibration risk tag must not contain surrounding whitespace")
        return value


_DEFAULT_RISK_REQUIREMENTS = (
    CalibrationRiskTagRequirement(
        tag="judge-prompt-injection",
        min_validation_fail_cases=12,
        min_holdout_fail_cases=25,
    ),
)


class StratifiedCalibrationPolicy(BaseModel):
    """Acceptance policy over isolated validation and holdout strata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-stratified-calibration-policy/v1"] = (
        _POLICY_SCHEMA
    )
    validation_policy: SemanticCalibrationPolicy
    holdout_policy: SemanticCalibrationPolicy
    min_development_cases: int = Field(default=10, ge=0, le=10_000, strict=True)
    confidence_z: float = Field(
        default=_DEFAULT_ONE_SIDED_95_Z,
        gt=0.0,
        le=8.0,
        allow_inf_nan=False,
        strict=True,
    )
    max_validation_false_pass_upper_bound: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        strict=True,
    )
    max_holdout_false_pass_upper_bound: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        strict=True,
    )
    risk_requirements: tuple[CalibrationRiskTagRequirement, ...] = Field(
        default=_DEFAULT_RISK_REQUIREMENTS,
        min_length=1,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_risk_requirements(self) -> Self:
        tags = tuple(requirement.tag for requirement in self.risk_requirements)
        if len(set(tags)) != len(tags):
            raise ValueError("stratified calibration risk requirements must have unique tags")
        if tags != tuple(sorted(tags)):
            raise ValueError("stratified calibration risk requirements must be sorted by tag")
        return self

    @property
    def identity(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.model_dump(mode="json"))).hexdigest()


class StratifiedCalibrationObservation(BaseModel):
    """Bind one durable calibration observation to exactly one declared split."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[
        "agent-evals/semantic-stratified-calibration-observation/v1"
    ] = _OBSERVATION_SCHEMA
    split: CalibrationSplit
    observation: SemanticCalibrationObservation

    @property
    def case_identity(self) -> str:
        return self.observation.case_identity


class CalibrationRiskSupport(BaseModel):
    """Derived evaluator-FAIL support for one configured risk tag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tag: str = Field(min_length=1, max_length=128)
    fail_cases: int = Field(ge=0, le=10_000, strict=True)


class _DerivedStratifiedMetrics(TypedDict):
    validation_receipt: SemanticCalibrationReceipt
    holdout_receipt: SemanticCalibrationReceipt
    validation_false_pass_upper_bound: float
    holdout_false_pass_upper_bound: float
    validation_risk_support: tuple[CalibrationRiskSupport, ...]
    holdout_risk_support: tuple[CalibrationRiskSupport, ...]
    accepted: bool


class StratifiedCalibrationReceipt(BaseModel):
    """Integrity-bound qualification for one exact semantic judge profile.

    Acceptance requires existing v2 validation and holdout policies, development support,
    per-risk FAIL support in validation and holdout independently, and bounded one-sided false-pass
    rates. The embedded holdout v2 receipt can be reused by existing semantic judgment machinery
    only after this higher-level qualification is accepted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[
        "agent-evals/semantic-stratified-calibration-receipt/v1"
    ] = _RECEIPT_SCHEMA
    judge_profile: SemanticJudgeProfile
    policy: StratifiedCalibrationPolicy
    observations: tuple[StratifiedCalibrationObservation, ...] = Field(
        min_length=1,
        max_length=30_000,
    )
    validation_receipt: SemanticCalibrationReceipt
    holdout_receipt: SemanticCalibrationReceipt
    validation_false_pass_upper_bound: float = Field(
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        strict=True,
    )
    holdout_false_pass_upper_bound: float = Field(
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        strict=True,
    )
    validation_risk_support: tuple[CalibrationRiskSupport, ...]
    holdout_risk_support: tuple[CalibrationRiskSupport, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        judge_profile: SemanticJudgeProfile,
        policy: StratifiedCalibrationPolicy,
        observations: tuple[StratifiedCalibrationObservation, ...],
    ) -> Self:
        canonical = _canonical_partition(observations)
        derived = _derive_stratified_metrics(
            judge_profile=judge_profile,
            policy=policy,
            observations=canonical,
        )
        unsigned = _unsigned_receipt_material(
            judge_profile=judge_profile,
            policy=policy,
            observations=canonical,
            derived=derived,
        )
        return cls(
            judge_profile=judge_profile,
            policy=policy,
            observations=canonical,
            validation_receipt=derived["validation_receipt"],
            holdout_receipt=derived["holdout_receipt"],
            validation_false_pass_upper_bound=derived[
                "validation_false_pass_upper_bound"
            ],
            holdout_false_pass_upper_bound=derived["holdout_false_pass_upper_bound"],
            validation_risk_support=derived["validation_risk_support"],
            holdout_risk_support=derived["holdout_risk_support"],
            accepted=derived["accepted"],
            receipt_root=_receipt_root(unsigned),
        )

    @property
    def identity(self) -> str:
        return self.receipt_root

    def require_accepted_holdout(self) -> SemanticCalibrationReceipt:
        """Return the exact v2 holdout receipt only after stratified qualification succeeds."""

        if not self.accepted:
            raise ValueError("stratified semantic calibration is not accepted")
        return self.holdout_receipt

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        canonical = _canonical_partition(self.observations)
        if canonical != self.observations:
            raise ValueError("stratified calibration observations are not in canonical split order")
        derived = _derive_stratified_metrics(
            judge_profile=self.judge_profile,
            policy=self.policy,
            observations=self.observations,
        )
        if self.validation_receipt != derived["validation_receipt"]:
            raise ValueError("stratified validation receipt does not recompute")
        if self.holdout_receipt != derived["holdout_receipt"]:
            raise ValueError("stratified holdout receipt does not recompute")
        if (
            self.validation_false_pass_upper_bound
            != derived["validation_false_pass_upper_bound"]
        ):
            raise ValueError("stratified validation false-pass bound does not recompute")
        if (
            self.holdout_false_pass_upper_bound
            != derived["holdout_false_pass_upper_bound"]
        ):
            raise ValueError("stratified holdout false-pass bound does not recompute")
        if self.validation_risk_support != derived["validation_risk_support"]:
            raise ValueError("stratified validation risk support does not recompute")
        if self.holdout_risk_support != derived["holdout_risk_support"]:
            raise ValueError("stratified holdout risk support does not recompute")
        if self.accepted is not derived["accepted"]:
            raise ValueError("stratified calibration acceptance does not recompute")
        expected = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected, self.receipt_root):
            raise ValueError("stratified semantic calibration receipt root mismatch")
        return self


def _canonical_partition(
    observations: tuple[StratifiedCalibrationObservation, ...],
) -> tuple[StratifiedCalibrationObservation, ...]:
    identities = [item.case_identity for item in observations]
    if len(set(identities)) != len(identities):
        raise ValueError("one calibration case cannot appear in multiple declared splits")
    order = {
        CalibrationSplit.DEVELOPMENT: 0,
        CalibrationSplit.VALIDATION: 1,
        CalibrationSplit.HOLDOUT: 2,
    }
    return tuple(sorted(observations, key=lambda item: (order[item.split], item.case_identity)))


def _derive_stratified_metrics(
    *,
    judge_profile: SemanticJudgeProfile,
    policy: StratifiedCalibrationPolicy,
    observations: tuple[StratifiedCalibrationObservation, ...],
) -> _DerivedStratifiedMetrics:
    development = tuple(
        item.observation
        for item in observations
        if item.split is CalibrationSplit.DEVELOPMENT
    )
    validation = tuple(
        item.observation for item in observations if item.split is CalibrationSplit.VALIDATION
    )
    holdout = tuple(
        item.observation for item in observations if item.split is CalibrationSplit.HOLDOUT
    )
    if not validation:
        raise ValueError("stratified calibration requires validation observations")
    if not holdout:
        raise ValueError("stratified calibration requires holdout observations")

    validation_receipt = SemanticCalibrationReceipt.create(
        judge_profile=judge_profile,
        policy=policy.validation_policy,
        observations=validation,
    )
    holdout_receipt = SemanticCalibrationReceipt.create(
        judge_profile=judge_profile,
        policy=policy.holdout_policy,
        observations=holdout,
    )
    validation_upper = _false_pass_upper_bound(
        false_passes=validation_receipt.false_passes,
        fail_cases=validation_receipt.fail_cases,
        z=policy.confidence_z,
    )
    holdout_upper = _false_pass_upper_bound(
        false_passes=holdout_receipt.false_passes,
        fail_cases=holdout_receipt.fail_cases,
        z=policy.confidence_z,
    )
    validation_support = _risk_support(
        observations=validation,
        requirements=policy.risk_requirements,
    )
    holdout_support = _risk_support(
        observations=holdout,
        requirements=policy.risk_requirements,
    )
    support_accepted = all(
        validation_item.fail_cases >= requirement.min_validation_fail_cases
        and holdout_item.fail_cases >= requirement.min_holdout_fail_cases
        for requirement, validation_item, holdout_item in zip(
            policy.risk_requirements,
            validation_support,
            holdout_support,
            strict=True,
        )
    )
    accepted = (
        len(development) >= policy.min_development_cases
        and validation_receipt.accepted
        and holdout_receipt.accepted
        and validation_upper <= policy.max_validation_false_pass_upper_bound
        and holdout_upper <= policy.max_holdout_false_pass_upper_bound
        and support_accepted
    )
    return {
        "validation_receipt": validation_receipt,
        "holdout_receipt": holdout_receipt,
        "validation_false_pass_upper_bound": validation_upper,
        "holdout_false_pass_upper_bound": holdout_upper,
        "validation_risk_support": validation_support,
        "holdout_risk_support": holdout_support,
        "accepted": accepted,
    }


def _risk_support(
    *,
    observations: tuple[SemanticCalibrationObservation, ...],
    requirements: tuple[CalibrationRiskTagRequirement, ...],
) -> tuple[CalibrationRiskSupport, ...]:
    return tuple(
        CalibrationRiskSupport(
            tag=requirement.tag,
            fail_cases=sum(
                observation.expected is SemanticDecision.FAIL
                and requirement.tag in observation.tags
                for observation in observations
            ),
        )
        for requirement in requirements
    )


def _false_pass_upper_bound(*, false_passes: int, fail_cases: int, z: float) -> float:
    if fail_cases <= 0:
        return 1.0
    proportion = false_passes / fail_cases
    z_squared = z * z
    denominator = 1.0 + z_squared / fail_cases
    center = (proportion + z_squared / (2.0 * fail_cases)) / denominator
    radius = (
        z
        * sqrt(
            (proportion * (1.0 - proportion) + z_squared / (4.0 * fail_cases))
            / fail_cases
        )
        / denominator
    )
    return min(1.0, center + radius)


def _unsigned_receipt_material(
    *,
    judge_profile: SemanticJudgeProfile,
    policy: StratifiedCalibrationPolicy,
    observations: tuple[StratifiedCalibrationObservation, ...],
    derived: _DerivedStratifiedMetrics,
) -> dict[str, object]:
    return {
        "schema_version": _RECEIPT_SCHEMA,
        "judge_profile": judge_profile.model_dump(mode="json"),
        "policy": policy.model_dump(mode="json"),
        "observations": [item.model_dump(mode="json") for item in observations],
        "validation_receipt": derived["validation_receipt"].model_dump(mode="json"),
        "holdout_receipt": derived["holdout_receipt"].model_dump(mode="json"),
        "validation_false_pass_upper_bound": derived[
            "validation_false_pass_upper_bound"
        ],
        "holdout_false_pass_upper_bound": derived["holdout_false_pass_upper_bound"],
        "validation_risk_support": [
            support.model_dump(mode="json") for support in derived["validation_risk_support"]
        ],
        "holdout_risk_support": [
            support.model_dump(mode="json") for support in derived["holdout_risk_support"]
        ],
        "accepted": derived["accepted"],
    }


def _receipt_root(value: object) -> str:
    validate_json_material(
        value,
        budget=RECEIPT_MATERIAL_BUDGET,
        label="stratified semantic calibration receipt material",
    )
    return hashlib.sha256(_RECEIPT_DOMAIN + _canonical_json_bytes(value)).hexdigest()


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
            "stratified semantic calibration material must be finite JSON-compatible data"
        ) from exc
