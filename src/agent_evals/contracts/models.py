"""Immutable contracts for the evaluated subject, scenario, and authority boundary."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.contracts.resource import ResourceIdentifier, ResourceScope
from agent_evals.contracts.semantic import SemanticRubricSpec
from agent_evals.retrieval.models import RetrievalContractSpec
from agent_evals.side_effect.models import SideEffectIdempotencySpec

_MAX_CANONICAL_DEPTH = 32
_MAX_CANONICAL_NODES = 100_000
_MAX_CANONICAL_COLLECTION_ITEMS = 10_000
_MAX_CANONICAL_SCALAR_UTF8_BYTES = 1 * 1024 * 1024
_MAX_CANONICAL_JSON_BYTES = 4 * 1024 * 1024
_MAX_TEXT_HASH_BYTES = 4 * 1024 * 1024
_MAX_CANONICAL_INTEGER_BITS = 4_096


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

    def snapshot(self) -> SubjectFingerprint:
        """Return a detached, revalidated copy for one runtime boundary."""
        return SubjectFingerprint.model_validate_json(self.model_dump_json())


class HandoffAuthorityGrant(BaseModel):
    """Directed authority granted to one agent after one exact handoff transition.

    A grant may preserve or reduce tool/resource/budget authority and may add approval
    requirements. It never removes constraints inherited from the source authority.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_agent: str = Field(min_length=1, max_length=256)
    target_agent: str = Field(min_length=1, max_length=256)
    allowed_tools: frozenset[str] = frozenset()
    allowed_resource_scopes: tuple[ResourceScope, ...] = ()
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

    @field_validator("allowed_resource_scopes")
    @classmethod
    def canonicalize_resource_scopes(
        cls,
        value: tuple[ResourceScope, ...],
    ) -> tuple[ResourceScope, ...]:
        return _canonical_resource_scopes(value)

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

    def authorizes_resource(self, resource: ResourceIdentifier) -> bool:
        return any(scope.contains_identifier(resource) for scope in self.allowed_resource_scopes)


