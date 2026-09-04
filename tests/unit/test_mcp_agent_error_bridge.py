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


def error_text(fault: MCPFaultSpec) -> str:
    return f"Error executing tool {fault.tool_name}: {fault.payload_json}"


def protocol_receipt(
    fault: MCPFaultSpec,
    *,
    protocol_version: str = "2026-07-28",
    injection_point: str | None = None,
) -> MCPFaultReceipt:
    return MCPFaultReceipt.create(
        fault=fault,
        protocol_version=protocol_version,
        injection_point=(
            injection_point
            or f"mcp:{protocol_version}:tools/call:{fault.tool_name}:"
            "error.content[0].text:message-suffix"
        ),
        observed_text=error_text(fault),
    )


def create_receipt() -> MCPAgentToolErrorRecoveryReceipt:
    fault = error_fault()
    return MCPAgentToolErrorRecoveryReceipt.create(
        scenario_identity="a" * 64,
        fault=fault,
        protocol_receipt=protocol_receipt(fault),
        agent_tool_name=_TOOL,
        error_call_id="call_error",
        retry_call_id="call_retry",
        error_arguments={"customer_id": "7"},
        retry_arguments={"customer_id": "7"},
        agent_error_output={"type": "text", "text": error_text(fault)},
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
            agent_error_output={"type": "text", "text": error_text(fault)},
            expected_recovery_text="benign",
            agent_recovery_output={"type": "text", "text": "benign"},
        )


def test_error_recovery_receipt_rejects_reused_call_identity() -> None:
    fault = error_fault()

    with pytest.raises(ValueError, match="distinct OpenAI call IDs"):
        MCPAgentToolErrorRecoveryReceipt.create(
            scenario_identity="a" * 64,
            fault=fault,
            protocol_receipt=protocol_receipt(fault),
            agent_tool_name=_TOOL,
            error_call_id="call_same",
            retry_call_id="call_same",
            error_arguments={"customer_id": "7"},
            retry_arguments={"customer_id": "7"},
            agent_error_output={"type": "text", "text": error_text(fault)},
            expected_recovery_text="benign",
            agent_recovery_output={"type": "text", "text": "benign"},
        )


def test_error_recovery_receipt_rejects_agent_error_observation_mismatch() -> None:
    fault = error_fault()

    with pytest.raises(ValueError, match="agent-observed MCP ToolError"):
        MCPAgentToolErrorRecoveryReceipt.create(
            scenario_identity="a" * 64,
            fault=fault,
            protocol_receipt=protocol_receipt(fault),
            agent_tool_name=_TOOL,
            error_call_id="call_error",
            retry_call_id="call_retry",
            error_arguments={"customer_id": "7"},
            retry_arguments={"customer_id": "7"},
            agent_error_output={"type": "text", "text": "different error"},
            expected_recovery_text="benign",
            agent_recovery_output={"type": "text", "text": "benign"},
        )


def test_error_recovery_receipt_rejects_agent_recovery_observation_mismatch() -> None:
    fault = error_fault()

    with pytest.raises(ValueError, match="agent-observed MCP recovery"):
        MCPAgentToolErrorRecoveryReceipt.create(
            scenario_identity="a" * 64,
            fault=fault,
            protocol_receipt=protocol_receipt(fault),
            agent_tool_name=_TOOL,
            error_call_id="call_error",
            retry_call_id="call_retry",
            error_arguments={"customer_id": "7"},
            retry_arguments={"customer_id": "7"},
            agent_error_output={"type": "text", "text": error_text(fault)},
            expected_recovery_text="benign",
            agent_recovery_output={"type": "text", "text": "different recovery"},
        )


def test_error_recovery_receipt_rejects_wrong_protocol_version() -> None:
    fault = error_fault()

    with pytest.raises(ValueError, match="protocol version 2026-07-28"):
        MCPAgentToolErrorRecoveryReceipt.create(
            scenario_identity="a" * 64,
            fault=fault,
            protocol_receipt=protocol_receipt(fault, protocol_version="2026-01-01"),
            agent_tool_name=_TOOL,
            error_call_id="call_error",
            retry_call_id="call_retry",
            error_arguments={"customer_id": "7"},
            retry_arguments={"customer_id": "7"},
            agent_error_output={"type": "text", "text": error_text(fault)},
            expected_recovery_text="benign",
            agent_recovery_output={"type": "text", "text": "benign"},
        )


def test_error_recovery_receipt_rejects_wrong_protocol_observation_point() -> None:
    fault = error_fault()

    with pytest.raises(ValueError, match="unexpected observation boundary"):
        MCPAgentToolErrorRecoveryReceipt.create(
            scenario_identity="a" * 64,
            fault=fault,
            protocol_receipt=protocol_receipt(
                fault,
                injection_point=f"mcp:2026-07-28:tools/call:{_TOOL}:result.content[0].text",
            ),
            agent_tool_name=_TOOL,
            error_call_id="call_error",
            retry_call_id="call_retry",
            error_arguments={"customer_id": "7"},
            retry_arguments={"customer_id": "7"},
            agent_error_output={"type": "text", "text": error_text(fault)},
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


def test_error_recovery_receipt_rejects_tampered_argument_digest() -> None:
    tampered = create_receipt().model_dump(mode="json")
    tampered["retry_arguments_sha256"] = "b" * 64

    with pytest.raises(ValidationError, match="argument digests"):
        MCPAgentToolErrorRecoveryReceipt.model_validate(tampered)


def test_error_recovery_receipt_rejects_tampered_error_observation_digest() -> None:
    tampered = create_receipt().model_dump(mode="json")
    tampered["agent_error_observation_sha256"] = "b" * 64

    with pytest.raises(ValidationError, match="error digest"):
        MCPAgentToolErrorRecoveryReceipt.model_validate(tampered)


def test_error_recovery_receipt_rejects_tampered_recovery_observation_digest() -> None:
    tampered = create_receipt().model_dump(mode="json")
    tampered["agent_recovery_observation_sha256"] = "b" * 64

    with pytest.raises(ValidationError, match="recovery digest"):
        MCPAgentToolErrorRecoveryReceipt.model_validate(tampered)


def test_error_recovery_receipt_rejects_tampered_root() -> None:
    receipt = create_receipt()
    tampered = receipt.model_dump(mode="json")
    tampered["retry_call_id"] = "call_retry_tampered"

    with pytest.raises(ValidationError, match="receipt root"):
        MCPAgentToolErrorRecoveryReceipt.model_validate(tampered)
