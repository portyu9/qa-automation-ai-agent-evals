from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.mcp.agent_error_bridge import MCPAgentToolErrorRecoveryReceipt
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_TOOL = "lookup_customer"


def error_fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="unit-agent-mcp-tool-error",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={"code": "TRANSIENT_UPSTREAM"},
    )


def protocol_receipt(fault: MCPFaultSpec) -> MCPFaultReceipt:
    observed = f"Error executing tool {fault.tool_name}: {fault.payload_json}"
    return MCPFaultReceipt.create(
        fault=fault,
        protocol_version="2026-07-28",
        injection_point=(
            f"mcp:2026-07-28:tools/call:{fault.tool_name}:"
            "error.content[0].text:message-suffix"
        ),
        observed_text=observed,
    )


def create_receipt() -> MCPAgentToolErrorRecoveryReceipt:
    fault = error_fault()
    error_text = f"Error executing tool {fault.tool_name}: {fault.payload_json}"
    return MCPAgentToolErrorRecoveryReceipt.create(
        scenario_identity="a" * 64,
        fault=fault,
        protocol_receipt=protocol_receipt(fault),
        agent_tool_name=_TOOL,
        error_call_id="call_error",
        retry_call_id="call_retry",
        error_arguments={"customer_id": "7"},
        retry_arguments={"customer_id": "7"},
        agent_error_output={"type": "text", "text": error_text},
        expected_recovery_text="benign",
        agent_recovery_output={"type": "text", "text": "benign"},
    )


def test_error_recovery_receipt_binds_relation_without_raw_controlled_content() -> None:
    receipt = create_receipt()

    assert receipt.error_arguments_sha256 == receipt.retry_arguments_sha256
    assert receipt.expected_recovery_sha256 == receipt.agent_recovery_observation_sha256
    serialized = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)
    assert error_fault().payload_json not in serialized
    assert "benign" not in serialized


def test_error_recovery_receipt_rejects_changed_retry_arguments() -> None:
    fault = error_fault()
    error_text = f"Error executing tool {fault.tool_name}: {fault.payload_json}"

    with pytest.raises(ValueError, match="retry arguments"):
        MCPAgentToolErrorRecoveryReceipt.create(
            scenario_identity="a" * 64,
            fault=fault,
            protocol_receipt=protocol_receipt(fault),
            agent_tool_name=_TOOL,
            error_call_id="call_error",
            retry_call_id="call_retry",
            error_arguments={"customer_id": "7"},
            retry_arguments={"customer_id": "8"},
            agent_error_output={"type": "text", "text": error_text},
            expected_recovery_text="benign",
            agent_recovery_output={"type": "text", "text": "benign"},
        )


def test_error_recovery_receipt_rejects_wrong_protocol_fault_kind() -> None:
    wrong_fault = MCPFaultSpec.from_payload(
        fault_id="unit-agent-mcp-tool-result",
        revision="1",
        kind=MCPFaultKind.TOOL_RESULT_POISON,
        tool_name=_TOOL,
        payload={"value": "poison"},
    )
    wrong_protocol = MCPFaultReceipt.create(
        fault=wrong_fault,
        protocol_version="2026-07-28",
        injection_point=f"mcp:2026-07-28:tools/call:{_TOOL}:result.content[0].text",
        observed_text=wrong_fault.payload_json,
    )

    with pytest.raises(ValueError, match="TOOL_ERROR"):
        MCPAgentToolErrorRecoveryReceipt.create(
            scenario_identity="a" * 64,
            fault=wrong_fault,
            protocol_receipt=wrong_protocol,
            agent_tool_name=_TOOL,
            error_call_id="call_error",
            retry_call_id="call_retry",
            error_arguments={"customer_id": "7"},
            retry_arguments={"customer_id": "7"},
            agent_error_output={"type": "text", "text": wrong_fault.payload_json},
            expected_recovery_text="benign",
            agent_recovery_output={"type": "text", "text": "benign"},
        )


def test_error_recovery_receipt_rejects_tampered_root() -> None:
    receipt = create_receipt()
    tampered = receipt.model_dump(mode="json")
    tampered["retry_call_id"] = "call_retry_tampered"

    with pytest.raises(ValidationError, match="receipt root"):
        MCPAgentToolErrorRecoveryReceipt.model_validate(tampered)
