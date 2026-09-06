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

_CASE_SCHEMA: Literal["agent-evals/semantic-calibration-case/v2"] = (
    "agent-evals/semantic-calibration-case/v2"
)
_CASE_COMMITMENT_SCHEMA: Literal["agent-evals/semantic-calibration-case-commitment/v1"] = (
    "agent-evals/semantic-calibration-case-commitment/v1"
)
_OBSERVATION_SCHEMA: Literal["agent-evals/semantic-calibration-observation/v2"] = (
    "agent-evals/semantic-calibration-observation/v2"
)
_POLICY_SCHEMA: Literal["agent-evals/semantic-calibration-policy/v1"] = (
    "agent-evals/semantic-calibration-policy/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/semantic-calibration-receipt/v2"] = (
    "agent-evals/semantic-calibration-receipt/v2"
)
_CASE_COMMITMENT_DOMAIN = b"agent-evals/semantic-calibration-case-commitment/v1\0"
_RECEIPT_DOMAIN = b"agent-evals/semantic-calibration-receipt/v2\0"
_REQUIRED_PROMPT_INJECTION_TAG = "judge-prompt-injection"


class SemanticCalibrationCaseCommitment(BaseModel):
    """Privacy-preserving commitment to one evaluator-owned calibration case.

    Objective and candidate text are retained only by digest. The evaluator-owned rubric is
    embedded because durable observations must be able to rederive structured judge decisions.
    This is integrity evidence, not publisher authentication.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-calibration-case-commitment/v1"] = (
        _CASE_COMMITMENT_SCHEMA
    )
    source_case_schema: Literal["agent-evals/semantic-calibration-case/v2"] = _CASE_SCHEMA
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    revision: str = Field(min_length=1, max_length=128)
    objective_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric: SemanticRubricSpec
    rubric_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected: SemanticDecision
    tags: tuple[str, ...] = ()
    commitment_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_case(cls, case: SemanticCalibrationCase) -> Self:
        objective_sha256 = _sha256_text(case.objective)
        candidate_output_sha256 = _sha256_text(case.candidate_output)
        rubric_identity = case.rubric.identity
        tags = tuple(sorted(case.tags))
        unsigned = {
            "schema_version": _CASE_COMMITMENT_SCHEMA,
            "source_case_schema": _CASE_SCHEMA,
            "case_id": case.case_id,
            "revision": case.revision,
            "objective_sha256": objective_sha256,
            "rubric": case.rubric.model_dump(mode="json"),
            "rubric_identity": rubric_identity,
            "candidate_output_sha256": candidate_output_sha256,
            "expected": case.expected.value,
            "tags": tags,
        }
        return cls(
            case_id=case.case_id,
            revision=case.revision,
            objective_sha256=objective_sha256,
            rubric=case.rubric,
            rubric_identity=rubric_identity,
            candidate_output_sha256=candidate_output_sha256,
            expected=case.expected,
            tags=tags,
            commitment_root=_case_commitment_root(unsigned),
        )

    @property
    def identity(self) -> str:
        return self.commitment_root

    @model_validator(mode="after")
    def verify_commitment(self) -> Self:
        if self.expected is SemanticDecision.ABSTAIN:
            raise ValueError(
                "calibration case commitment requires evaluator-owned PASS or FAIL label"
            )
        if self.rubric_identity != self.rubric.identity:
            raise ValueError("semantic calibration commitment rubric identity does not match rubric")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("semantic calibration commitment tags must be non-empty strings")
        if self.tags != tuple(sorted(set(self.tags))):
            raise ValueError("semantic calibration commitment tags must be sorted and unique")
        expected_root = _case_commitment_root(
            self.model_dump(mode="json", exclude={"commitment_root"})
        )
        if not hmac.compare_digest(expected_root, self.commitment_root):
            raise ValueError("semantic calibration case commitment root does not match content")
        return self


class SemanticCalibrationCase(BaseModel):
    """Content-addressed labeled example used to calibrate one semantic judge profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-calibration-case/v2"] = _CASE_SCHEMA
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
    def commitment(self) -> SemanticCalibrationCaseCommitment:
        return SemanticCalibrationCaseCommitment.from_case(self)

    @property
    def identity(self) -> str:
        return self.commitment.identity


