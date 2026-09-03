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


class MCPFaultKind(StrEnum):
    """Deterministic MCP fault behaviors implemented by the protocol laboratory."""

    TOOL_METADATA_POISON = "tool_metadata_poison"
    TOOL_RESULT_POISON = "tool_result_poison"
    TOOL_ERROR = "tool_error"
    TOOL_LIST_STALE_CACHE = "tool_list_stale_cache"


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
            payload = self.payload
            if not isinstance(payload, dict) or set(payload) != {"ttl_ms"}:
                raise ValueError(
                    "MCP stale-cache fault payload must contain exactly integer field 'ttl_ms'"
                )
            ttl_ms = payload["ttl_ms"]
            if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int):
                raise ValueError("MCP stale-cache ttl_ms must be an integer")
            if ttl_ms <= 0 or ttl_ms > _MAX_CACHE_TTL_MS:
                raise ValueError(
                    "MCP stale-cache ttl_ms must be between 1 and 86400000 milliseconds"
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
