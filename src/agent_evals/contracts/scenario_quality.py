"""Scenario coverage, semantic duplicate review, and regression-promotion quality contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.contracts.scenario_registry import (
    ScenarioLifecycle,
    ScenarioOrigin,
    ScenarioRegistry,
    ScenarioRegistryEntry,
)

_COVERAGE_SCHEMA: Literal["agent-evals/scenario-coverage-report/v1"] = (
    "agent-evals/scenario-coverage-report/v1"
)
_SEMANTIC_DUPLICATE_SCHEMA: Literal["agent-evals/scenario-semantic-duplicate/v1"] = (
    "agent-evals/scenario-semantic-duplicate/v1"
)
_PROMOTION_SCHEMA: Literal["agent-evals/regression-promotion-proposal/v1"] = (
    "agent-evals/regression-promotion-proposal/v1"
)
_PROMOTION_DOMAIN = b"agent-evals/regression-promotion-proposal/v1\0"


class ScenarioQualitySeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class ScenarioQualityCode(StrEnum):
    TRIVIAL_NO_ORACLE = "trivial-no-oracle"
    TOOL_AUTHORITY_WITH_ZERO_BUDGET = "tool-authority-with-zero-budget"
    HANDOFF_AUTHORITY_WITH_ZERO_BUDGET = "handoff-authority-with-zero-budget"
    RESOURCE_AUTHORITY_WITHOUT_TOOLS = "resource-authority-without-tools"
    IMPOSSIBLE_APPROVAL_BUDGET = "impossible-approval-budget"


class SemanticDuplicateRelation(StrEnum):
    EQUIVALENT = "equivalent"
    NEAR_DUPLICATE = "near-duplicate"
    DISTINCT_AFTER_REVIEW = "distinct-after-review"


class ScenarioQualityFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ScenarioQualityCode
    severity: ScenarioQualitySeverity
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    detail: str = Field(min_length=1, max_length=2000)


class ScenarioCoverageCount(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ScenarioKind
    active_count: int = Field(ge=0, strict=True)
    minimum_required: int = Field(ge=0, strict=True)

    @property
    def satisfied(self) -> bool:
        return self.active_count >= self.minimum_required


class ScenarioCoverageReport(BaseModel):
    """Integer coverage counts for the risk categories required by the benchmark policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/scenario-coverage-report/v1"] = _COVERAGE_SCHEMA
    counts: tuple[ScenarioCoverageCount, ...]
    accepted: bool = Field(strict=True)

    @classmethod
    def create(
        cls,
        registry: ScenarioRegistry,
        *,
        minimums: dict[ScenarioKind, int] | None = None,
    ) -> Self:
        checked = _revalidate_registry(registry)
        required = minimums or {
            ScenarioKind.CAPABILITY: 1,
            ScenarioKind.SECURITY: 1,
            ScenarioKind.RESILIENCE: 1,
            ScenarioKind.METAMORPHIC: 1,
        }
        if any(value < 0 for value in required.values()):
            raise ValueError("scenario coverage minima must be non-negative")
        counts = tuple(
            ScenarioCoverageCount(
                kind=kind,
                active_count=sum(
                    entry.scenario_kind is kind and entry.lifecycle is ScenarioLifecycle.ACTIVE
                    for entry in checked.entries
                ),
                minimum_required=required[kind],
            )
            for kind in sorted(required, key=lambda item: item.value)
        )
        return cls(counts=counts, accepted=all(item.satisfied for item in counts))

    @model_validator(mode="after")
    def verify_acceptance(self) -> Self:
        if self.accepted != all(item.satisfied for item in self.counts):
            raise ValueError("scenario coverage acceptance does not recompute")
        kinds = tuple(item.kind.value for item in self.counts)
        if len(set(kinds)) != len(kinds):
            raise ValueError("scenario coverage kinds must be unique")
        if kinds != tuple(sorted(kinds)):
            raise ValueError("scenario coverage kinds must be canonically sorted")
        return self


