from __future__ import annotations

import pytest

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_bridge import MCPAgentToolResultReceipt
from agent_evals.mcp.agent_error_bridge import MCPAgentToolErrorRecoveryReceipt
from agent_evals.mcp.agent_metadata_bridge import MCPAgentToolMetadataReceipt
from agent_evals.mcp.delivery import ProtocolDeliveryError, verify_protocol_delivery
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_SCENARIO_ID = "a" * 64
_SUBJECT_ID = "b" * 64
_TOOL = "lookup_customer"
_RESULT_TEXT = '{"value":"controlled"}'
_ERROR_PAYLOAD = '{"code":"TRANSIENT"}'
_ERROR_TEXT = f"Error executing tool {_TOOL}: {_ERROR_PAYLOAD}"
_METADATA_SCHEMA = {
    "type": "object",
    "properties": {"customer_id": {"type": "string"}},
    "required": ["customer_id"],
}


def result_bridge() -> MCPAgentToolResultReceipt:
    fault = MCPFaultSpec.from_payload(
        fault_id="unit-protocol-result",
        revision="1",
        kind=MCPFaultKind.TOOL_RESULT_POISON,
        tool_name=_TOOL,
        payload={"value": "controlled"},
    )
    protocol = MCPFaultReceipt.create(
        fault=fault,
        protocol_version="2026-07-28",
        injection_point=f"mcp:2026-07-28:tools/call:{_TOOL}:result.content[0].text",
        observed_text=fault.payload_json,
    )
    return MCPAgentToolResultReceipt.create(
        scenario_identity=_SCENARIO_ID,
        protocol_receipt=protocol,
        agent_tool_name=_TOOL,
        agent_call_id="call_result",
        agent_output={"type": "text", "text": fault.payload_json},
    )


def error_recovery_bridge() -> MCPAgentToolErrorRecoveryReceipt:
    fault = MCPFaultSpec.from_payload(
        fault_id="unit-protocol-error-recovery",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={"code": "TRANSIENT"},
    )
    error_text = f"Error executing tool {_TOOL}: {fault.payload_json}"
    protocol = MCPFaultReceipt.create(
        fault=fault,
        protocol_version="2026-07-28",
        injection_point=(f"mcp:2026-07-28:tools/call:{_TOOL}:error.content[0].text:message-suffix"),
        observed_text=error_text,
    )
    return MCPAgentToolErrorRecoveryReceipt.create(
        scenario_identity=_SCENARIO_ID,
        fault=fault,
        protocol_receipt=protocol,
        agent_tool_name=_TOOL,
        error_call_id="call_error",
        retry_call_id="call_retry",
        error_arguments={"customer_id": "7"},
        retry_arguments={"customer_id": "7"},
        agent_error_output={"type": "text", "text": error_text},
        expected_recovery_text="benign",
        agent_recovery_output={"type": "text", "text": "benign"},
    )


def metadata_bridge() -> MCPAgentToolMetadataReceipt:
    fault = MCPFaultSpec.from_payload(
        fault_id="unit-protocol-metadata",
        revision="1",
        kind=MCPFaultKind.TOOL_METADATA_POISON,
        tool_name=_TOOL,
        payload={"instruction": "controlled metadata"},
    )
    protocol = MCPFaultReceipt.create(
        fault=fault,
        protocol_version="2026-07-28",
        injection_point=f"mcp:2026-07-28:tools/list:{_TOOL}:description",
        observed_text=fault.payload_json,
    )
    return MCPAgentToolMetadataReceipt.create(
        scenario_identity=_SCENARIO_ID,
        protocol_receipt=protocol,
        agent_tool_name=_TOOL,
        protocol_schema=_METADATA_SCHEMA,
        model_description=fault.payload_json,
        model_schema=_METADATA_SCHEMA,
        model_snapshot_ordinal=0,
    )


def trial(*events: EvidenceEvent, scenario_identity: str = _SCENARIO_ID) -> TrialEvidence:
    return TrialEvidence(
        trial_id="protocol-delivery",
        subject_identity=_SUBJECT_ID,
        scenario_identity=scenario_identity,
        events=events,
    )


def request(sequence: int, *, call_id: str, arguments: str, tool: str = _TOOL) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_REQUEST,
        source="adapter:test",
        payload={"tool": tool, "call_id": call_id, "arguments": arguments},
    )


def result(sequence: int, *, call_id: str, text: str) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_RESULT,
        source="adapter:test",
        payload={"call_id": call_id, "output": {"type": "text", "text": text}},
    )


def result_evidence(receipt: MCPAgentToolResultReceipt | None = None) -> TrialEvidence:
    bridge = receipt or result_bridge()
    return trial(
        request(0, call_id=bridge.agent_call_id, arguments='{"customer_id":"7"}'),
        bridge.to_event(sequence=1),
        result(2, call_id=bridge.agent_call_id, text=_RESULT_TEXT),
    )


