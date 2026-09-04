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


class AuthorityPolicy(BaseModel):
    """Fail-closed authority granted to the evaluated agent for one scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_tools: frozenset[str] = frozenset()
    forbidden_tools: frozenset[str] = frozenset()
    approval_required_tools: frozenset[str] = frozenset()
    allowed_resource_prefixes: tuple[str, ...] = ()
    max_turns: int = Field(default=16, ge=1, le=10_000)
    max_tool_calls: int = Field(default=32, ge=0, le=10_000)
    max_handoffs: int = Field(default=8, ge=0, le=1_000)

    @field_validator("allowed_tools", "forbidden_tools", "approval_required_tools")
    @classmethod
    def reject_empty_tool_names(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not name.strip() for name in value):
            raise ValueError("tool identities must be non-empty strings")
        return value

    @field_validator("allowed_resource_prefixes")
    @classmethod
    def canonicalize_resource_prefixes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not prefix.strip() for prefix in value):
            raise ValueError("resource prefixes must be non-empty strings")
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def validate_disjoint_tools(self) -> AuthorityPolicy:
        overlap = self.allowed_tools & self.forbidden_tools
        if overlap:
            raise ValueError(f"tools cannot be both allowed and forbidden: {sorted(overlap)!r}")
        if not self.approval_required_tools <= self.allowed_tools:
            missing = self.approval_required_tools - self.allowed_tools
            raise ValueError(f"approval-required tools must also be allowed: {sorted(missing)!r}")
        return self

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
    def reject_contradictory_outcomes(self) -> EvaluationScenario:
        conflicts = {
            key
            for key, expected in self.required_outcomes.items()
            if key in self.forbidden_outcomes and self.forbidden_outcomes[key] == expected
        }
        if conflicts:
            raise ValueError(
                f"outcomes cannot be simultaneously required and forbidden: {sorted(conflicts)!r}"
            )
        return self

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python", exclude_none=True))


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
