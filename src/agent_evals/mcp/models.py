"""Content-addressed contracts for deterministic MCP fault-laboratory scenarios."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_FAULT_SCHEMA: Literal["agent-evals/mcp-fault/v1"] = "agent-evals/mcp-fault/v1"
_RECEIPT_SCHEMA: Literal["agent-evals/mcp-fault-receipt/v1"] = "agent-evals/mcp-fault-receipt/v1"
_PROTOCOL_VERSION = "2026-07-28"
_MAX_CACHE_TTL_MS = 86_400_000
_SCHEMA_DRIFT_INITIAL_REQUIRED = {"query": "string"}
_SCHEMA_DRIFT_REPLACEMENT_REQUIRED = {
    "customer_id": "integer",
    "include_history": "boolean",
}


class MCPFaultKind(StrEnum):
    """Deterministic MCP fault behaviors implemented by the protocol laboratory."""

    TOOL_METADATA_POISON = "tool_metadata_poison"
    TOOL_RESULT_POISON = "tool_result_poison"
    TOOL_ERROR = "tool_error"
    TOOL_LIST_STALE_CACHE = "tool_list_stale_cache"
    TOOL_SCHEMA_DRIFT = "tool_schema_drift"
    TOOL_IDENTITY_DRIFT = "tool_identity_drift"


class MCPFaultSpec(BaseModel):
    """Content-addressed MCP fault stimulus independent of an agent provider.

    For content faults, complete canonical ``payload_json`` becomes malicious metadata/result
    content or the controlled message carried inside the SDK's model-visible tool-error envelope.
    For protocol-state faults, the payload binds the exact deterministic fault parameters consumed
    by the laboratory. Routing identity and controlled fault material therefore remain immutable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-fault/v1"] = _FAULT_SCHEMA
    fault_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    revision: str = Field(min_length=1, max_length=128)
    kind: MCPFaultKind
    tool_name: str = Field(min_length=1, max_length=128)
    payload_json: str = Field(min_length=1, max_length=100_000)

    @classmethod
    def from_payload(
        cls,
        *,
        fault_id: str,
        revision: str,
        kind: MCPFaultKind,
        tool_name: str,
        payload: Any,
    ) -> Self:
        return cls(
            fault_id=fault_id,
            revision=revision,
            kind=kind,
            tool_name=tool_name,
            payload_json=_canonical_json(payload),
        )

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("MCP fault tool name must be non-empty")
        if value != value.strip():
            raise ValueError("MCP fault tool name must not contain surrounding whitespace")
        return value

    @field_validator("payload_json")
    @classmethod
    def canonicalize_payload_json(cls, value: str) -> str:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("MCP fault payload_json must contain valid JSON") from exc
        return _canonical_json(parsed)

    @model_validator(mode="after")
    def validate_kind_payload(self) -> Self:
        if self.kind is MCPFaultKind.TOOL_LIST_STALE_CACHE:
            payload = _object_payload(self.payload, "MCP stale-cache fault")
            _require_exact_keys(payload, {"ttl_ms"}, "MCP stale-cache fault")
            _bounded_ttl_ms(payload["ttl_ms"], "MCP stale-cache")
        elif self.kind is MCPFaultKind.TOOL_SCHEMA_DRIFT:
            payload = _object_payload(self.payload, "MCP schema-drift fault")
            _require_exact_keys(
                payload,
                {"ttl_ms", "initial_required", "replacement_required"},
                "MCP schema-drift fault",
            )
            _bounded_ttl_ms(payload["ttl_ms"], "MCP schema-drift")
            if payload["initial_required"] != _SCHEMA_DRIFT_INITIAL_REQUIRED:
                raise ValueError(
                    "MCP schema-drift initial_required must bind the v1 query:string contract"
                )
            if payload["replacement_required"] != _SCHEMA_DRIFT_REPLACEMENT_REQUIRED:
                raise ValueError(
                    "MCP schema-drift replacement_required must bind the v1 "
                    "customer_id:integer/include_history:boolean contract"
                )
        elif self.kind is MCPFaultKind.TOOL_IDENTITY_DRIFT:
            payload = _object_payload(self.payload, "MCP identity-drift fault")
            _require_exact_keys(
                payload,
                {"ttl_ms", "replacement_tool_name"},
                "MCP identity-drift fault",
            )
            _bounded_ttl_ms(payload["ttl_ms"], "MCP identity-drift")
            replacement = payload["replacement_tool_name"]
            if not isinstance(replacement, str):
                raise ValueError("MCP identity-drift replacement_tool_name must be a string")
            if not replacement.strip():
                raise ValueError("MCP identity-drift replacement_tool_name must be non-empty")
            if replacement != replacement.strip():
                raise ValueError(
                    "MCP identity-drift replacement_tool_name must not contain surrounding whitespace"
                )
            if len(replacement) > 128:
                raise ValueError(
                    "MCP identity-drift replacement_tool_name must be at most 128 characters"
                )
            if replacement == self.tool_name:
                raise ValueError(
                    "MCP identity-drift replacement_tool_name must differ from the original tool"
                )
        return self

    @property
    def payload(self) -> Any:
        """Return a fresh decoded payload so callers cannot mutate fault identity in place."""
        return json.loads(self.payload_json)

    @property
    def payload_sha256(self) -> str:
        return _sha256_text(self.payload_json)

    @property
    def identity(self) -> str:
        return _sha256_json(
            {
                "schema_version": self.schema_version,
                "fault_id": self.fault_id,
                "revision": self.revision,
                "kind": self.kind.value,
                "tool_name": self.tool_name,
                "payload_json": self.payload_json,
            }
        )


