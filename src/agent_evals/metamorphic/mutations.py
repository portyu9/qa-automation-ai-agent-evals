"""Deterministic metamorphic scenario mutation and effectiveness contracts.

Mutation recipes are evaluator-authored declarations of controlled transformations. The framework
does not infer that a transformation is semantics-preserving. Effectiveness keeps BLOCKED distinct
from both killed and survived mutants.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.contracts.models import EvaluationScenario, ScenarioKind

_MUTATION_SPEC_SCHEMA: Literal["agent-evals/metamorphic-mutation-spec/v1"] = (
    "agent-evals/metamorphic-mutation-spec/v1"
)
_MUTATION_RECORD_SCHEMA: Literal["agent-evals/metamorphic-mutation-record/v1"] = (
    "agent-evals/metamorphic-mutation-record/v1"
)
_EFFECTIVENESS_POLICY_SCHEMA: Literal["agent-evals/metamorphic-effectiveness-policy/v1"] = (
    "agent-evals/metamorphic-effectiveness-policy/v1"
)
_EFFECTIVENESS_REPORT_SCHEMA: Literal["agent-evals/metamorphic-effectiveness-report/v1"] = (
    "agent-evals/metamorphic-effectiveness-report/v1"
)
_SPEC_DOMAIN = b"agent-evals/metamorphic-mutation-spec/v1\0"


class MetamorphicMutantResult(StrEnum):
    KILLED = "killed"
    SURVIVED = "survived"
    BLOCKED = "blocked"


class MetamorphicMutationSpec(BaseModel):
    """Evaluator-authored deterministic mutation recipe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/metamorphic-mutation-spec/v1"] = _MUTATION_SPEC_SCHEMA
    mutation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    relation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    mutant_scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    mutant_revision: str = Field(min_length=1, max_length=128)
    objective_suffix: str | None = Field(default=None, min_length=1, max_length=4000)
    initial_state_overlay: dict[str, Any] = Field(default_factory=dict)
    drop_initial_state_keys: tuple[str, ...] = ()
    add_tags: tuple[str, ...] = ()

    @field_validator("drop_initial_state_keys", "add_tags")
    @classmethod
    def canonical_strings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("metamorphic mutation labels must be non-empty strings")
        if len(set(value)) != len(value):
            raise ValueError("metamorphic mutation labels must be unique")
        if value != tuple(sorted(value)):
            raise ValueError("metamorphic mutation labels must be canonically sorted")
        return value

    @field_validator("initial_state_overlay")
    @classmethod
    def finite_overlay(cls, value: dict[str, Any]) -> dict[str, Any]:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def require_transformation(self) -> Self:
        if (
            self.objective_suffix is None
            and not self.initial_state_overlay
            and not self.drop_initial_state_keys
            and not self.add_tags
        ):
            raise ValueError("metamorphic mutation spec requires at least one transformation")
        overlap = set(self.initial_state_overlay) & set(self.drop_initial_state_keys)
        if overlap:
            raise ValueError(f"state keys cannot be both dropped and overlaid: {sorted(overlap)!r}")
        return self

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            _SPEC_DOMAIN + _canonical_json_bytes(self.model_dump(mode="json"))
        ).hexdigest()


class MetamorphicMutationRecord(BaseModel):
    """Binding between one parent scenario, recipe, and generated mutant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/metamorphic-mutation-record/v1"] = (
        _MUTATION_RECORD_SCHEMA
    )
    mutation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    relation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    parent_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    mutant_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    mutation_spec_identity: str = Field(pattern=r"^[0-9a-f]{64}$")


def generate_metamorphic_mutant(
    base: EvaluationScenario,
    spec: MetamorphicMutationSpec,
) -> tuple[EvaluationScenario, MetamorphicMutationRecord]:
    """Apply one explicit recipe and return a revalidated mutant plus binding record."""

    if type(base) is not EvaluationScenario:
        raise ValueError("metamorphic mutation requires an exact EvaluationScenario")
    if type(spec) is not MetamorphicMutationSpec:
        raise ValueError("metamorphic mutation requires an exact MetamorphicMutationSpec")
    checked_base = EvaluationScenario.model_validate_json(base.model_dump_json())
    checked_spec = MetamorphicMutationSpec.model_validate_json(spec.model_dump_json())

    state = dict(checked_base.initial_state)
    for key in checked_spec.drop_initial_state_keys:
        state.pop(key, None)
    state.update(checked_spec.initial_state_overlay)

    objective = checked_base.objective
    if checked_spec.objective_suffix is not None:
        objective = f"{objective}\n{checked_spec.objective_suffix}"

    payload = checked_base.model_dump(mode="json")
    payload.update(
        {
            "scenario_id": checked_spec.mutant_scenario_id,
            "revision": checked_spec.mutant_revision,
            "kind": ScenarioKind.METAMORPHIC.value,
            "objective": objective,
            "initial_state": state,
            "tags": sorted(set(checked_base.tags) | set(checked_spec.add_tags)),
        }
    )
    mutant = EvaluationScenario.model_validate(payload)
    if mutant.identity == checked_base.identity:
        raise ValueError("metamorphic mutation must produce a distinct scenario identity")

    return mutant, MetamorphicMutationRecord(
        mutation_id=checked_spec.mutation_id,
        relation_id=checked_spec.relation_id,
        parent_scenario_identity=checked_base.identity,
        mutant_scenario_identity=mutant.identity,
        mutation_spec_identity=checked_spec.identity,
    )


class MetamorphicMutantOutcome(BaseModel):
    """Observed relation outcome for one generated mutant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mutation: MetamorphicMutationRecord
    result: MetamorphicMutantResult

    @model_validator(mode="after")
    def require_exact_record(self) -> Self:
        if type(self.mutation) is not MetamorphicMutationRecord:
            raise ValueError("mutant outcome requires exact MetamorphicMutationRecord")
        return self


