"""Verified trust bridge for MCP ToolError recovery observed by an OpenAI agent."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_BRIDGE_SCHEMA: Literal["agent-evals/mcp-agent-tool-error-recovery-receipt/v1"] = (
    "agent-evals/mcp-agent-tool-error-recovery-receipt/v1"
)
_BRIDGE_DOMAIN = b"agent-evals/mcp-agent-tool-error-recovery-receipt/v1\0"
_PROTOCOL_VERSION = "2026-07-28"
_EVENT_SOURCE = "bridge:mcp-agent:tool-error-recovery"


class MCPAgentToolErrorRecoveryReceipt(BaseModel):
    """Bind one verified MCP ToolError to one exact agent retry and recovery result.

    Raw controlled error text, retry arguments, and recovery text are deliberately excluded.
    The receipt stores only integrity identities and digests needed to prove the evaluator-observed
    relation. It is not target-side attestation and does not itself decide an agent verdict.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-agent-tool-error-recovery-receipt/v1"] = _BRIDGE_SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_receipt: MCPFaultReceipt
    agent_tool_name: str = Field(min_length=1, max_length=128)
    error_call_id: str = Field(min_length=1, max_length=256)
    retry_call_id: str = Field(min_length=1, max_length=256)
    error_arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retry_arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_error_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_recovery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_recovery_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        scenario_identity: str,
        fault: MCPFaultSpec,
        protocol_receipt: MCPFaultReceipt,
        agent_tool_name: str,
        error_call_id: str,
        retry_call_id: str,
        error_arguments: Mapping[str, object] | None,
        retry_arguments: Mapping[str, object] | None,
        agent_error_output: object,
        expected_recovery_text: str,
        agent_recovery_output: object,
    ) -> Self:
        """Create a receipt only after protocol error, retry identity, and recovery agree."""
        validated_protocol = _revalidate_protocol_receipt(protocol_receipt)
        _require_tool_error_receipt(fault=fault, receipt=validated_protocol)
        _validate_identity_text(agent_tool_name, label="agent tool name")
        _validate_identity_text(error_call_id, label="error call ID")
        _validate_identity_text(retry_call_id, label="retry call ID")
        if error_call_id == retry_call_id:
            raise ValueError("MCP ToolError recovery requires distinct OpenAI call IDs")
        if agent_tool_name != fault.tool_name:
            raise ValueError("agent tool name does not match the controlled MCP fault tool")
        if not expected_recovery_text:
            raise ValueError("expected MCP recovery text must be non-empty")

        error_arguments_sha256 = _sha256_json(_canonical_arguments(error_arguments))
        retry_arguments_sha256 = _sha256_json(_canonical_arguments(retry_arguments))
        if not hmac.compare_digest(error_arguments_sha256, retry_arguments_sha256):
            raise ValueError("MCP ToolError retry arguments do not match the original call")

        agent_error_text = _extract_single_text_output(agent_error_output, phase="error")
        agent_error_sha256 = _sha256_text(agent_error_text)
        if not hmac.compare_digest(
            agent_error_sha256,
            validated_protocol.observation_sha256,
        ):
            raise ValueError(
                "agent-observed MCP ToolError does not match verified protocol observation"
            )

        expected_recovery_sha256 = _sha256_text(expected_recovery_text)
        agent_recovery_text = _extract_single_text_output(
            agent_recovery_output,
            phase="recovery",
        )
        agent_recovery_sha256 = _sha256_text(agent_recovery_text)
        if not hmac.compare_digest(
            expected_recovery_sha256,
            agent_recovery_sha256,
        ):
            raise ValueError("agent-observed MCP recovery does not match expected benign result")

        unsigned = {
            "schema_version": _BRIDGE_SCHEMA,
            "scenario_identity": scenario_identity,
            "protocol_receipt": validated_protocol.model_dump(mode="json"),
            "agent_tool_name": agent_tool_name,
            "error_call_id": error_call_id,
            "retry_call_id": retry_call_id,
            "error_arguments_sha256": error_arguments_sha256,
            "retry_arguments_sha256": retry_arguments_sha256,
            "agent_error_observation_sha256": agent_error_sha256,
            "expected_recovery_sha256": expected_recovery_sha256,
            "agent_recovery_observation_sha256": agent_recovery_sha256,
        }
        return cls(
            scenario_identity=scenario_identity,
            protocol_receipt=validated_protocol,
            agent_tool_name=agent_tool_name,
            error_call_id=error_call_id,
            retry_call_id=retry_call_id,
            error_arguments_sha256=error_arguments_sha256,
            retry_arguments_sha256=retry_arguments_sha256,
            agent_error_observation_sha256=agent_error_sha256,
            expected_recovery_sha256=expected_recovery_sha256,
            agent_recovery_observation_sha256=agent_recovery_sha256,
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

    @field_validator("error_call_id", "retry_call_id")
    @classmethod
    def validate_call_id(cls, value: str) -> str:
        _validate_identity_text(value, label="agent call ID")
        return value

    @model_validator(mode="after")
    def verify_bridge(self) -> Self:
        _require_tool_error_receipt_shape(self.protocol_receipt)
        if self.agent_tool_name != self.protocol_receipt.tool_name:
            raise ValueError("agent tool name does not match verified MCP protocol tool")
        if self.error_call_id == self.retry_call_id:
            raise ValueError("MCP ToolError recovery requires distinct OpenAI call IDs")
        if not hmac.compare_digest(
            self.error_arguments_sha256,
            self.retry_arguments_sha256,
        ):
            raise ValueError("MCP ToolError retry argument digests do not match")
        if not hmac.compare_digest(
            self.agent_error_observation_sha256,
            self.protocol_receipt.observation_sha256,
        ):
            raise ValueError("agent error digest does not match MCP protocol observation digest")
        if not hmac.compare_digest(
            self.expected_recovery_sha256,
            self.agent_recovery_observation_sha256,
        ):
            raise ValueError("agent recovery digest does not match expected recovery digest")
        expected_root = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("MCP ToolError recovery receipt root does not match receipt content")
        return self

    def to_event(self, *, sequence: int) -> EvidenceEvent:
        """Emit normalized trial evidence after the complete recovery relation closes."""
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


def _require_tool_error_receipt(
    *,
    fault: MCPFaultSpec,
    receipt: MCPFaultReceipt,
) -> None:
    _require_tool_error_receipt_shape(receipt)
    if fault.kind is not MCPFaultKind.TOOL_ERROR:
        raise ValueError("MCP ToolError recovery bridge requires a TOOL_ERROR fault")
    if receipt.fault_identity != fault.identity:
        raise ValueError("MCP ToolError protocol receipt identity does not match controlled fault")
    if receipt.tool_name != fault.tool_name:
        raise ValueError("MCP ToolError protocol receipt tool does not match controlled fault")
    if not hmac.compare_digest(receipt.payload_sha256, fault.payload_sha256):
        raise ValueError("MCP ToolError protocol receipt payload does not match controlled fault")
    expected_error = f"Error executing tool {fault.tool_name}: {fault.payload_json}"
    if not hmac.compare_digest(
        receipt.observation_sha256,
        _sha256_text(expected_error),
    ):
        raise ValueError(
            "MCP ToolError protocol observation does not match controlled fault envelope"
        )


def _require_tool_error_receipt_shape(receipt: MCPFaultReceipt) -> None:
    if receipt.kind is not MCPFaultKind.TOOL_ERROR:
        raise ValueError("MCP ToolError recovery bridge requires a TOOL_ERROR protocol receipt")
    if receipt.protocol_version != _PROTOCOL_VERSION:
        raise ValueError(
            f"MCP ToolError recovery bridge requires protocol version {_PROTOCOL_VERSION}"
        )
    expected_point = (
        f"mcp:{_PROTOCOL_VERSION}:tools/call:{receipt.tool_name}:"
        "error.content[0].text:message-suffix"
    )
    if receipt.injection_point != expected_point:
        raise ValueError("MCP ToolError protocol receipt uses an unexpected observation boundary")


def _canonical_arguments(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("MCP ToolError arguments must be a mapping or None")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise ValueError("MCP ToolError argument keys must be strings")
    _canonical_json_bytes(result)
    return result


def _extract_single_text_output(value: object, *, phase: str) -> str:
    if not isinstance(value, Mapping):
        raise ValueError(f"agent MCP {phase} result must be one model-visible text output object")
    if set(value) != {"type", "text"}:
        raise ValueError(f"agent MCP {phase} result must contain exactly 'type' and 'text'")
    text = value.get("text")
    if value.get("type") != "text" or not isinstance(text, str):
        raise ValueError(f"agent MCP {phase} result must be one text output object")
    return text


def _validate_identity_text(value: str, *, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must be non-empty")
    if value != value.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")


def _receipt_root(value: object) -> str:
    return hashlib.sha256(_BRIDGE_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
