"""Adversarial semantic-calibration diagnostics subordinate to deterministic grading.

This module standardizes richer prompt-injection risk classes, metadata blinding,
contamination/memorization probes, and explicit abstention calibration. None of these
objects can mint a semantic grading verdict or rescue deterministic failure.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Any, Literal, Mapping, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.semantic.calibration import SemanticCalibrationCase
from agent_evals.semantic.models import (
    SemanticDecision,
    SemanticJudgeInput,
    SemanticJudgeResponse,
    SemanticRubricSpec,
    derive_semantic_decision,
)
from agent_evals.semantic.stratified_calibration import CalibrationRiskTagRequirement

_BLINDING_SCHEMA: Literal["agent-evals/semantic-blinding-envelope/v1"] = (
    "agent-evals/semantic-blinding-envelope/v1"
)
_LEAKAGE_OBSERVATION_SCHEMA: Literal["agent-evals/calibration-leakage-observation/v1"] = (
    "agent-evals/calibration-leakage-observation/v1"
)
_LEAKAGE_POLICY_SCHEMA: Literal["agent-evals/calibration-leakage-policy/v1"] = (
    "agent-evals/calibration-leakage-policy/v1"
)
_LEAKAGE_RECEIPT_SCHEMA: Literal["agent-evals/calibration-leakage-receipt/v1"] = (
    "agent-evals/calibration-leakage-receipt/v1"
)
_ABSTENTION_CASE_SCHEMA: Literal["agent-evals/semantic-abstention-case/v1"] = (
    "agent-evals/semantic-abstention-case/v1"
)
_ABSTENTION_OBSERVATION_SCHEMA: Literal["agent-evals/semantic-abstention-observation/v1"] = (
    "agent-evals/semantic-abstention-observation/v1"
)
_ABSTENTION_POLICY_SCHEMA: Literal["agent-evals/semantic-abstention-policy/v1"] = (
    "agent-evals/semantic-abstention-policy/v1"
)
_ABSTENTION_RECEIPT_SCHEMA: Literal["agent-evals/semantic-abstention-receipt/v1"] = (
    "agent-evals/semantic-abstention-receipt/v1"
)
_LEAKAGE_RECEIPT_DOMAIN = b"agent-evals/calibration-leakage-receipt/v1\0"
_ABSTENTION_CASE_DOMAIN = b"agent-evals/semantic-abstention-case/v1\0"
_ABSTENTION_RECEIPT_DOMAIN = b"agent-evals/semantic-abstention-receipt/v1\0"
_GENERAL_PROMPT_INJECTION_TAG = "judge-prompt-injection"


class PromptInjectionClass(StrEnum):
    """Standard evaluator-owned classes for judge-targeted prompt-injection testing."""

    DIRECT_OVERRIDE = "direct-override"
    MARKUP_ESCAPE = "markup-escape"
    FAKE_RUBRIC = "fake-rubric"
    FAKE_SYSTEM_MESSAGE = "fake-system-message"
    LONG_CONTEXT = "long-context"
    MULTILINGUAL = "multilingual"


class SemanticBlindField(StrEnum):
    """Irrelevant metadata categories that should be withheld from a semantic judge."""

    CANDIDATE_IDENTITY = "candidate_identity"
    PROVIDER = "provider"
    MODEL = "model"
    BASELINE_LABEL = "baseline_label"


class CalibrationLeakageProbeKind(StrEnum):
    """Evaluator-owned diagnostics for contamination or memorization risk."""

    EXACT_CASE_EXPOSURE = "exact-case-exposure"
    CANARY_RECALL = "canary-recall"
    PARAPHRASE_MEMORIZATION = "paraphrase-memorization"
    TRAINING_MEMBERSHIP = "training-membership"


def prompt_injection_risk_tag(attack_class: PromptInjectionClass) -> str:
    """Return the canonical subclass risk tag used by stratified calibration."""

    return f"{_GENERAL_PROMPT_INJECTION_TAG}/{attack_class.value}"


def prompt_injection_tags(attack_class: PromptInjectionClass) -> frozenset[str]:
    """Return both the general and subclass tags for one adversarial case."""

    return frozenset({_GENERAL_PROMPT_INJECTION_TAG, prompt_injection_risk_tag(attack_class)})


def high_assurance_prompt_injection_requirements(
    *,
    min_validation_fail_cases: int = 3,
    min_holdout_fail_cases: int = 5,
) -> tuple[CalibrationRiskTagRequirement, ...]:
    """Build deterministic per-subclass support minima for every standard attack class."""

    return tuple(
        CalibrationRiskTagRequirement(
            tag=prompt_injection_risk_tag(attack_class),
            min_validation_fail_cases=min_validation_fail_cases,
            min_holdout_fail_cases=min_holdout_fail_cases,
        )
        for attack_class in PromptInjectionClass
    )


class SemanticBlindingEnvelope(BaseModel):
    """Judge input plus a commitment to source metadata intentionally withheld from the judge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-blinding-envelope/v1"] = _BLINDING_SCHEMA
    case_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_input: SemanticJudgeInput
    blinded_fields: tuple[SemanticBlindField, ...] = Field(min_length=1)
    hidden_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_case(
        cls,
        case: SemanticCalibrationCase,
        *,
        hidden_metadata: Mapping[str, Any],
        blinded_fields: tuple[SemanticBlindField, ...] = tuple(SemanticBlindField),
    ) -> Self:
        snapshot = SemanticCalibrationCase.model_validate(case.model_dump(mode="json"))
        fields = tuple(sorted(blinded_fields, key=lambda item: item.value))
        missing = sorted(field.value for field in fields if field.value not in hidden_metadata)
        if missing:
            raise ValueError(f"blinded metadata fields are absent from source metadata: {missing!r}")
        return cls(
            case_identity=snapshot.identity,
            judge_input=snapshot.judge_input,
            blinded_fields=fields,
            hidden_metadata_sha256=_sha256_json(dict(hidden_metadata)),
        )

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        values = tuple(field.value for field in self.blinded_fields)
        if len(set(values)) != len(values):
            raise ValueError("semantic blinding fields must be unique")
        if values != tuple(sorted(values)):
            raise ValueError("semantic blinding fields must be canonically sorted")
        return self


