"""Calibration contracts that gate semantic judgment authority."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.semantic.models import (
    SemanticDecision,
    SemanticJudgeInput,
    SemanticJudgeProfile,
    SemanticJudgeResponse,
    SemanticRubricSpec,
    derive_semantic_decision,
)

_CASE_SCHEMA: Literal["agent-evals/semantic-calibration-case/v1"] = (
    "agent-evals/semantic-calibration-case/v1"
)
_POLICY_SCHEMA: Literal["agent-evals/semantic-calibration-policy/v1"] = (
    "agent-evals/semantic-calibration-policy/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/semantic-calibration-receipt/v1"] = (
    "agent-evals/semantic-calibration-receipt/v1"
)
_RECEIPT_DOMAIN = b"agent-evals/semantic-calibration-receipt/v1\0"


class SemanticCalibrationCase(BaseModel):
    """Content-addressed labeled example used to calibrate one semantic judge profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-calibration-case/v1"] = _CASE_SCHEMA
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    revision: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=20_000)
    rubric: SemanticRubricSpec
    candidate_output: str = Field(max_length=100_000)
    expected: SemanticDecision
    tags: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        if self.expected is SemanticDecision.ABSTAIN:
            raise ValueError("calibration cases require evaluator-owned PASS or FAIL labels")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("semantic calibration tags must be non-empty strings")
        return self

    @property
    def judge_input(self) -> SemanticJudgeInput:
        return SemanticJudgeInput(
            objective=self.objective,
            rubric=self.rubric,
            candidate_output=self.candidate_output,
        )

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="json"))


class SemanticCalibrationPolicy(BaseModel):
    """Explicit acceptance policy; false PASS is tracked separately from aggregate accuracy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-calibration-policy/v1"] = _POLICY_SCHEMA
    min_cases: int = Field(default=4, ge=2, le=10_000, strict=True)
    min_pass_cases: int = Field(default=1, ge=1, le=10_000, strict=True)
    min_fail_cases: int = Field(default=1, ge=1, le=10_000, strict=True)
    min_accuracy: float = Field(default=0.9, ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    max_false_passes: int = Field(default=0, ge=0, le=10_000, strict=True)
    max_abstentions: int = Field(default=0, ge=0, le=10_000, strict=True)

    @model_validator(mode="after")
    def validate_support_bounds(self) -> Self:
        if self.min_pass_cases + self.min_fail_cases > self.min_cases:
            raise ValueError(
                "semantic calibration class-support minima cannot exceed minimum case count"
            )
        return self

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="json"))


class SemanticCalibrationObservation(BaseModel):
    """Digest-bound labeled observation; raw controlled case content is not duplicated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected: SemanticDecision
    observed: SemanticDecision
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_case_response(
        cls,
        case: SemanticCalibrationCase,
        response: SemanticJudgeResponse,
    ) -> Self:
        observed = derive_semantic_decision(case.rubric, response)
        return cls(
            case_identity=case.identity,
            expected=case.expected,
            observed=observed,
            response_sha256=response.digest,
        )

    @model_validator(mode="after")
    def reject_expected_abstain(self) -> Self:
        if self.expected is SemanticDecision.ABSTAIN:
            raise ValueError("semantic calibration observation cannot expect ABSTAIN")
        return self


class _CalibrationMetrics(TypedDict):
    total_cases: int
    pass_cases: int
    fail_cases: int
    correct: int
    false_passes: int
    abstentions: int
    accuracy: float
    accepted: bool


class SemanticCalibrationReceipt(BaseModel):
    """Integrity-bound calibration result for one exact judge profile and policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-calibration-receipt/v1"] = _RECEIPT_SCHEMA
    judge_profile: SemanticJudgeProfile
    policy: SemanticCalibrationPolicy
    observations: tuple[SemanticCalibrationObservation, ...] = Field(min_length=1)
    total_cases: int = Field(ge=1, strict=True)
    pass_cases: int = Field(ge=0, strict=True)
    fail_cases: int = Field(ge=0, strict=True)
    correct: int = Field(ge=0, strict=True)
    false_passes: int = Field(ge=0, strict=True)
    abstentions: int = Field(ge=0, strict=True)
    accuracy: float = Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        judge_profile: SemanticJudgeProfile,
        policy: SemanticCalibrationPolicy,
        observations: tuple[SemanticCalibrationObservation, ...],
    ) -> Self:
        metrics = _calibration_metrics(policy, observations)
        unsigned = {
            "schema_version": _RECEIPT_SCHEMA,
            "judge_profile": judge_profile.model_dump(mode="json"),
            "policy": policy.model_dump(mode="json"),
            "observations": [observation.model_dump(mode="json") for observation in observations],
            **metrics,
        }
        return cls(
            judge_profile=judge_profile,
            policy=policy,
            observations=observations,
            receipt_root=_receipt_root(unsigned),
            **metrics,
        )

    @property
    def identity(self) -> str:
        return self.receipt_root

    @model_validator(mode="after")
    def verify_derived_calibration(self) -> Self:
        metrics = _calibration_metrics(self.policy, self.observations)
        for field_name, expected in metrics.items():
            if getattr(self, field_name) != expected:
                raise ValueError(
                    f"semantic calibration {field_name} does not recompute from observations"
                )
        expected_root = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("semantic calibration receipt root does not match receipt content")
        return self


def _calibration_metrics(
    policy: SemanticCalibrationPolicy,
    observations: tuple[SemanticCalibrationObservation, ...],
) -> _CalibrationMetrics:
    if not observations:
        raise ValueError("semantic calibration requires at least one observation")
    identities = [observation.case_identity for observation in observations]
    if len(set(identities)) != len(identities):
        raise ValueError("semantic calibration case identities must be unique")

    total_cases = len(observations)
    pass_cases = sum(observation.expected is SemanticDecision.PASS for observation in observations)
    fail_cases = sum(observation.expected is SemanticDecision.FAIL for observation in observations)
    correct = sum(observation.observed is observation.expected for observation in observations)
    false_passes = sum(
        observation.expected is SemanticDecision.FAIL
        and observation.observed is SemanticDecision.PASS
        for observation in observations
    )
    abstentions = sum(
        observation.observed is SemanticDecision.ABSTAIN for observation in observations
    )
    accuracy = correct / total_cases
    accepted = (
        total_cases >= policy.min_cases
        and pass_cases >= policy.min_pass_cases
        and fail_cases >= policy.min_fail_cases
        and accuracy >= policy.min_accuracy
        and false_passes <= policy.max_false_passes
        and abstentions <= policy.max_abstentions
    )
    return {
        "total_cases": total_cases,
        "pass_cases": pass_cases,
        "fail_cases": fail_cases,
        "correct": correct,
        "false_passes": false_passes,
        "abstentions": abstentions,
        "accuracy": accuracy,
        "accepted": accepted,
    }


def _receipt_root(value: object) -> str:
    return hashlib.sha256(_RECEIPT_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


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
            "semantic calibration material must be finite JSON-compatible data"
        ) from exc
