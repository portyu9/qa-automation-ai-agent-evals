"""Verified trust bridge from MCP tool metadata to model-visible OpenAI tool definitions."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt

_BRIDGE_SCHEMA: Literal["agent-evals/mcp-agent-tool-metadata-receipt/v1"] = (
    "agent-evals/mcp-agent-tool-metadata-receipt/v1"
)
_BRIDGE_DOMAIN = b"agent-evals/mcp-agent-tool-metadata-receipt/v1\0"
_PROTOCOL_VERSION = "2026-07-28"
_EVENT_SOURCE = "bridge:mcp-agent:tool-metadata"


class MCPAgentToolMetadataReceipt(BaseModel):
    """Bind one exact MCP description observation to one model-visible tool definition.

    The receipt proves only that the controlled description crossed the official MCP discovery and
    pinned OpenAI Agents SDK tool-conversion boundary for one exact target contract. It does not
    prove that the model attended to, followed, or resisted that description. Raw poisoned metadata
    is deliberately excluded from the receipt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-agent-tool-metadata-receipt/v1"] = _BRIDGE_SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_receipt: MCPFaultReceipt
    agent_tool_name: str = Field(min_length=1, max_length=128)
    protocol_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_description_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_snapshot_ordinal: int = Field(ge=0, strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        scenario_identity: str,
        protocol_receipt: MCPFaultReceipt,
        agent_tool_name: str,
        protocol_schema: Mapping[str, Any],
        model_description: str,
        model_schema: Mapping[str, Any],
        model_snapshot_ordinal: int,
    ) -> Self:
        """Create a receipt only after protocol and model-visible metadata agree exactly."""
        validated_protocol = _revalidate_protocol_receipt(protocol_receipt)
        _require_metadata_receipt(validated_protocol)
        _validate_identity_text(agent_tool_name, label="agent tool name")
        if agent_tool_name != validated_protocol.tool_name:
            raise ValueError("model-visible tool name does not match the verified MCP protocol tool")
        if isinstance(model_snapshot_ordinal, bool) or model_snapshot_ordinal < 0:
            raise ValueError("model snapshot ordinal must be a non-negative integer")

        description_sha256 = _sha256_text(model_description)
        if not hmac.compare_digest(description_sha256, validated_protocol.observation_sha256):
            raise ValueError(
                "model-visible MCP tool description does not match the verified protocol observation"
            )

        protocol_schema_sha256 = _sha256_json_mapping(protocol_schema)
        model_schema_sha256 = _sha256_json_mapping(model_schema)
        if not hmac.compare_digest(protocol_schema_sha256, model_schema_sha256):
            raise ValueError(
                "model-visible MCP tool schema does not match the protocol-discovered target schema"
            )

        unsigned = {
            "schema_version": _BRIDGE_SCHEMA,
            "scenario_identity": scenario_identity,
            "protocol_receipt": validated_protocol.model_dump(mode="json"),
            "agent_tool_name": agent_tool_name,
            "protocol_schema_sha256": protocol_schema_sha256,
            "model_description_sha256": description_sha256,
            "model_schema_sha256": model_schema_sha256,
            "model_snapshot_ordinal": model_snapshot_ordinal,
        }
        return cls(
            scenario_identity=scenario_identity,
            protocol_receipt=validated_protocol,
            agent_tool_name=agent_tool_name,
            protocol_schema_sha256=protocol_schema_sha256,
            model_description_sha256=description_sha256,
            model_schema_sha256=model_schema_sha256,
            model_snapshot_ordinal=model_snapshot_ordinal,
            receipt_root=_receipt_root(unsigned),
        )

    @field_validator("protocol_receipt", mode="before")
    @classmethod
    def revalidate_protocol_receipt(cls, value: Any) -> MCPFaultReceipt:
        return _revalidate_protocol_receipt(value)

    @field_validator("agent_tool_name")
    @classmethod
    def validate_agent_tool_name(cls, value: str) -> str:
        _validate_identity_text(value, label="agent tool name")
        return value

    @model_validator(mode="after")
    def verify_bridge(self) -> Self:
        _require_metadata_receipt(self.protocol_receipt)
        if self.agent_tool_name != self.protocol_receipt.tool_name:
            raise ValueError("model-visible tool name does not match the verified MCP protocol tool")
        if not hmac.compare_digest(
            self.model_description_sha256,
            self.protocol_receipt.observation_sha256,
        ):
            raise ValueError(
                "model-visible description digest does not match verified MCP observation"
            )
        if not hmac.compare_digest(self.protocol_schema_sha256, self.model_schema_sha256):
            raise ValueError("protocol and model-visible MCP tool schema digests do not match")
        expected_root = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("MCP-to-agent tool-metadata receipt root does not match receipt content")
        return self

    def to_event(self, *, sequence: int) -> EvidenceEvent:
        """Emit delivery evidence after the first model-visible target definition is verified."""
        return EvidenceEvent(
            sequence=sequence,
            kind=EvidenceKind.PROTOCOL_DELIVERY,
            source=_EVENT_SOURCE,
            payload=self.model_dump(mode="json"),
        )


def _revalidate_protocol_receipt(value: Any) -> MCPFaultReceipt:
    if isinstance(value, MCPFaultReceipt):
        value = value.model_dump(mode="json")
    return MCPFaultReceipt.model_validate(value)


def _require_metadata_receipt(receipt: MCPFaultReceipt) -> None:
    if receipt.kind is not MCPFaultKind.TOOL_METADATA_POISON:
        raise ValueError("MCP metadata bridge requires a TOOL_METADATA_POISON protocol receipt")
    if receipt.protocol_version != _PROTOCOL_VERSION:
        raise ValueError(f"MCP metadata bridge requires protocol version {_PROTOCOL_VERSION}")
    expected_point = f"mcp:{_PROTOCOL_VERSION}:tools/list:{receipt.tool_name}:description"
    if receipt.injection_point != expected_point:
        raise ValueError(
            "MCP metadata bridge requires the exact tools/list target-description observation boundary"
        )
    if not hmac.compare_digest(receipt.observation_sha256, receipt.payload_sha256):
        raise ValueError(
            "MCP metadata protocol receipt does not prove exact controlled-description observation"
        )


def _validate_identity_text(value: str, *, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must be non-empty")
    if value != value.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")


def _receipt_root(value: object) -> str:
    return hashlib.sha256(_BRIDGE_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _sha256_text(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("model-visible MCP tool description must be a string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json_mapping(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise ValueError("MCP tool schema must be a JSON object")
    return hashlib.sha256(_canonical_json_bytes(dict(value))).hexdigest()


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
        raise ValueError("MCP metadata receipt material must be finite JSON-compatible data") from exc
