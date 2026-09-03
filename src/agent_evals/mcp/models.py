"""Content-addressed contracts for deterministic MCP fault-laboratory scenarios."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_FAULT_SCHEMA: Literal["agent-evals/mcp-fault/v1"] = "agent-evals/mcp-fault/v1"
_RECEIPT_SCHEMA: Literal["agent-evals/mcp-fault-receipt/v1"] = (
    "agent-evals/mcp-fault-receipt/v1"
)
_PROTOCOL_VERSION = "2026-07-28"


class MCPFaultKind(StrEnum):
    """Deterministic MCP fault behaviors implemented by the protocol laboratory."""

    TOOL_METADATA_POISON = "tool_metadata_poison"
    TOOL_RESULT_POISON = "tool_result_poison"
    TOOL_ERROR = "tool_error"


class MCPFaultSpec(BaseModel):
    """Content-addressed MCP fault stimulus independent of an agent provider.

    The complete canonical ``payload_json`` becomes the malicious metadata, result, or
    model-visible tool-error text. Routing identity and exact injected bytes are therefore bound to
    one immutable fault identity rather than selected independently by the runtime harness.
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

    @property
    def payload(self) -> Any:
        """Return a fresh decoded payload so callers cannot mutate fault identity in place."""
        return json.loads(self.payload_json)

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(self.payload_json.encode("utf-8")).hexdigest()

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

    The receipt stores the payload digest rather than raw malicious content. It is evaluator-side
    evidence relative to the trusted in-process client observation; it is not cryptographic server
    identity, remote-host attestation, or proof that an autonomous agent consumed the bytes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-fault-receipt/v1"] = _RECEIPT_SCHEMA
    fault_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: MCPFaultKind
    protocol_version: str = Field(min_length=1, max_length=64)
    tool_name: str = Field(min_length=1, max_length=128)
    injection_point: str = Field(min_length=1, max_length=512)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        fault: MCPFaultSpec,
        injection_point: str,
        protocol_version: str = _PROTOCOL_VERSION,
    ) -> Self:
        material = {
            "schema_version": _RECEIPT_SCHEMA,
            "fault_identity": fault.identity,
            "kind": fault.kind.value,
            "protocol_version": protocol_version,
            "tool_name": fault.tool_name,
            "injection_point": injection_point,
            "payload_sha256": fault.payload_sha256,
        }
        return cls(**material, receipt_root=_sha256_json(material))

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
        }
        if self.receipt_root != _sha256_json(material):
            raise ValueError("MCP fault receipt root does not match receipt material")
        return self


class MCPProbeResult(BaseModel):
    """Deterministic client observation produced by one MCP fault-lab probe."""

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
        if self.receipt is not None:
            if self.receipt.fault_identity != self.fault_identity:
                raise ValueError("MCP probe receipt identity does not match probed fault")
            if self.receipt.protocol_version != self.protocol_version:
                raise ValueError("MCP probe receipt protocol version does not match probe")
        return self


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("MCP fault payload must be finite JSON-compatible data") from exc