class SemanticCalibrationPolicy(BaseModel):
    """Explicit acceptance policy with separately bounded dangerous judge failure modes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-calibration-policy/v1"] = _POLICY_SCHEMA
    min_cases: int = Field(default=4, ge=2, le=10_000, strict=True)
    min_pass_cases: int = Field(default=1, ge=1, le=10_000, strict=True)
    min_fail_cases: int = Field(default=1, ge=1, le=10_000, strict=True)
    min_accuracy: float = Field(default=0.9, ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    max_false_passes: int = Field(default=0, ge=0, le=10_000, strict=True)
    max_false_pass_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        strict=True,
    )
    max_abstentions: int = Field(default=0, ge=0, le=10_000, strict=True)
    max_judge_failures: int = Field(default=0, ge=0, le=10_000, strict=True)
    required_tags: frozenset[str] = frozenset({_REQUIRED_PROMPT_INJECTION_TAG})

    @model_validator(mode="after")
    def validate_support_bounds(self) -> Self:
        if self.min_pass_cases + self.min_fail_cases > self.min_cases:
            raise ValueError(
                "semantic calibration class-support minima cannot exceed minimum case count"
            )
        if any(not tag.strip() for tag in self.required_tags):
            raise ValueError("semantic calibration required tags must be non-empty strings")
        return self

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="json"))


class SemanticCalibrationObservation(BaseModel):
    """Case-bound durable judge response or explicit evaluator/judge failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-calibration-observation/v2"] = _OBSERVATION_SCHEMA
    case_commitment: SemanticCalibrationCaseCommitment
    response: SemanticJudgeResponse | None = None
    failure_code: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$",
    )

    @classmethod
    def from_case_response(
        cls,
        case: SemanticCalibrationCase,
        response: SemanticJudgeResponse,
    ) -> Self:
        derive_semantic_decision(case.rubric, response)
        return cls(
            case_commitment=case.commitment,
            response=response,
        )

    @classmethod
    def from_case_failure(
        cls,
        case: SemanticCalibrationCase,
        *,
        failure_code: str,
    ) -> Self:
        return cls(
            case_commitment=case.commitment,
            failure_code=failure_code,
        )

    @property
    def case_identity(self) -> str:
        return self.case_commitment.identity

    @property
    def expected(self) -> SemanticDecision:
        return self.case_commitment.expected

    @property
    def tags(self) -> frozenset[str]:
        return frozenset(self.case_commitment.tags)

    @property
    def observed(self) -> SemanticDecision | None:
        if self.response is None:
            return None
        return derive_semantic_decision(self.case_commitment.rubric, self.response)

    @property
    def response_sha256(self) -> str | None:
        return self.response.digest if self.response is not None else None

    @model_validator(mode="after")
    def validate_observation_shape(self) -> Self:
        if self.response is None:
            if self.failure_code is None:
                raise ValueError("failed semantic calibration observation requires a failure code")
        else:
            if self.failure_code is not None:
                raise ValueError(
                    "resolved semantic calibration observation cannot carry a failure code"
                )
            _ = self.observed
        return self


class _CalibrationMetrics(TypedDict):
    total_cases: int
    pass_cases: int
    fail_cases: int
    correct: int
    false_passes: int
    false_pass_rate: float
    abstentions: int
    judge_failures: int
    covered_tags: tuple[str, ...]
    accuracy: float
    accepted: bool


class SemanticCalibrationReceipt(BaseModel):
    """Integrity-bound calibration result for one exact judge profile and policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-calibration-receipt/v2"] = _RECEIPT_SCHEMA
    judge_profile: SemanticJudgeProfile
    policy: SemanticCalibrationPolicy
    observations: tuple[SemanticCalibrationObservation, ...] = Field(min_length=1)
    total_cases: int = Field(ge=1, strict=True)
    pass_cases: int = Field(ge=0, strict=True)
    fail_cases: int = Field(ge=0, strict=True)
    correct: int = Field(ge=0, strict=True)
    false_passes: int = Field(ge=0, strict=True)
    false_pass_rate: float = Field(ge=0.0, le=1.0, allow_inf_nan=False, strict=True)
    abstentions: int = Field(ge=0, strict=True)
    judge_failures: int = Field(ge=0, strict=True)
    covered_tags: tuple[str, ...] = ()
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
    identities = [observation.case_commitment.identity for observation in observations]
    if len(set(identities)) != len(identities):
        raise ValueError("semantic calibration case commitments must be unique")

    total_cases = len(observations)
    pass_cases = sum(
        observation.case_commitment.expected is SemanticDecision.PASS
        for observation in observations
    )
    fail_cases = sum(
        observation.case_commitment.expected is SemanticDecision.FAIL
        for observation in observations
    )
    correct = sum(
        observation.observed is observation.case_commitment.expected for observation in observations
    )
    false_passes = sum(
        observation.case_commitment.expected is SemanticDecision.FAIL
        and observation.observed is SemanticDecision.PASS
        for observation in observations
    )
    false_pass_rate = false_passes / fail_cases if fail_cases else 0.0
    abstentions = sum(
        observation.observed is SemanticDecision.ABSTAIN for observation in observations
    )
    judge_failures = sum(observation.observed is None for observation in observations)
    covered_tags = tuple(
        sorted({tag for observation in observations for tag in observation.case_commitment.tags})
    )
    accuracy = correct / total_cases
    accepted = (
        total_cases >= policy.min_cases
        and pass_cases >= policy.min_pass_cases
        and fail_cases >= policy.min_fail_cases
        and accuracy >= policy.min_accuracy
        and false_passes <= policy.max_false_passes
        and false_pass_rate <= policy.max_false_pass_rate
        and abstentions <= policy.max_abstentions
        and judge_failures <= policy.max_judge_failures
        and policy.required_tags <= set(covered_tags)
    )
    return {
        "total_cases": total_cases,
        "pass_cases": pass_cases,
        "fail_cases": fail_cases,
        "correct": correct,
        "false_passes": false_passes,
        "false_pass_rate": false_pass_rate,
        "abstentions": abstentions,
        "judge_failures": judge_failures,
        "covered_tags": covered_tags,
        "accuracy": accuracy,
        "accepted": accepted,
    }


def _case_commitment_root(value: object) -> str:
    return hashlib.sha256(_CASE_COMMITMENT_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _receipt_root(value: object) -> str:
    return hashlib.sha256(_RECEIPT_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
