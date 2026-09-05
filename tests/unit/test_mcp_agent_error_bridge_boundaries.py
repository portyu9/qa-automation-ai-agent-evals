from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_evals.mcp.agent_error_bridge import MCPAgentToolErrorRecoveryReceipt
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_TOOL = "lookup_customer"
_PROTOCOL_VERSION = "2026-07-28"


def _fault(
    *,
    fault_id: str = "tool-error-boundaries",
    tool_name: str = _TOOL,
    payload: object = None,
) -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id=fault_id,
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=tool_name,
        payload={"code": "TRANSIENT_UPSTREAM"} if payload is None else payload,
    )


def _error_text(fault: MCPFaultSpec) -> str:
    return f"Error executing tool {fault.tool_name}: {fault.payload_json}"


def _protocol_receipt(
    fault: MCPFaultSpec,
    *,
    observed_text: str | None = None,
) -> MCPFaultReceipt:
    return MCPFaultReceipt.create(
        fault=fault,
        protocol_version=_PROTOCOL_VERSION,
        injection_point=(
            f"mcp:{_PROTOCOL_VERSION}:tools/call:{fault.tool_name}:"
            "error.content[0].text:message-suffix"
        ),
        observed_text=_error_text(fault) if observed_text is None else observed_text,
    )


def _bridge_kwargs() -> dict[str, Any]:
    fault = _fault()
    return {
        "scenario_identity": "a" * 64,
        "fault": fault,
        "protocol_receipt": _protocol_receipt(fault),
        "agent_tool_name": _TOOL,
        "error_call_id": "call-error",
        "retry_call_id": "call-retry",
        "error_arguments": {"customer_id": "7"},
        "retry_arguments": {"customer_id": "7"},
        "agent_error_output": {"type": "text", "text": _error_text(fault)},
        "expected_recovery_text": "benign",
        "agent_recovery_output": {"type": "text", "text": "benign"},
    }


def _create_bridge(**overrides: Any) -> MCPAgentToolErrorRecoveryReceipt:
    values = _bridge_kwargs()
    values.update(overrides)
    return MCPAgentToolErrorRecoveryReceipt.create(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("agent_tool_name", " ", "non-empty"),
        ("agent_tool_name", f" {_TOOL}", "surrounding whitespace"),
        ("error_call_id", " ", "non-empty"),
        ("error_call_id", " call-error", "surrounding whitespace"),
        ("retry_call_id", " ", "non-empty"),
        ("retry_call_id", "call-retry ", "surrounding whitespace"),
        ("agent_tool_name", "different_tool", "controlled MCP fault tool"),
    ],
)
def test_bridge_create_rejects_malformed_or_unbound_identity(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(**{field: value})


def test_bridge_create_rejects_empty_expected_recovery() -> None:
    with pytest.raises(ValueError, match="recovery text must be non-empty"):
        _create_bridge(expected_recovery_text="")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("error_arguments", [("customer_id", "7")], "mapping or None"),
        ("retry_arguments", [("customer_id", "7")], "mapping or None"),
        ("error_arguments", {1: "7"}, "keys must be strings"),
        ("retry_arguments", {1: "7"}, "keys must be strings"),
    ],
)
def test_bridge_create_rejects_malformed_arguments(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(**{field: value})


@pytest.mark.parametrize("field", ["error_arguments", "retry_arguments"])
def test_bridge_create_rejects_non_finite_arguments(field: str) -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        _create_bridge(**{field: {"customer_id": "7", "score": float("nan")}})


@pytest.mark.parametrize("field", ["agent_error_output", "agent_recovery_output"])
@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("not-an-output-object", "model-visible text output object"),
        ({"type": "text"}, "contain exactly 'type' and 'text'"),
        ({"type": "text", "text": "x", "extra": True}, "contain exactly"),
        ({"type": "json", "text": "x"}, "one text output object"),
        ({"type": "text", "text": 1}, "one text output object"),
    ],
)
def test_bridge_create_rejects_malformed_model_visible_output(
    field: str, output: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(**{field: output})


def test_bridge_create_rejects_protocol_receipt_from_different_fault_identity() -> None:
    controlled = _fault()
    different = _fault(fault_id="tool-error-different-identity")
    with pytest.raises(ValueError, match="identity does not match controlled fault"):
        _create_bridge(fault=controlled, protocol_receipt=_protocol_receipt(different))


def test_bridge_create_rejects_protocol_observation_not_bound_to_controlled_envelope() -> None:
    fault = _fault()
    with pytest.raises(ValueError, match="observation does not match controlled fault envelope"):
        _create_bridge(
            fault=fault,
            protocol_receipt=_protocol_receipt(fault, observed_text="different ToolError envelope"),
        )


def test_receipt_model_validation_rejects_verified_tool_mismatch() -> None:
    payload = _create_bridge().model_dump(mode="json")
    payload["agent_tool_name"] = "different_tool"
    with pytest.raises(ValidationError, match="verified MCP protocol tool"):
        MCPAgentToolErrorRecoveryReceipt.model_validate(payload)


def test_receipt_model_validation_rejects_reused_call_identity() -> None:
    payload = _create_bridge().model_dump(mode="json")
    payload["retry_call_id"] = payload["error_call_id"]
    with pytest.raises(ValidationError, match="distinct OpenAI call IDs"):
        MCPAgentToolErrorRecoveryReceipt.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("error_arguments_sha256", "argument digests"),
        ("retry_arguments_sha256", "argument digests"),
        ("agent_error_observation_sha256", "error digest"),
        ("expected_recovery_sha256", "recovery digest"),
        ("agent_recovery_observation_sha256", "recovery digest"),
    ],
)
def test_receipt_model_validation_rechecks_relation_digests(field: str, message: str) -> None:
    payload = _create_bridge().model_dump(mode="json")
    payload[field] = "f" * 64
    with pytest.raises(ValidationError, match=message):
        MCPAgentToolErrorRecoveryReceipt.model_validate(payload)


def test_receipt_model_validation_rejects_root_tampering() -> None:
    payload = _create_bridge().model_dump(mode="json")
    payload["receipt_root"] = "f" * 64
    with pytest.raises(ValidationError, match="receipt root"):
        MCPAgentToolErrorRecoveryReceipt.model_validate(payload)
