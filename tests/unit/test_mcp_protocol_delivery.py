from __future__ import annotations

import pytest

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_bridge import MCPAgentToolResultReceipt
from agent_evals.mcp.agent_error_bridge import MCPAgentToolErrorRecoveryReceipt
from agent_evals.mcp.agent_metadata_bridge import MCPAgentToolMetadataReceipt
from agent_evals.mcp.delivery import ProtocolDeliveryError, verify_protocol_delivery
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_SCENARIO_ID = "a" * 64
_TOOL = "lookup_customer"
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


def evidence_for(event: EvidenceEvent, *, scenario_identity: str = _SCENARIO_ID) -> TrialEvidence:
    return TrialEvidence(
        trial_id="protocol-delivery",
        subject_identity="b" * 64,
        scenario_identity=scenario_identity,
        events=(event,),
    )


def test_protocol_delivery_verifier_accepts_all_known_bridge_receipts() -> None:
    result = result_bridge()
    recovery = error_recovery_bridge()
    metadata = metadata_bridge()
    evidence = TrialEvidence(
        trial_id="protocol-delivery",
        subject_identity="b" * 64,
        scenario_identity=_SCENARIO_ID,
        events=(
            result.to_event(sequence=0),
            recovery.to_event(sequence=1),
            metadata.to_event(sequence=2),
        ),
    )

    verified = verify_protocol_delivery(evidence)

    assert verified == (result, recovery, metadata)


def test_metadata_delivery_allows_leading_pre_model_attack_delivery() -> None:
    metadata = metadata_bridge()
    evidence = TrialEvidence(
        trial_id="protocol-delivery-leading-attack",
        subject_identity="b" * 64,
        scenario_identity=_SCENARIO_ID,
        events=(
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
        ),
    )

    assert verify_protocol_delivery(evidence) == (metadata,)


def test_metadata_delivery_rejects_replayed_event_after_behavior() -> None:
    metadata = metadata_bridge()
    evidence = TrialEvidence(
        trial_id="protocol-delivery-reordered",
        subject_identity="b" * 64,
        scenario_identity=_SCENARIO_ID,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.OUTPUT,
                source="adapter:test",
                payload={"output": "already happened"},
            ),
            metadata.to_event(sequence=1),
        ),
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
        verify_protocol_delivery(evidence_for(event))


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
        verify_protocol_delivery(evidence_for(event))


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
        verify_protocol_delivery(evidence_for(event))


def test_protocol_delivery_verifier_rejects_scenario_identity_mismatch() -> None:
    event = result_bridge().to_event(sequence=0)

    with pytest.raises(ProtocolDeliveryError, match="scenario identity"):
        verify_protocol_delivery(evidence_for(event, scenario_identity="c" * 64))