class MetamorphicEffectivenessPolicy(BaseModel):
    """Integer-ratio policy so mutant-kill authority never depends on floating-point rounding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/metamorphic-effectiveness-policy/v1"] = (
        _EFFECTIVENESS_POLICY_SCHEMA
    )
    min_evaluable_mutants: int = Field(default=10, ge=1, le=100_000, strict=True)
    min_kill_numerator: int = Field(default=4, ge=0, le=10_000, strict=True)
    min_kill_denominator: int = Field(default=5, ge=1, le=10_000, strict=True)

    @model_validator(mode="after")
    def validate_ratio(self) -> Self:
        if self.min_kill_numerator > self.min_kill_denominator:
            raise ValueError("minimum kill ratio cannot exceed 1")
        return self


class _EffectivenessMetrics(TypedDict):
    total_mutants: int
    evaluable_mutants: int
    killed: int
    survived: int
    blocked: int
    accepted: bool


class MetamorphicEffectivenessReport(BaseModel):
    """Per-parent mutant-kill sufficient statistics with BLOCKED preserved separately."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/metamorphic-effectiveness-report/v1"] = (
        _EFFECTIVENESS_REPORT_SCHEMA
    )
    parent_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy: MetamorphicEffectivenessPolicy
    outcomes: tuple[MetamorphicMutantOutcome, ...] = Field(min_length=1)
    total_mutants: int = Field(ge=1, strict=True)
    evaluable_mutants: int = Field(ge=0, strict=True)
    killed: int = Field(ge=0, strict=True)
    survived: int = Field(ge=0, strict=True)
    blocked: int = Field(ge=0, strict=True)
    accepted: bool = Field(strict=True)

    @classmethod
    def create(
        cls,
        *,
        policy: MetamorphicEffectivenessPolicy,
        outcomes: tuple[MetamorphicMutantOutcome, ...],
    ) -> Self:
        if type(policy) is not MetamorphicEffectivenessPolicy:
            raise ValueError("metamorphic effectiveness requires exact policy type")
        checked_policy = MetamorphicEffectivenessPolicy.model_validate_json(policy.model_dump_json())
        checked_list: list[MetamorphicMutantOutcome] = []
        for item in outcomes:
            if type(item) is not MetamorphicMutantOutcome:
                raise ValueError("metamorphic effectiveness requires exact outcome values")
            checked_list.append(MetamorphicMutantOutcome.model_validate_json(item.model_dump_json()))
        checked = tuple(checked_list)
        parents = {item.mutation.parent_scenario_identity for item in checked}
        if len(parents) != 1:
            raise ValueError("metamorphic effectiveness report requires exactly one parent scenario")
        parent = next(iter(parents))
        metrics = _effectiveness_metrics(checked_policy, checked)
        return cls(
            parent_scenario_identity=parent,
            policy=checked_policy,
            outcomes=checked,
            **metrics,
        )

    @model_validator(mode="after")
    def verify_metrics(self) -> Self:
        if any(
            item.mutation.parent_scenario_identity != self.parent_scenario_identity
            for item in self.outcomes
        ):
            raise ValueError("metamorphic effectiveness outcome parent mismatch")
        metrics = _effectiveness_metrics(self.policy, self.outcomes)
        for name, expected in metrics.items():
            if getattr(self, name) != expected:
                raise ValueError(f"metamorphic effectiveness {name} does not recompute")
        return self


def _effectiveness_metrics(
    policy: MetamorphicEffectivenessPolicy,
    outcomes: tuple[MetamorphicMutantOutcome, ...],
) -> _EffectivenessMetrics:
    if not outcomes:
        raise ValueError("metamorphic effectiveness requires outcomes")
    mutation_ids = [item.mutation.mutation_id for item in outcomes]
    if len(set(mutation_ids)) != len(mutation_ids):
        raise ValueError("metamorphic effectiveness mutation ids must be unique")
    killed = sum(item.result is MetamorphicMutantResult.KILLED for item in outcomes)
    survived = sum(item.result is MetamorphicMutantResult.SURVIVED for item in outcomes)
    blocked = sum(item.result is MetamorphicMutantResult.BLOCKED for item in outcomes)
    evaluable = killed + survived
    accepted = (
        evaluable >= policy.min_evaluable_mutants
        and killed * policy.min_kill_denominator
        >= evaluable * policy.min_kill_numerator
    )
    return {
        "total_mutants": len(outcomes),
        "evaluable_mutants": evaluable,
        "killed": killed,
        "survived": survived,
        "blocked": blocked,
        "accepted": accepted,
    }


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
        raise ValueError("metamorphic mutation material must be finite JSON-compatible data") from exc


__all__ = [
    "MetamorphicEffectivenessPolicy",
    "MetamorphicEffectivenessReport",
    "MetamorphicMutantOutcome",
    "MetamorphicMutantResult",
    "MetamorphicMutationRecord",
    "MetamorphicMutationSpec",
    "generate_metamorphic_mutant",
]
