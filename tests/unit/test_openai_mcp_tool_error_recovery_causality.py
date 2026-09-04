from __future__ import annotations

import pytest

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adapters.openai_mcp_tool_error_recovery import _attach_verified_recovery_bridge
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_TOOL = "lookup_customer"


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="unit.openai.mcp.tool-error-recovery-causality",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Prove the recovery call occurs only after the controlled error is observed.",
    )


def fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="unit-openai-mcp-tool-error-causality",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={"code": "TRANSIENT_UPSTREAM"},
    )


def protocol_receipt(controlled_fault: MCPFaultSpec) -> MCPFaultReceipt:
    error_text = f"Error executing tool {_TOOL}: {controlled_fault.payload_json}"
    return MCPFaultReceipt.create(
        fault=controlled_fault,
        protocol_version="2026-07-28",
        injection_point=(
            f"mcp:2026-07-28:tools/call:{_TOOL}:error.content[0].text:message-suffix"
        ),
        observed_text=error_text,
    )


def test_error_recovery_bridge_rejects_preissued_retry_before_error_result() -> None:
    controlled_fault = fault()
    events = (
        EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.TOOL_REQUEST,
            source="openai-agents:new_items",
            payload={"tool": _TOOL, "call_id": "call_error", "arguments": "{}"},
        ),
        EvidenceEvent(
            sequence=1,
            kind=EvidenceKind.TOOL_REQUEST,
            source="openai-agents:new_items",
            payload={"tool": _TOOL, "call_id": "call_preissued", "arguments": "{}"},
        ),
        EvidenceEvent(
            sequence=2,
            kind=EvidenceKind.TOOL_RESULT,
            source="openai-agents:new_items",
            payload={"call_id": "call_error", "output": {"type": "text", "text": "error"}},
        ),
        EvidenceEvent(
            sequence=3,
            kind=EvidenceKind.TOOL_RESULT,
            source="openai-agents:new_items",
            payload={"call_id": "call_preissued", "output": {"type": "text", "text": "benign"}},
        ),
    )

    with pytest.raises(AdapterPreconditionError) as exc_info:
        _attach_verified_recovery_bridge(
            AdapterResult(events=events),
            scenario=scenario(),
            fault=controlled_fault,
            protocol_receipt=protocol_receipt(controlled_fault),
            error_arguments={"customer_id": "7"},
            retry_arguments={"customer_id": "7"},
            expected_recovery_text="benign",
        )

    assert exc_info.value.code == "mcp_error_retry_causality_unverified"
    assert "only after" in exc_info.value.reason