class ScenarioSemanticDuplicateDeclaration(BaseModel):
    """Evaluator-reviewed semantic duplicate declaration; never inferred from hashes alone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/scenario-semantic-duplicate/v1"] = (
        _SEMANTIC_DUPLICATE_SCHEMA
    )
    left_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    right_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    relation: SemanticDuplicateRelation
    reviewer: str = Field(min_length=1, max_length=256)
    review_revision: str = Field(min_length=1, max_length=128)
    rationale_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_canonical_pair(self) -> Self:
        if self.left_scenario_identity >= self.right_scenario_identity:
            raise ValueError("semantic duplicate identities must be distinct and canonical")
        if (
            self.reviewer != self.reviewer.strip()
            or self.review_revision != self.review_revision.strip()
        ):
            raise ValueError("semantic duplicate review metadata must be trimmed")
        return self


class ScenarioSemanticDuplicateFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    relation: SemanticDuplicateRelation
    severity: ScenarioQualitySeverity
    left_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    right_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")


class RegressionPromotionProposal(BaseModel):
    """Integrity-bound proposal connecting a derived regression to parent failure evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/regression-promotion-proposal/v1"] = _PROMOTION_SCHEMA
    promoted_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: ScenarioOrigin
    source_trial_id: str = Field(min_length=1, max_length=512)
    source_evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_registry(
        cls,
        registry: ScenarioRegistry,
        *,
        promoted_scenario_identity: str,
    ) -> Self:
        checked = _revalidate_registry(registry)
        by_identity = {entry.scenario_identity: entry for entry in checked.entries}
        try:
            entry = by_identity[promoted_scenario_identity]
        except KeyError as exc:
            raise ValueError("promoted scenario is absent from registry") from exc
        _validate_promotion_entry(entry)
        provenance = entry.provenance
        assert provenance.parent_scenario_identity is not None
        assert provenance.source_trial_id is not None
        assert provenance.source_evidence_root is not None
        unsigned = {
            "schema_version": _PROMOTION_SCHEMA,
            "promoted_scenario_identity": entry.scenario_identity,
            "parent_scenario_identity": provenance.parent_scenario_identity,
            "origin": provenance.origin.value,
            "source_trial_id": provenance.source_trial_id,
            "source_evidence_root": provenance.source_evidence_root,
        }
        return cls(
            promoted_scenario_identity=entry.scenario_identity,
            parent_scenario_identity=provenance.parent_scenario_identity,
            origin=provenance.origin,
            source_trial_id=provenance.source_trial_id,
            source_evidence_root=provenance.source_evidence_root,
            proposal_root=_domain_root(_PROMOTION_DOMAIN, unsigned),
        )

    @model_validator(mode="after")
    def verify_root(self) -> Self:
        if self.origin not in {ScenarioOrigin.COUNTEREXAMPLE, ScenarioOrigin.MINIMIZED_FAILURE}:
            raise ValueError(
                "regression promotion requires counterexample or minimized-failure origin"
            )
        expected = _domain_root(
            _PROMOTION_DOMAIN,
            self.model_dump(mode="json", exclude={"proposal_root"}),
        )
        if not hmac.compare_digest(expected, self.proposal_root):
            raise ValueError("regression promotion proposal root mismatch")
        return self


def lint_scenario_contracts(
    scenarios: tuple[EvaluationScenario, ...],
) -> tuple[ScenarioQualityFinding, ...]:
    """Return deterministic quality findings over revalidated raw scenario contracts."""

    checked: list[EvaluationScenario] = []
    for scenario in scenarios:
        if type(scenario) is not EvaluationScenario:
            raise ValueError("scenario quality lint requires exact EvaluationScenario objects")
        checked.append(EvaluationScenario.model_validate(scenario.model_dump(mode="json")))
    identities = [scenario.identity for scenario in checked]
    if len(set(identities)) != len(identities):
        raise ValueError("scenario quality lint requires unique scenario identities")

    findings: list[ScenarioQualityFinding] = []
    for scenario in checked:
        no_oracle = (
            not scenario.required_outcomes
            and not scenario.forbidden_outcomes
            and scenario.approval_intent is None
            and scenario.semantic_rubric is None
            and scenario.retrieval is None
            and scenario.side_effect_idempotency is None
        )
        if no_oracle:
            findings.append(
                _finding(
                    scenario,
                    ScenarioQualityCode.TRIVIAL_NO_ORACLE,
                    ScenarioQualitySeverity.ERROR,
                    "scenario has no deterministic or explicitly subordinate evaluation oracle",
                )
            )
        if scenario.authority.allowed_tools and scenario.authority.max_tool_calls == 0:
            findings.append(
                _finding(
                    scenario,
                    ScenarioQualityCode.TOOL_AUTHORITY_WITH_ZERO_BUDGET,
                    ScenarioQualitySeverity.ERROR,
                    "scenario grants tools while the root tool-call budget is zero",
                )
            )
        if scenario.authority.handoff_grants and scenario.authority.max_handoffs == 0:
            findings.append(
                _finding(
                    scenario,
                    ScenarioQualityCode.HANDOFF_AUTHORITY_WITH_ZERO_BUDGET,
                    ScenarioQualitySeverity.ERROR,
                    "scenario grants handoff transitions while the handoff budget is zero",
                )
            )
        if scenario.authority.allowed_resource_scopes and not scenario.authority.allowed_tools:
            findings.append(
                _finding(
                    scenario,
                    ScenarioQualityCode.RESOURCE_AUTHORITY_WITHOUT_TOOLS,
                    ScenarioQualitySeverity.WARNING,
                    "scenario grants resource scopes but no root tools can consume them",
                )
            )
        if scenario.approval_intent is not None and scenario.authority.max_tool_calls == 0:
            findings.append(
                _finding(
                    scenario,
                    ScenarioQualityCode.IMPOSSIBLE_APPROVAL_BUDGET,
                    ScenarioQualitySeverity.ERROR,
                    "approval intent cannot be exercised with a zero tool-call budget",
                )
            )

    return tuple(
        sorted(
            findings,
            key=lambda item: (item.severity.value, item.code.value, item.scenario_identity),
        )
    )