def recovery_evidence(
    receipt: MCPAgentToolErrorRecoveryReceipt | None = None,
    *,
    retry_arguments: str = '{"customer_id":"7"}',
    recovery_text: str = "benign",
) -> TrialEvidence:
    bridge = receipt or error_recovery_bridge()
    return trial(
        request(0, call_id=bridge.error_call_id, arguments='{"customer_id":"7"}'),
        result(1, call_id=bridge.error_call_id, text=_ERROR_TEXT),
        request(2, call_id=bridge.retry_call_id, arguments=retry_arguments),
        result(3, call_id=bridge.retry_call_id, text=recovery_text),
        bridge.to_event(sequence=4),
    )


def test_protocol_delivery_verifier_accepts_result_bridge_with_bound_evidence() -> None:
    bridge = result_bridge()
    assert verify_protocol_delivery(result_evidence(bridge)) == (bridge,)


def test_protocol_delivery_verifier_accepts_error_recovery_with_bound_evidence() -> None:
    bridge = error_recovery_bridge()
    assert verify_protocol_delivery(recovery_evidence(bridge)) == (bridge,)


def test_protocol_delivery_verifier_accepts_metadata_bridge() -> None:
    bridge = metadata_bridge()
    assert verify_protocol_delivery(trial(bridge.to_event(sequence=0))) == (bridge,)


def test_result_bridge_rejects_receipt_only_replay() -> None:
    bridge = result_bridge()
    with pytest.raises(ProtocolDeliveryError, match="exactly one normalized target request"):
        verify_protocol_delivery(trial(bridge.to_event(sequence=0)))


def test_result_bridge_rejects_changed_normalized_output() -> None:
    bridge = result_bridge()
    evidence = trial(
        request(0, call_id=bridge.agent_call_id, arguments='{"customer_id":"7"}'),
        bridge.to_event(sequence=1),
        result(2, call_id=bridge.agent_call_id, text="changed"),
    )
    with pytest.raises(ProtocolDeliveryError, match="receipt-bound observation"):
        verify_protocol_delivery(evidence)


def test_error_recovery_bridge_rejects_changed_retry_arguments() -> None:
    with pytest.raises(ProtocolDeliveryError, match="retry arguments"):
        verify_protocol_delivery(recovery_evidence(retry_arguments='{"customer_id":"8"}'))


def test_error_recovery_bridge_rejects_changed_recovery_output() -> None:
    with pytest.raises(ProtocolDeliveryError, match="recovery output"):
        verify_protocol_delivery(recovery_evidence(recovery_text="changed"))


def test_metadata_delivery_allows_leading_pre_model_attack_delivery() -> None:
    metadata = metadata_bridge()
    evidence = trial(
        EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.ATTACK_DELIVERY,
            source="injector:test:pre-model",
            payload={"phase": "pre-model"},
        ),
        metadata.to_event(sequence=1),
        EvidenceEvent(
            sequence=2,
            kind=EvidenceKind.OUTPUT,
            source="adapter:test",
            payload={"output": "safe"},
        ),
    )
    assert verify_protocol_delivery(evidence) == (metadata,)


def test_metadata_delivery_rejects_replayed_event_after_behavior() -> None:
    metadata = metadata_bridge()
    evidence = trial(
        EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.OUTPUT,
            source="adapter:test",
            payload={"output": "already happened"},
        ),
        metadata.to_event(sequence=1),
    )
    with pytest.raises(ProtocolDeliveryError, match="after normalized behavioral evidence"):
        verify_protocol_delivery(evidence)


def test_protocol_delivery_verifier_rejects_unknown_source() -> None:
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.PROTOCOL_DELIVERY,
        source="bridge:unknown",
        payload={},
    )
    with pytest.raises(ProtocolDeliveryError, match="unsupported protocol delivery"):
        verify_protocol_delivery(trial(event))


def test_protocol_delivery_verifier_rejects_malformed_known_receipt() -> None:
    receipt = result_bridge()
    payload = receipt.model_dump(mode="json")
    payload["receipt_root"] = "0" * 64
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.PROTOCOL_DELIVERY,
        source="bridge:mcp-agent:tool-result",
        payload=payload,
    )
    with pytest.raises(ProtocolDeliveryError, match="malformed or internally inconsistent"):
        verify_protocol_delivery(trial(event))


def test_protocol_delivery_verifier_rejects_malformed_metadata_receipt() -> None:
    receipt = metadata_bridge()
    payload = receipt.model_dump(mode="json")
    payload["model_schema_sha256"] = "0" * 64
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.PROTOCOL_DELIVERY,
        source="bridge:mcp-agent:tool-metadata",
        payload=payload,
    )
    with pytest.raises(ProtocolDeliveryError, match="malformed or internally inconsistent"):
        verify_protocol_delivery(trial(event))


def test_protocol_delivery_verifier_rejects_scenario_identity_mismatch() -> None:
    event = result_bridge().to_event(sequence=0)
    with pytest.raises(ProtocolDeliveryError, match="scenario identity"):
        verify_protocol_delivery(trial(event, scenario_identity="c" * 64))
