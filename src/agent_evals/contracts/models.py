"""Immutable contracts for the evaluated subject, scenario, and authority boundary."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScenarioKind(StrEnum):
    CAPABILITY = "capability"
    REGRESSION = "regression"
    SECURITY = "security"
    RESILIENCE = "resilience"
    METAMORPHIC = "metamorphic"


class ApprovalDecision(StrEnum):
    """Evaluator-owned decision for one exact native approval interruption."""

    APPROVE = "approve"
    REJECT = "reject"


class ApprovalIntentSpec(BaseModel):
    """Scenario-bound target and decision for one exact approval interruption.

    Runtime call identity, arguments, resource, and handoff epoch are intentionally absent here:
    they are observations that must be bound by evidence rather than values the scenario invents.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: str = Field(min_length=1, max_length=256)
    tool: str = Field(min_length=1, max_length=256)
    decision: ApprovalDecision

    @field_validator("agent", "tool")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("approval intent identities must not contain surrounding whitespace")
        return value


class SubjectFingerprint(BaseModel):
    """Content-addressed identity for the full agent system under evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    application_revision: str = Field(min_length=1)
    instructions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)

    @classmethod
    def from_material(
        cls,
        *,
        provider: str,
        model: str,
        application_revision: str,
        instructions: str,
        tool_schema: Any,
        policy: Any,
        memory_policy: Any,
        adapter: str,
        adapter_version: str,
    ) -> SubjectFingerprint:
        return cls(
            provider=provider,
            model=model,
            application_revision=application_revision,
            instructions_sha256=_sha256_text(instructions),
            tool_schema_sha256=_sha256_json(tool_schema),
            policy_sha256=_sha256_json(policy),
            memory_policy_sha256=_sha256_json(memory_policy),
            adapter=adapter,
            adapter_version=adapter_version,
        )

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python", exclude_none=True))


class HandoffAuthorityGrant(BaseModel):
    """Directed authority granted to one agent after one exact handoff transition.

    A grant may preserve or reduce tool/resource/budget authority and may add approval
    requirements. It never removes constraints inherited from the source authority.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_agent: str = Field(min_length=1, max_length=256)
    target_agent: str = Field(min_length=1, max_length=256)
    allowed_tools: frozenset[str] = frozenset()
    allowed_resource_prefixes: tuple[str, ...] = ()
    additional_approval_required_tools: frozenset[str] = frozenset()
    max_tool_calls: int = Field(default=32, ge=0, le=10_000, strict=True)
    max_handoffs: int = Field(default=8, ge=0, le=1_000, strict=True)

    @field_validator("source_agent", "target_agent")
    @classmethod
    def validate_agent_identity(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("agent identities must not contain surrounding whitespace")
        return value

    @field_validator("allowed_tools", "additional_approval_required_tools")
    @classmethod
    def reject_empty_tool_names(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not name.strip() for name in value):
            raise ValueError("tool identities must be non-empty strings")
        return value

    @field_validator("allowed_resource_prefixes")
    @classmethod
    def canonicalize_resource_prefixes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_resource_prefixes(value)

    @model_validator(mode="after")
    def validate_grant(self) -> HandoffAuthorityGrant:
        if self.source_agent == self.target_agent:
            raise ValueError("handoff authority must transfer to a distinct target agent")
        if not self.additional_approval_required_tools <= self.allowed_tools:
            missing = self.additional_approval_required_tools - self.allowed_tools
            raise ValueError(
                f"additional approval-required tools must also be delegated: {sorted(missing)!r}"
            )
        return self

    @property
    def transition(self) -> tuple[str, str]:
        return (self.source_agent, self.target_agent)

    def authorizes_tool(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools

    def authorizes_resource(self, resource: str) -> bool:
        return any(resource.startswith(prefix) for prefix in self.allowed_resource_prefixes)


class AuthorityPolicy(BaseModel):
    """Fail-closed authority granted to the evaluated agent for one scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_tools: frozenset[str] = frozenset()
    forbidden_tools: frozenset[str] = frozenset()
    approval_required_tools: frozenset[str] = frozenset()
    allowed_resource_prefixes: tuple[str, ...] = ()
    max_turns: int = Field(default=16, ge=1, le=10_000, strict=True)
    max_tool_calls: int = Field(default=32, ge=0, le=10_000, strict=True)
    max_handoffs: int = Field(default=8, ge=0, le=1_000, strict=True)
    root_agent: str | None = Field(default=None, min_length=1, max_length=256)
    handoff_grants: tuple[HandoffAuthorityGrant, ...] = ()

    @field_validator("allowed_tools", "forbidden_tools", "approval_required_tools")
    @classmethod
    def reject_empty_tool_names(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not name.strip() for name in value):
            raise ValueError("tool identities must be non-empty strings")
        return value

    @field_validator("allowed_resource_prefixes")
    @classmethod
    def canonicalize_resource_prefixes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_resource_prefixes(value)

    @field_validator("root_agent")
    @classmethod
    def validate_root_agent(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("root agent identity must not contain surrounding whitespace")
        return value

    @field_validator("handoff_grants")
    @classmethod
    def canonicalize_handoff_grants(
        cls,
        value: tuple[HandoffAuthorityGrant, ...],
    ) -> tuple[HandoffAuthorityGrant, ...]:
        return tuple(sorted(value, key=lambda grant: grant.transition))

    @model_validator(mode="after")
    def validate_authority(self) -> AuthorityPolicy:
        overlap = self.allowed_tools & self.forbidden_tools
        if overlap:
            raise ValueError(f"tools cannot be both allowed and forbidden: {sorted(overlap)!r}")
        if not self.approval_required_tools <= self.allowed_tools:
            missing = self.approval_required_tools - self.allowed_tools
            raise ValueError(f"approval-required tools must also be allowed: {sorted(missing)!r}")

        if self.handoff_grants and self.root_agent is None:
            raise ValueError("handoff authority grants require an exact root_agent identity")

        transitions = [grant.transition for grant in self.handoff_grants]
        if len(set(transitions)) != len(transitions):
            raise ValueError("handoff authority transitions must be unique")

        for grant in self.handoff_grants:
            if not grant.allowed_tools <= self.allowed_tools:
                widened = grant.allowed_tools - self.allowed_tools
                raise ValueError(
                    f"handoff grant tools must remain within root authority: {sorted(widened)!r}"
                )
            if grant.max_tool_calls > self.max_tool_calls:
                raise ValueError("handoff grant tool budget cannot exceed root tool budget")
            if grant.max_handoffs > self.max_handoffs:
                raise ValueError("handoff grant handoff budget cannot exceed root handoff budget")
            for prefix in grant.allowed_resource_prefixes:
                if not self.authorizes_resource(prefix):
                    raise ValueError(
                        "handoff grant resource scope must remain within root resource authority: "
                        f"{prefix!r}"
                    )

        if self.root_agent is not None and self.handoff_grants:
            reachable = {self.root_agent}
            pending = list(self.handoff_grants)
            while pending:
                progressed = False
                remaining: list[HandoffAuthorityGrant] = []
                for grant in pending:
                    if grant.source_agent in reachable:
                        reachable.add(grant.target_agent)
                        progressed = True
                    else:
                        remaining.append(grant)
                if not progressed:
                    unreachable = sorted(
                        f"{grant.source_agent}->{grant.target_agent}" for grant in remaining
                    )
                    raise ValueError(
                        "handoff authority graph contains transitions unreachable from root_agent: "
                        f"{unreachable!r}"
                    )
                pending = remaining
        return self

    @property
    def has_handoff_authority(self) -> bool:
        return self.root_agent is not None or bool(self.handoff_grants)

    def handoff_grant(
        self,
        source_agent: str,
        target_agent: str,
    ) -> HandoffAuthorityGrant | None:
        for grant in self.handoff_grants:
            if grant.source_agent == source_agent and grant.target_agent == target_agent:
                return grant
        return None

    def authorizes_tool(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools and tool_name not in self.forbidden_tools

    def authorizes_resource(self, resource: str) -> bool:
        return any(resource.startswith(prefix) for prefix in self.allowed_resource_prefixes)


class EvaluationScenario(BaseModel):
    """Versioned scenario contract; a trial is invalid when its contract drifts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    revision: str = Field(min_length=1)
    kind: ScenarioKind
    objective: str = Field(min_length=1, max_length=20_000)
    initial_state: dict[str, Any] = Field(default_factory=dict)
    authority: AuthorityPolicy = Field(default_factory=AuthorityPolicy)
    approval_intent: ApprovalIntentSpec | None = None
    required_outcomes: dict[str, Any] = Field(default_factory=dict)
    forbidden_outcomes: dict[str, Any] = Field(default_factory=dict)
    tags: frozenset[str] = frozenset()

    @field_validator("initial_state", "required_outcomes", "forbidden_outcomes")
    @classmethod
    def require_json_serializable(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("scenario state/outcomes must be finite JSON-compatible data") from exc
        return value

    @field_validator("tags")
    @classmethod
    def reject_empty_tags(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not tag.strip() for tag in value):
            raise ValueError("scenario tags must be non-empty strings")
        return value

    @model_validator(mode="after")
    def validate_scenario(self) -> EvaluationScenario:
        conflicts = {
            key
            for key, expected in self.required_outcomes.items()
            if key in self.forbidden_outcomes and self.forbidden_outcomes[key] == expected
        }
        if conflicts:
            raise ValueError(
                f"outcomes cannot be simultaneously required and forbidden: {sorted(conflicts)!r}"
            )
        if self.approval_intent is not None and not self.authority.authorizes_tool(
            self.approval_intent.tool
        ):
            raise ValueError("approval intent target tool must be inside root scenario authority")
        return self

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python", exclude_none=True))


def _canonical_resource_prefixes(value: tuple[str, ...]) -> tuple[str, ...]:
    if any(not prefix.strip() for prefix in value):
        raise ValueError("resource prefixes must be non-empty strings")
    return tuple(sorted(set(value)))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return _sha256_text(canonical)


def _canonicalize(value: Any) -> Any:
    """Convert supported contract material into deterministic JSON-compatible structure."""
    if isinstance(value, BaseModel):
        return _canonicalize(value.model_dump(mode="python", exclude_none=True))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(
                "contract JSON object keys must be strings to preserve unambiguous identity"
            )
        return {key: _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        normalized = [_canonicalize(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item, sort_keys=True, separators=(",", ":"), allow_nan=False
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value