class AuthorityPolicy(BaseModel):
    """Fail-closed authority granted to the evaluated agent for one scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_tools: frozenset[str] = frozenset()
    forbidden_tools: frozenset[str] = frozenset()
    approval_required_tools: frozenset[str] = frozenset()
    allowed_resource_scopes: tuple[ResourceScope, ...] = ()
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

    @field_validator("allowed_resource_scopes")
    @classmethod
    def canonicalize_resource_scopes(
        cls,
        value: tuple[ResourceScope, ...],
    ) -> tuple[ResourceScope, ...]:
        return _canonical_resource_scopes(value)

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
        if len(value) > _MAX_CANONICAL_COLLECTION_ITEMS:
            raise ValueError(
                "handoff authority grants exceed the contract collection complexity ceiling"
            )
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
            for scope in grant.allowed_resource_scopes:
                if not any(parent.contains_scope(scope) for parent in self.allowed_resource_scopes):
                    raise ValueError(
                        "handoff grant resource scope must remain within root resource authority: "
                        f"{scope.canonical_json}"
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

    def authorizes_resource(self, resource: ResourceIdentifier) -> bool:
        return any(scope.contains_identifier(resource) for scope in self.allowed_resource_scopes)


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
    semantic_rubric: SemanticRubricSpec | None = None
    retrieval: RetrievalContractSpec | None = None
    side_effect_idempotency: SideEffectIdempotencySpec | None = None
    required_outcomes: dict[str, Any] = Field(default_factory=dict)
    forbidden_outcomes: dict[str, Any] = Field(default_factory=dict)
    tags: frozenset[str] = frozenset()

    @field_validator("initial_state", "required_outcomes", "forbidden_outcomes")
    @classmethod
    def require_json_serializable(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canonical_material(value)
        try:
            canonical = json.dumps(
                value, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("scenario state/outcomes must be finite JSON-compatible data") from exc
        _require_canonical_json_size(canonical)
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

        spec = self.approval_intent
        if spec is not None:
            if not self.authority.authorizes_tool(spec.tool):
                raise ValueError(
                    "approval intent target tool must be inside root scenario authority"
                )
            if not _agent_path_requires_approval(self.authority, agent=spec.agent, tool=spec.tool):
                raise ValueError(
                    "approval intent target must be approval-required on at least one configured "
                    "authority path to that agent"
                )
        return self

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python", exclude_none=True))

    def snapshot(self) -> EvaluationScenario:
        """Return a detached, revalidated copy for one runtime boundary."""
        return EvaluationScenario.model_validate_json(self.model_dump_json())


def _agent_path_requires_approval(policy: AuthorityPolicy, *, agent: str, tool: str) -> bool:
    root_required = tool in policy.approval_required_tools
    if not policy.has_handoff_authority:
        return root_required
    if policy.root_agent == agent:
        return root_required
    if policy.root_agent is None:
        return False

    pending: list[tuple[str, bool]] = [(policy.root_agent, root_required)]
    visited: set[tuple[str, bool]] = set()
    while pending:
        source, required = pending.pop()
        state = (source, required)
        if state in visited:
            continue
        visited.add(state)
        for grant in policy.handoff_grants:
            if grant.source_agent != source or tool not in grant.allowed_tools:
                continue
            child_required = required or tool in grant.additional_approval_required_tools
            if grant.target_agent == agent and child_required:
                return True
            pending.append((grant.target_agent, child_required))
    return False


def _canonical_resource_scopes(value: tuple[ResourceScope, ...]) -> tuple[ResourceScope, ...]:
    if len(value) > _MAX_CANONICAL_COLLECTION_ITEMS:
        raise ValueError("resource scopes exceed the contract collection complexity ceiling")
    canonical = {scope.canonical_json: scope for scope in value}
    return tuple(canonical[key] for key in sorted(canonical))


def _sha256_text(value: str) -> str:
    encoded = _bounded_utf8_bytes(value, limit=_MAX_TEXT_HASH_BYTES, label="hashed text")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_json(value: Any) -> str:
    _validate_canonical_material(value)
    canonical = json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    encoded = _require_canonical_json_size(canonical)
    return hashlib.sha256(encoded).hexdigest()


def _validate_canonical_material(value: Any) -> None:
    """Fail before recursive serialization when contract material exceeds safe work ceilings."""
    nodes = 0
    scalar_bytes = 0
    active_containers: set[int] = set()
    stack: list[tuple[Any, int, bool]] = [(value, 0, False)]

    while stack:
        current, depth, exiting = stack.pop()
        if exiting:
            active_containers.remove(id(current))
            continue

        nodes += 1
        if nodes > _MAX_CANONICAL_NODES:
            raise ValueError("contract material exceeds the canonical node complexity ceiling")
        if depth > _MAX_CANONICAL_DEPTH:
            raise ValueError("contract material exceeds the canonical nesting depth ceiling")

        if isinstance(current, BaseModel):
            stack.append((current.model_dump(mode="python", exclude_none=True), depth, False))
            continue

        if isinstance(current, str):
            scalar_bytes += len(
                _bounded_utf8_bytes(
                    current,
                    limit=_MAX_CANONICAL_SCALAR_UTF8_BYTES,
                    label="contract string",
                )
            )
            if scalar_bytes > _MAX_CANONICAL_SCALAR_UTF8_BYTES:
                raise ValueError("contract material exceeds the canonical scalar-byte ceiling")
            continue

        if isinstance(current, bool) or current is None:
            continue
        if isinstance(current, int):
            if current.bit_length() > _MAX_CANONICAL_INTEGER_BITS:
                raise ValueError("contract integer exceeds the canonical integer-size ceiling")
            continue
        if isinstance(current, float):
            if not isfinite(current):
                raise ValueError("contract material requires finite floating-point values")
            continue

        if isinstance(current, dict):
            if len(current) > _MAX_CANONICAL_COLLECTION_ITEMS:
                raise ValueError("contract object exceeds the canonical collection-size ceiling")
            container_id = id(current)
            if container_id in active_containers:
                raise ValueError("contract material must not contain reference cycles")
            active_containers.add(container_id)
            stack.append((current, depth, True))
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError(
                        "contract JSON object keys must be strings to preserve unambiguous identity"
                    )
                scalar_bytes += len(
                    _bounded_utf8_bytes(
                        key,
                        limit=_MAX_CANONICAL_SCALAR_UTF8_BYTES,
                        label="contract object key",
                    )
                )
                if scalar_bytes > _MAX_CANONICAL_SCALAR_UTF8_BYTES:
                    raise ValueError("contract material exceeds the canonical scalar-byte ceiling")
                stack.append((item, depth + 1, False))
            continue

        if isinstance(current, (set, frozenset, list, tuple)):
            if len(current) > _MAX_CANONICAL_COLLECTION_ITEMS:
                raise ValueError("contract array/set exceeds the canonical collection-size ceiling")
            container_id = id(current)
            if container_id in active_containers:
                raise ValueError("contract material must not contain reference cycles")
            active_containers.add(container_id)
            stack.append((current, depth, True))
            for item in current:
                stack.append((item, depth + 1, False))


def _bounded_utf8_bytes(value: str, *, limit: int, label: str) -> bytes:
    if len(value) > limit:
        raise ValueError(f"{label} exceeds the configured UTF-8 byte ceiling")
    encoded = value.encode("utf-8")
    if len(encoded) > limit:
        raise ValueError(f"{label} exceeds the configured UTF-8 byte ceiling")
    return encoded


def _require_canonical_json_size(value: str) -> bytes:
    encoded = _bounded_utf8_bytes(
        value, limit=_MAX_CANONICAL_JSON_BYTES, label="canonical contract JSON"
    )
    return encoded


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