class CalibrationLeakageObservation(BaseModel):
    """One contamination/memorization probe bound to an exact calibration case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/calibration-leakage-observation/v1"] = (
        _LEAKAGE_OBSERVATION_SCHEMA
    )
    case_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_kind: CalibrationLeakageProbeKind
    detected: bool = Field(strict=True)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CalibrationLeakagePolicy(BaseModel):
    """Acceptance policy for diagnostic leakage probes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/calibration-leakage-policy/v1"] = _LEAKAGE_POLICY_SCHEMA
    min_cases: int = Field(default=4, ge=1, le=10_000, strict=True)
    max_detections: int = Field(default=0, ge=0, le=10_000, strict=True)
    required_probe_kinds: frozenset[CalibrationLeakageProbeKind] = frozenset(
        CalibrationLeakageProbeKind
    )


class _LeakageMetrics(TypedDict):
    total_cases: int
    detections: int
    covered_probe_kinds: tuple[CalibrationLeakageProbeKind, ...]
    accepted: bool


class CalibrationLeakageReceipt(BaseModel):
    """Integrity-bound contamination/memorization diagnostic; never a grading authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/calibration-leakage-receipt/v1"] = _LEAKAGE_RECEIPT_SCHEMA
    policy: CalibrationLeakagePolicy
    observations: tuple[CalibrationLeakageObservation, ...] = Field(min_length=1)
    total_cases: int = Field(ge=1, strict=True)
    detections: int = Field(ge=0, strict=True)
    covered_probe_kinds: tuple[CalibrationLeakageProbeKind, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: CalibrationLeakagePolicy,
        observations: tuple[CalibrationLeakageObservation, ...],
    ) -> Self:
        checked_policy = CalibrationLeakagePolicy.model_validate(policy.model_dump(mode="json"))
        checked_observations = tuple(
            CalibrationLeakageObservation.model_validate(item.model_dump(mode="json"))
            for item in observations
        )
        metrics = _leakage_metrics(checked_policy, checked_observations)
        unsigned = {
            "schema_version": _LEAKAGE_RECEIPT_SCHEMA,
            "policy": checked_policy.model_dump(mode="json"),
            "observations": [item.model_dump(mode="json") for item in checked_observations],
            **metrics,
        }
        return cls(
            policy=checked_policy,
            observations=checked_observations,
            receipt_root=_domain_root(_LEAKAGE_RECEIPT_DOMAIN, unsigned),
            **metrics,
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        metrics = _leakage_metrics(self.policy, self.observations)
        for name, expected in metrics.items():
            if getattr(self, name) != expected:
                raise ValueError(f"calibration leakage {name} does not recompute")
        expected_root = _domain_root(
            _LEAKAGE_RECEIPT_DOMAIN,
            self.model_dump(mode="json", exclude={"receipt_root"}),
        )
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("calibration leakage receipt root mismatch")
        return self


class SemanticAbstentionCase(BaseModel):
    """Evaluator-owned case where the calibrated safe response is explicit abstention."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-abstention-case/v1"] = _ABSTENTION_CASE_SCHEMA
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    revision: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=20_000)
    rubric: SemanticRubricSpec
    candidate_output: str = Field(max_length=100_000)
    tags: frozenset[str] = frozenset()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not tag.strip() for tag in value):
            raise ValueError("semantic abstention tags must be non-empty strings")
        return value

    @property
    def judge_input(self) -> SemanticJudgeInput:
        return SemanticJudgeInput(
            objective=self.objective,
            rubric=self.rubric,
            candidate_output=self.candidate_output,
        )

    @property
    def identity(self) -> str:
        return _domain_root(
            _ABSTENTION_CASE_DOMAIN,
            self.model_dump(mode="json"),
        )


