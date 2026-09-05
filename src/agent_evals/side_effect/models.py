"""Scenario-owned contracts for run-local side-effect idempotency assurance."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_OPERATION_DOMAIN = b"agent-evals/side-effect-operation/v1\0"


class SideEffectIdempotencySpec(BaseModel):
    """Bind one exact two-attempt logical operation used to test local idempotency."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str = Field(min_length=1, max_length=256)
    key_argument: str = Field(min_length=1, max_length=256)
    expected_arguments: dict[str, Any]
    attempts: Literal[2] = 2
    require_first_mutation: bool = True

    @field_validator("tool", "key_argument")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("side-effect identities must not contain surrounding whitespace")
        return value

    @field_validator("expected_arguments")
    @classmethod
    def validate_expected_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        _canonical_json_bytes(value)
        return value

    @model_validator(mode="after")
    def validate_operation_key(self) -> Self:
        if self.key_argument not in self.expected_arguments:
            raise ValueError("side-effect key_argument must exist in expected_arguments")
        key = self.expected_arguments[self.key_argument]
        if isinstance(key, bool) or not isinstance(key, (str, int)):
            raise ValueError("side-effect logical-operation key must be a string or integer")
        return self

    @property
    def expected_arguments_sha256(self) -> str:
        return _sha256_json(self.expected_arguments)

    @property
    def key_sha256(self) -> str:
        return _sha256_json(self.expected_arguments[self.key_argument])

    @property
    def logical_operation_identity(self) -> str:
        material = {
            "tool": self.tool,
            "key_argument": self.key_argument,
            "key_sha256": self.key_sha256,
            "arguments_sha256": self.expected_arguments_sha256,
        }
        return hashlib.sha256(_OPERATION_DOMAIN + _canonical_json_bytes(material)).hexdigest()

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python"))


def canonical_json_sha256(value: Any) -> str:
    """Return the deterministic digest used for arguments and effect snapshots."""
    return _sha256_json(value)


def canonicalize_json(value: Any) -> Any:
    """Return deterministic finite JSON-compatible material or raise ValueError."""
    return _canonicalize_json(value)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    normalized = _canonicalize_json(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonicalize_json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonicalize_json(value.model_dump(mode="python", exclude_none=True))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("side-effect JSON object keys must be strings")
        return {key: _canonicalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("side-effect JSON values must be finite")
        return value
    raise ValueError(f"unsupported side-effect JSON value type: {type(value).__name__}")
