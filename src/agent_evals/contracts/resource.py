"""Versioned typed resource identifiers and structural authorization scopes."""

from __future__ import annotations

import json
import re
import unicodedata
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_RESOURCE_SCHEMA: Literal["agent-evals/resource/v1"] = "agent-evals/resource/v1"
_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MAX_COMPONENTS = 64
_MAX_COMPONENT_LENGTH = 256


class ResourceKind(StrEnum):
    """Resource grammars with explicitly defined authorization semantics."""

    HIERARCHICAL = "hierarchical"


class ResourceIdentifier(BaseModel):
    """One canonical resource identity in a versioned resource domain.

    Version 1 supports only evaluator-defined hierarchical domains. Components are exact,
    case-sensitive Unicode strings that must already be NFC-normalized. Filesystem paths, URLs,
    encoded paths, and object-store keys are not silently reinterpreted as this resource kind.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/resource/v1"] = _RESOURCE_SCHEMA
    kind: ResourceKind = ResourceKind.HIERARCHICAL
    domain: str = Field(min_length=1, max_length=64)
    components: tuple[str, ...]

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        if _DOMAIN_RE.fullmatch(value) is None:
            raise ValueError(
                "resource domain must be canonical lowercase ASCII: letter followed by "
                "letters, digits, '_' or '-'"
            )
        return value

    @field_validator("components")
    @classmethod
    def validate_components(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("resource identifier requires at least one component")
        return _validate_components(value)

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        if self.kind is not ResourceKind.HIERARCHICAL:
            raise ValueError("unsupported resource kind")
        return self

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.model_dump(mode="python"))


class ResourceScope(BaseModel):
    """Canonical component-aware authorization scope for one resource domain.

    An empty component tuple explicitly means the entire named domain. Otherwise containment is
    structural: the scope components must match complete leading components of the candidate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/resource/v1"] = _RESOURCE_SCHEMA
    kind: ResourceKind = ResourceKind.HIERARCHICAL
    domain: str = Field(min_length=1, max_length=64)
    components: tuple[str, ...] = ()

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        if _DOMAIN_RE.fullmatch(value) is None:
            raise ValueError(
                "resource domain must be canonical lowercase ASCII: letter followed by "
                "letters, digits, '_' or '-'"
            )
        return value

    @field_validator("components")
    @classmethod
    def validate_components(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_components(value)

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        if self.kind is not ResourceKind.HIERARCHICAL:
            raise ValueError("unsupported resource kind")
        return self

    def contains_identifier(self, resource: ResourceIdentifier) -> bool:
        """Return whether this scope contains one exact typed resource identity."""
        if type(resource) is not ResourceIdentifier:
            return False
        if self.schema_version != resource.schema_version:
            return False
        if self.kind is not resource.kind or self.domain != resource.domain:
            return False
        return _components_contain(self.components, resource.components)

    def contains_scope(self, candidate: ResourceScope) -> bool:
        """Return whether another scope is equal to or structurally narrower than this scope."""
        if type(candidate) is not ResourceScope:
            return False
        if self.schema_version != candidate.schema_version:
            return False
        if self.kind is not candidate.kind or self.domain != candidate.domain:
            return False
        return _components_contain(self.components, candidate.components)

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.model_dump(mode="python"))


def _validate_components(value: tuple[str, ...]) -> tuple[str, ...]:
    if len(value) > _MAX_COMPONENTS:
        raise ValueError(f"resource paths may contain at most {_MAX_COMPONENTS} components")
    for component in value:
        if not isinstance(component, str):
            raise ValueError("resource components must be strings")
        if not component:
            raise ValueError("resource components must be non-empty")
        if len(component) > _MAX_COMPONENT_LENGTH:
            raise ValueError(
                f"resource components must be at most {_MAX_COMPONENT_LENGTH} characters"
            )
        if component != component.strip():
            raise ValueError("resource components must not contain surrounding whitespace")
        if component in {".", ".."}:
            raise ValueError("resource components must not use dot-segment aliases")
        if "/" in component or "\\" in component:
            raise ValueError("resource separators must be represented as distinct components")
        if "%" in component:
            raise ValueError("percent-encoded resource material is not accepted by v1")
        if unicodedata.normalize("NFC", component) != component:
            raise ValueError("resource components must already be NFC-normalized")
        if any(unicodedata.category(character).startswith("C") for character in component):
            raise ValueError(
                "resource components must not contain control, format, surrogate, private-use, "
                "or unassigned Unicode characters"
            )
    return value


def _components_contain(scope: tuple[str, ...], candidate: tuple[str, ...]) -> bool:
    return len(scope) <= len(candidate) and candidate[: len(scope)] == scope


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
