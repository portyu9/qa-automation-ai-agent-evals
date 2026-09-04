"""Verified trust bridge from MCP protocol delivery to agent-observed tool results."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt

_BRIDGE_SCHEMA: Literal["agent-evals/mcp-agent-tool-result-receipt/v1"] = (
    "agent-evals/mcp-agent-tool-result-receipt/v1"
)
_BRIDGE_DOMAIN = b"agent-evals/mcp-agent-tool-result-receipt/v1\0"
_PROTOCOL_VERSION = "2026-07-28"
_EVENT_SOURCE = "bridge:mcp-agent:tool-result"


class MCPAgentToolResultReceipt(BaseModel):
    """Bind verified MCP tool-result delivery to one exact agent-observed tool result.

    This receipt is deliberately narrower than general MCP protocol evidence. It accepts only the
    direct ``TOOL_RESULT_POISON`` boundary where the protocol laboratory observed exact controlled
    text and the agent subsequently observed that same text for the same tool call. Raw controlled
    content is never duplicated into the receipt or normalized evidence event.

    The receipt proves consistency across trusted evaluator observations. It is not target-side
    attestation and does not, by itself, establish an agent behavioral verdict or release decision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-agent-tool-result-receipt/v1"] = _BRIDGE_SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_receipt: MCPFaultReceipt
    agent_tool_name: str = Field(min_length=1, max_length=128)
    agent_call_id: str = Field(min_length=1, max_length=256)
    agent_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        scenario_identity: str,
        protocol_receipt: MCPFaultReceipt,
        agent_tool_name: str,
        agent_call_id: str,
        agent_output: object,
    ) -> Self:
        """Create a bridge receipt only after exact protocol and agent observations agree."""
        validated_protocol = _revalidate_protocol_receipt(protocol_receipt)
        _require_direct_tool_result_receipt(validated_protocol)
        _validate_identity_text(agent_tool_name, label="agent tool name")
        _validate_identity_text(agent_call_id, label="agent call ID")
        if agent_tool_name != validated_protocol.tool_name:
            raise ValueError("agent tool name does not match the verified MCP protocol tool")

        observed_text = _extract_single_text_output(agent_output)
        observation_sha256 = _sha256_text(observed_text)
        if not hmac.compare_digest(observation_sha256, validated_protocol.payload_sha256):
            raise ValueError(
                "agent-observed MCP tool result does not match the verified controlled payload"
            )

        unsigned = {
            "schema_version": _BRIDGE_SCHEMA,
            "scenario_identity": scenario_identity,
            "protocol_receipt": validated_protocol.model_dump(mode="json"),
            "agent_tool_name": agent_tool_name,
            "agent_call_id": agent_call_id,
            "agent_observation_sha256": observation_sha256,
        }
        return cls(
            scenario_identity=scenario_identity,
            protocol_receipt=validated_protocol,
            agent_tool_name=agent_tool_name,
            agent_call_id=agent_call_id,
            agent_observation_sha256=observation_sha256,
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

    @field_validator("agent_call_id")
    @classmethod
    def validate_agent_call_id(cls, value: str) -> str:
        _validate_identity_text(value, label="agent call ID")
        return value

    @model_validator(mode="after")
    def verify_bridge(self) -> Self:
        _require_direct_tool_result_receipt(self.protocol_receipt)
        if self.agent_tool_name != self.protocol_receipt.tool_name:
            raise ValueError("agent tool name does not match the verified MCP protocol tool")
        if not hmac.compare_digest(
            self.agent_observation_sha256,
            self.protocol_receipt.payload_sha256,
        ):
            raise ValueError(
                "agent observation digest does not match the verified MCP controlled payload"
            )
        expected_root = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("MCP-to-agent tool-result receipt root does not match receipt content")
        return self

    def to_event(self, *, sequence: int) -> EvidenceEvent:
        """Emit normalized trial evidence after the protocol-to-agent bridge closes."""
        return EvidenceEvent(
            sequence=sequence,
            kind=EvidenceKind.PROTOCOL_DELIVERY,
            source=_EVENT_SOURCE,
            payload=self.model_dump(mode="json"),
        )


def _revalidate_protocol_receipt(value: Any) -> MCPFaultReceipt:
    """Never trust a pre-built Pydantic instance at this cross-domain trust boundary."""
    if isinstance(value, MCPFaultReceipt):
        value = value.model_dump(mode="json")
    return MCPFaultReceipt.model_validate(value)


def _require_direct_tool_result_receipt(receipt: MCPFaultReceipt) -> None:
    if receipt.kind is not MCPFaultKind.TOOL_RESULT_POISON:
        raise ValueError("MCP-to-agent bridge requires a TOOL_RESULT_POISON protocol receipt")
    if receipt.protocol_version != _PROTOCOL_VERSION:
        raise ValueError(f"MCP-to-agent bridge requires protocol version {_PROTOCOL_VERSION}")
    expected_point = (
        f"mcp:{_PROTOCOL_VERSION}:tools/call:{receipt.tool_name}:result.content[0].text"
    )
    if receipt.injection_point != expected_point:
        raise ValueError(
            "MCP-to-agent bridge requires the exact direct tool-result text observation boundary"
        )
    if not hmac.compare_digest(receipt.observation_sha256, receipt.payload_sha256):
        raise ValueError(
            "MCP protocol receipt does not prove exact direct controlled-payload observation"
        )


def _extract_single_text_output(value: object) -> str:
    """Accept the pinned Agents SDK model-visible shape for one MCP text content block."""
    if not isinstance(value, Mapping):
        raise ValueError("agent MCP tool result must be one model-visible text output object")
    if set(value) != {"type", "text"}:
        raise ValueError("agent MCP tool result must contain exactly 'type' and 'text'")
    text = value.get("text")
    if value.get("type") != "text" or not isinstance(text, str):
        raise ValueError("agent MCP tool result must be one text output object")
    return text


def _validate_identity_text(value: str, *, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must be non-empty")
    if value != value.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")


def _receipt_root(value: object) -> str:
    return hashlib.sha256(_BRIDGE_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
