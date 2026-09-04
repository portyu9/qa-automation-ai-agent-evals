"""Content-addressed contracts for subordinate semantic evaluation."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_RUBRIC_SCHEMA: Literal["agent-evals/semantic-rubric/v1"] = "agent-evals/semantic-rubric/v1"
_RESPONSE_SCHEMA: Literal["agent-evals/semantic-judge-response/v1"] = (
    "agent-evals/semantic-judge-response/v1"
)
_PROFILE_SCHEMA: Literal["agent-evals/semantic-judge-profile/v1"] = (
    "agent-evals/semantic-judge-profile/v1"
)
_INPUT_SCHEMA: Literal["agent-evals/semantic-judge-input/v1"] = (
    "agent-evals/semantic-judge-input/v1"
)


class SemanticDecision(StrEnum):
    """Bounded semantic outcome; ABSTAIN represents evaluator uncertainty, not subject failure."""

    PASS = "pass"  # nosec B105
    FAIL = "fail"
    ABSTAIN = "abstain"


class SemanticCriterionSpec(BaseModel):
    """One scenario-owned semantic criterion with an explicit pass threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")
    description: str = Field(min_length=1, max_length=4_000)
    minimum_score: int = Field(ge=0, le=4, strict=True)

    @field_validator("description")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("semantic criterion description must not contain surrounding whitespace")
        return value


class SemanticRubricSpec(BaseModel):
    """Immutable scenario-owned rubric whose identity changes when any criterion changes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-rubric/v1"] = _RUBRIC_SCHEMA
    rubric_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    revision: str = Field(min_length=1, max_length=128)
    criteria: tuple[SemanticCriterionSpec, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_unique_criteria(self) -> Self:
        identities = [criterion.criterion_id for criterion in self.criteria]
        if len(set(identities)) != len(identities):
            raise ValueError("semantic rubric criterion IDs must be unique")
        return self

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="json"))


class SemanticCriterionResult(BaseModel):
    """One bounded judge result; free-form reasoning is intentionally absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")
    decision: SemanticDecision
    score: int | None = Field(default=None, ge=0, le=4, strict=True)

    @model_validator(mode="after")
    def validate_score_shape(self) -> Self:
        if self.decision is SemanticDecision.ABSTAIN:
            if self.score is not None:
                raise ValueError("abstaining semantic criterion must not carry a score")
        elif self.score is None:
            raise ValueError("resolved semantic criterion requires an integer score")
        return self


class SemanticJudgeResponse(BaseModel):
    """Strict structured response accepted from one semantic judge invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-judge-response/v1"] = _RESPONSE_SCHEMA
    criteria: tuple[SemanticCriterionResult, ...] = Field(min_length=1, max_length=32)
    overall: SemanticDecision

    @model_validator(mode="after")
    def validate_unique_criteria(self) -> Self:
        identities = [result.criterion_id for result in self.criteria]
        if len(set(identities)) != len(identities):
            raise ValueError("semantic judge response criterion IDs must be unique")
        return self

    @property
    def digest(self) -> str:
        return _sha256_json(self.model_dump(mode="json"))


class SemanticJudgeProfile(BaseModel):
    """Content-addressed identity for behavior-bearing semantic judge configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-judge-profile/v1"] = _PROFILE_SCHEMA
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    model_revision: str = Field(min_length=1, max_length=256)
    adapter: str = Field(min_length=1, max_length=256)
    adapter_version: str = Field(min_length=1, max_length=128)
    prompt_template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_schema: str = Field(min_length=1, max_length=256)
    behavior_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_material(
        cls,
        *,
        provider: str,
        model: str,
        model_revision: str,
        adapter: str,
        adapter_version: str,
        prompt_template: str,
        response_schema: str = _RESPONSE_SCHEMA,
        behavior_config: Any,
    ) -> Self:
        return cls(
            provider=provider,
            model=model,
            model_revision=model_revision,
            adapter=adapter,
            adapter_version=adapter_version,
            prompt_template_sha256=_sha256_text(prompt_template),
            response_schema=response_schema,
            behavior_config_sha256=_sha256_json(behavior_config),
        )

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="json"))


class SemanticJudgeInput(BaseModel):
    """Bounded canonical projection exposed to a semantic judge.

    The evaluator intentionally does not include arbitrary evidence events, tool payloads, approval
    material, credentials, or environment state in this default projection.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-judge-input/v1"] = _INPUT_SCHEMA
    objective: str = Field(min_length=1, max_length=20_000)
    rubric: SemanticRubricSpec
    candidate_output: str = Field(max_length=100_000)

    @property
    def digest(self) -> str:
        return _sha256_json(self.model_dump(mode="json"))


def derive_semantic_decision(
    rubric: SemanticRubricSpec,
    response: SemanticJudgeResponse,
) -> SemanticDecision:
    """Revalidate exact criterion identity/order and derive the only accepted overall verdict."""
    expected_ids = tuple(criterion.criterion_id for criterion in rubric.criteria)
    observed_ids = tuple(result.criterion_id for result in response.criteria)
    if observed_ids != expected_ids:
        raise ValueError(
            "semantic judge response criteria must exactly match rubric criterion identity and order"
        )

    decisions: list[SemanticDecision] = []
    for criterion, result in zip(rubric.criteria, response.criteria, strict=True):
        if result.decision is SemanticDecision.ABSTAIN:
            decisions.append(SemanticDecision.ABSTAIN)
            continue
        if result.score is None:  # defensive guard after model validation
            raise ValueError("resolved semantic criterion is missing its score")
        expected = (
            SemanticDecision.PASS
            if result.score >= criterion.minimum_score
            else SemanticDecision.FAIL
        )
        if result.decision is not expected:
            raise ValueError(
                f"semantic criterion {criterion.criterion_id!r} decision contradicts its score"
            )
        decisions.append(expected)

    derived = (
        SemanticDecision.FAIL
        if SemanticDecision.FAIL in decisions
        else SemanticDecision.ABSTAIN
        if SemanticDecision.ABSTAIN in decisions
        else SemanticDecision.PASS
    )
    if response.overall is not derived:
        raise ValueError("semantic judge overall decision contradicts criterion results")
    return derived


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    try:
        material = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("semantic contract material must be finite JSON-compatible data") from exc
    return hashlib.sha256(material).hexdigest()