class SemanticAbstentionObservation(BaseModel):
    """Observed judge behavior for an evaluator-owned abstention case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-abstention-observation/v1"] = (
        _ABSTENTION_OBSERVATION_SCHEMA
    )
    case: SemanticAbstentionCase
    response: SemanticJudgeResponse | None = None
    failure_code: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.response is None and self.failure_code is None:
            raise ValueError("failed abstention observation requires failure_code")
        if self.response is not None and self.failure_code is not None:
            raise ValueError("resolved abstention observation cannot carry failure_code")
        if self.response is not None:
            _ = self.observed
        return self

    @property
    def case_identity(self) -> str:
        return self.case.identity

    @property
    def observed(self) -> SemanticDecision | None:
        if self.response is None:
            return None
        return derive_semantic_decision(self.case.rubric, self.response)


class SemanticAbstentionPolicy(BaseModel):
    """Fail-closed policy for explicit abstention calibration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-abstention-policy/v1"] = _ABSTENTION_POLICY_SCHEMA
    min_cases: int = Field(default=10, ge=1, le=10_000, strict=True)
    max_incorrect_resolutions: int = Field(default=0, ge=0, le=10_000, strict=True)
    max_judge_failures: int = Field(default=0, ge=0, le=10_000, strict=True)
    required_tags: frozenset[str] = frozenset()


class _AbstentionMetrics(TypedDict):
    total_cases: int
    abstentions: int
    incorrect_resolutions: int
    judge_failures: int
    covered_tags: tuple[str, ...]
    accepted: bool