class MCPFaultReceipt(BaseModel):
    """Integrity-bound observation that a fault reached one exact MCP protocol boundary.

    ``payload_sha256`` binds controlled fault material while ``observation_sha256`` binds the exact
    canonical observation derived from public MCP client fields. Those digests match for direct
    content delivery and may differ when the SDK transforms content or the fault changes protocol
    state rather than directly supplying text. Raw malicious content is not duplicated into the
    receipt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-fault-receipt/v1"] = _RECEIPT_SCHEMA
    fault_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: MCPFaultKind
    protocol_version: str = Field(min_length=1, max_length=64)
    tool_name: str = Field(min_length=1, max_length=128)
    injection_point: str = Field(min_length=1, max_length=512)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        fault: MCPFaultSpec,
        injection_point: str,
        observed_text: str,
        protocol_version: str = _PROTOCOL_VERSION,
    ) -> Self:
        observation_sha256 = _sha256_text(observed_text)
        material = {
            "schema_version": _RECEIPT_SCHEMA,
            "fault_identity": fault.identity,
            "kind": fault.kind.value,
            "protocol_version": protocol_version,
            "tool_name": fault.tool_name,
            "injection_point": injection_point,
            "payload_sha256": fault.payload_sha256,
            "observation_sha256": observation_sha256,
        }
        return cls(
            fault_identity=fault.identity,
            kind=fault.kind,
            protocol_version=protocol_version,
            tool_name=fault.tool_name,
            injection_point=injection_point,
            payload_sha256=fault.payload_sha256,
            observation_sha256=observation_sha256,
            receipt_root=_sha256_json(material),
        )

    @model_validator(mode="after")
    def verify_receipt_root(self) -> Self:
        material = {
            "schema_version": self.schema_version,
            "fault_identity": self.fault_identity,
            "kind": self.kind.value,
            "protocol_version": self.protocol_version,
            "tool_name": self.tool_name,
            "injection_point": self.injection_point,
            "payload_sha256": self.payload_sha256,
            "observation_sha256": self.observation_sha256,
        }
        if self.receipt_root != _sha256_json(material):
            raise ValueError("MCP fault receipt root does not match receipt material")
        return self


class MCPProbeResult(BaseModel):
    """Deterministic client observation produced by one MCP content-fault probe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fault_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1, max_length=64)
    advertised_description: str
    first_call_text: tuple[str, ...]
    first_call_is_error: bool
    second_call_text: tuple[str, ...]
    second_call_is_error: bool
    receipt: MCPFaultReceipt | None = None

    @model_validator(mode="after")
    def verify_receipt_identity(self) -> Self:
        _verify_probe_receipt(
            receipt=self.receipt,
            fault_identity=self.fault_identity,
            protocol_version=self.protocol_version,
        )
        return self


class MCPDiscoveryProbeResult(BaseModel):
    """Official-client observations for a stale tool-discovery cache fault."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fault_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1, max_length=64)
    initial_tool_names: tuple[str, ...]
    cached_tool_names: tuple[str, ...]
    refreshed_tool_names: tuple[str, ...]
    receipt: MCPFaultReceipt | None = None

    @model_validator(mode="after")
    def verify_receipt_identity(self) -> Self:
        _verify_probe_receipt(
            receipt=self.receipt,
            fault_identity=self.fault_identity,
            protocol_version=self.protocol_version,
        )
        return self


class MCPToolSchemaDriftProbeResult(BaseModel):
    """Public MCP observations spanning cached discovery, refresh, and call-time schema checks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fault_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1, max_length=64)
    initial_schema_json: str
    cached_schema_json: str
    refreshed_schema_json: str
    stale_call_text: tuple[str, ...]
    stale_call_is_error: bool
    refreshed_call_text: tuple[str, ...]
    refreshed_call_is_error: bool
    receipt: MCPFaultReceipt | None = None

    @model_validator(mode="after")
    def verify_receipt_identity(self) -> Self:
        _verify_probe_receipt(
            receipt=self.receipt,
            fault_identity=self.fault_identity,
            protocol_version=self.protocol_version,
        )
        return self


class MCPToolIdentityDriftProbeResult(BaseModel):
    """Public MCP observations spanning cached discovery, rename, refresh, and call-time lookup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fault_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: str = Field(min_length=1, max_length=64)
    initial_tool_names: tuple[str, ...]
    cached_tool_names: tuple[str, ...]
    refreshed_tool_names: tuple[str, ...]
    stale_call_text: tuple[str, ...]
    stale_call_is_error: bool
    replacement_call_text: tuple[str, ...]
    replacement_call_is_error: bool
    receipt: MCPFaultReceipt | None = None

    @model_validator(mode="after")
    def verify_receipt_identity(self) -> Self:
        _verify_probe_receipt(
            receipt=self.receipt,
            fault_identity=self.fault_identity,
            protocol_version=self.protocol_version,
        )
        return self


def _object_payload(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} payload must be an object")
    return payload


def _require_exact_keys(payload: dict[str, Any], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        expected_text = ", ".join(sorted(expected))
        raise ValueError(f"{label} payload must contain exactly: {expected_text}")


def _bounded_ttl_ms(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} ttl_ms must be an integer")
    if value <= 0 or value > _MAX_CACHE_TTL_MS:
        raise ValueError(f"{label} ttl_ms must be between 1 and 86400000 milliseconds")
    return value


def _verify_probe_receipt(
    *,
    receipt: MCPFaultReceipt | None,
    fault_identity: str,
    protocol_version: str,
) -> None:
    if receipt is None:
        return
    if receipt.fault_identity != fault_identity:
        raise ValueError("MCP probe receipt identity does not match probed fault")
    if receipt.protocol_version != protocol_version:
        raise ValueError("MCP probe receipt protocol version does not match probe")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("MCP fault payload must be finite JSON-compatible data") from exc
