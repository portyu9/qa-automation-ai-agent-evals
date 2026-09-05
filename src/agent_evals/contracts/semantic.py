"""Scenario-owned semantic rubric contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_RUBRIC_SCHEMA: Literal["agent-evals/semantic-rubric/v1"] = "agent-evals/semantic-rubric/v1"


class SemanticCriterionSpec(BaseModel):
    """One immutable semantic criterion with an explicit bounded pass threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,63}$")
    description: str = Field(min_length=1, max_length=4_000)
    minimum_score: int = Field(ge=0, le=4, strict=True)

    @field_validator("description")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError(
                "semantic criterion description must not contain surrounding whitespace"
            )
        return value


class SemanticRubricSpec(BaseModel):
    """Content-addressed rubric owned by an exact evaluation scenario revision."""

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
        material = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()