class SemanticAbstentionReceipt(BaseModel):
    """Integrity-bound explicit-abstention calibration result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-abstention-receipt/v1"] = (
        _ABSTENTION_RECEIPT_SCHEMA
    )
    policy: SemanticAbstentionPolicy
    observations: tuple[SemanticAbstentionObservation, ...] = Field(min_length=1)
    total_cases: int = Field(ge=1, strict=True)
    abstentions: int = Field(ge=0, strict=True)
    incorrect_resolutions: int = Field(ge=0, strict=True)
    judge_failures: int = Field(ge=0, strict=True)
    covered_tags: tuple[str, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: SemanticAbstentionPolicy,
        observations: tuple[SemanticAbstentionObservation, ...],
    ) -> Self:
        checked_policy = SemanticAbstentionPolicy.model_validate(policy.model_dump(mode="json"))
        checked_observations = tuple(
            SemanticAbstentionObservation.model_validate(item.model_dump(mode="json"))
            for item in observations
        )
        metrics = _abstention_metrics(checked_policy, checked_observations)
        unsigned = {
            "schema_version": _ABSTENTION_RECEIPT_SCHEMA,
            "policy": checked_policy.model_dump(mode="json"),
            "observations": [item.model_dump(mode="json") for item in checked_observations],
            **metrics,
        }
        return cls(
            policy=checked_policy,
            observations=checked_observations,
            receipt_root=_domain_root(_ABSTENTION_RECEIPT_DOMAIN, unsigned),
            **metrics,
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        metrics = _abstention_metrics(self.policy, self.observations)
        for name, expected in metrics.items():
            if getattr(self, name) != expected:
                raise ValueError(f"semantic abstention {name} does not recompute")
        expected_root = _domain_root(
            _ABSTENTION_RECEIPT_DOMAIN,
            self.model_dump(mode="json", exclude={"receipt_root"}),
        )
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("semantic abstention receipt root mismatch")
        return self


def _leakage_metrics(
    policy: CalibrationLeakagePolicy,
    observations: tuple[CalibrationLeakageObservation, ...],
) -> _LeakageMetrics:
    if not observations:
        raise ValueError("calibration leakage receipt requires observations")
    keys = [(item.case_identity, item.probe_kind.value) for item in observations]
    if len(set(keys)) != len(keys):
        raise ValueError("calibration leakage probe observations must be unique per case and kind")
    covered = tuple(sorted({item.probe_kind for item in observations}, key=lambda item: item.value))
    detections = sum(item.detected for item in observations)
    accepted = (
        len(observations) >= policy.min_cases
        and detections <= policy.max_detections
        and policy.required_probe_kinds <= set(covered)
    )
    return {
        "total_cases": len(observations),
        "detections": detections,
        "covered_probe_kinds": covered,
        "accepted": accepted,
    }


def _abstention_metrics(
    policy: SemanticAbstentionPolicy,
    observations: tuple[SemanticAbstentionObservation, ...],
) -> _AbstentionMetrics:
    if not observations:
        raise ValueError("semantic abstention receipt requires observations")
    identities = [item.case_identity for item in observations]
    if len(set(identities)) != len(identities):
        raise ValueError("semantic abstention case identities must be unique")
    abstentions = sum(item.observed is SemanticDecision.ABSTAIN for item in observations)
    incorrect = sum(item.observed in {SemanticDecision.PASS, SemanticDecision.FAIL} for item in observations)
    failures = sum(item.observed is None for item in observations)
    covered_tags = tuple(sorted({tag for item in observations for tag in item.case.tags}))
    accepted = (
        len(observations) >= policy.min_cases
        and incorrect <= policy.max_incorrect_resolutions
        and failures <= policy.max_judge_failures
        and policy.required_tags <= set(covered_tags)
    )
    return {
        "total_cases": len(observations),
        "abstentions": abstentions,
        "incorrect_resolutions": incorrect,
        "judge_failures": failures,
        "covered_tags": covered_tags,
        "accepted": accepted,
    }


def _domain_root(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _canonical_json_bytes(value)).hexdigest()


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
        raise ValueError("semantic adversarial material must be finite JSON-compatible data") from exc


__all__ = [
    "CalibrationLeakageObservation",
    "CalibrationLeakagePolicy",
    "CalibrationLeakageProbeKind",
    "CalibrationLeakageReceipt",
    "PromptInjectionClass",
    "SemanticAbstentionCase",
    "SemanticAbstentionObservation",
    "SemanticAbstentionPolicy",
    "SemanticAbstentionReceipt",
    "SemanticBlindField",
    "SemanticBlindingEnvelope",
    "high_assurance_prompt_injection_requirements",
    "prompt_injection_risk_tag",
    "prompt_injection_tags",
]