def require_scenario_contract_quality(scenarios: tuple[EvaluationScenario, ...]) -> None:
    errors = [
        item
        for item in lint_scenario_contracts(scenarios)
        if item.severity is ScenarioQualitySeverity.ERROR
    ]
    if errors:
        codes = ",".join(sorted({item.code.value for item in errors}))
        raise ValueError(f"scenario contract quality errors: {codes}")


def lint_semantic_duplicate_declarations(
    registry: ScenarioRegistry,
    declarations: tuple[ScenarioSemanticDuplicateDeclaration, ...],
) -> tuple[ScenarioSemanticDuplicateFinding, ...]:
    """Validate reviewer-owned semantic dedup declarations against one exact registry."""

    checked_registry = _revalidate_registry(registry)
    identities = {entry.scenario_identity for entry in checked_registry.entries}
    checked_list: list[ScenarioSemanticDuplicateDeclaration] = []
    for item in declarations:
        if type(item) is not ScenarioSemanticDuplicateDeclaration:
            raise ValueError(
                "semantic duplicate review requires exact ScenarioSemanticDuplicateDeclaration"
            )
        checked_list.append(
            ScenarioSemanticDuplicateDeclaration.model_validate_json(item.model_dump_json())
        )
    checked = tuple(checked_list)
    pairs = [(item.left_scenario_identity, item.right_scenario_identity) for item in checked]
    if len(set(pairs)) != len(pairs):
        raise ValueError("semantic duplicate declarations must have unique scenario pairs")
    for item in checked:
        if (
            item.left_scenario_identity not in identities
            or item.right_scenario_identity not in identities
        ):
            raise ValueError("semantic duplicate declaration references scenario outside registry")

    findings = [
        ScenarioSemanticDuplicateFinding(
            relation=item.relation,
            severity=(
                ScenarioQualitySeverity.ERROR
                if item.relation is SemanticDuplicateRelation.EQUIVALENT
                else ScenarioQualitySeverity.WARNING
            ),
            left_scenario_identity=item.left_scenario_identity,
            right_scenario_identity=item.right_scenario_identity,
        )
        for item in checked
        if item.relation is not SemanticDuplicateRelation.DISTINCT_AFTER_REVIEW
    ]
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.severity.value,
                item.relation.value,
                item.left_scenario_identity,
                item.right_scenario_identity,
            ),
        )
    )


def require_no_semantic_duplicates(
    registry: ScenarioRegistry,
    declarations: tuple[ScenarioSemanticDuplicateDeclaration, ...],
) -> None:
    errors = [
        item
        for item in lint_semantic_duplicate_declarations(registry, declarations)
        if item.severity is ScenarioQualitySeverity.ERROR
    ]
    if errors:
        raise ValueError("scenario corpus contains reviewer-confirmed semantic duplicates")



def _revalidate_registry(value: ScenarioRegistry) -> ScenarioRegistry:
    if type(value) is not ScenarioRegistry:
        raise ValueError("scenario quality requires exact ScenarioRegistry")
    return ScenarioRegistry.model_validate_json(value.model_dump_json())


def _validate_promotion_entry(entry: ScenarioRegistryEntry) -> None:
    if entry.scenario_kind is not ScenarioKind.REGRESSION:
        raise ValueError("promoted fixture must be registered as a regression scenario")
    provenance = entry.provenance
    if provenance.origin not in {ScenarioOrigin.COUNTEREXAMPLE, ScenarioOrigin.MINIMIZED_FAILURE}:
        raise ValueError("regression promotion requires derived failure provenance")
    if (
        provenance.parent_scenario_identity is None
        or provenance.source_trial_id is None
        or provenance.source_evidence_root is None
    ):
        raise ValueError("regression promotion requires parent scenario, trial, and evidence root")


def _finding(
    scenario: EvaluationScenario,
    code: ScenarioQualityCode,
    severity: ScenarioQualitySeverity,
    detail: str,
) -> ScenarioQualityFinding:
    return ScenarioQualityFinding(
        code=code,
        severity=severity,
        scenario_identity=scenario.identity,
        detail=detail,
    )


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
        raise ValueError("scenario quality material must be finite JSON-compatible data") from exc


__all__ = [
    "RegressionPromotionProposal",
    "ScenarioCoverageCount",
    "ScenarioCoverageReport",
    "ScenarioQualityCode",
    "ScenarioQualityFinding",
    "ScenarioQualitySeverity",
    "ScenarioSemanticDuplicateDeclaration",
    "ScenarioSemanticDuplicateFinding",
    "SemanticDuplicateRelation",
    "lint_scenario_contracts",
    "lint_semantic_duplicate_declarations",
    "require_no_semantic_duplicates",
    "require_scenario_contract_quality",
]
