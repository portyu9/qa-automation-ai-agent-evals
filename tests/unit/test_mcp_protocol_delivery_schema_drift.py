from __future__ import annotations

import pytest

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_schema_bridge import (
    MCPAgentToolSchemaDriftReceipt,
    create_schema_drift_protocol_receipt,
)
from agent_evals.mcp.delivery import ProtocolDeliveryError, verify_protocol_delivery
from agent_evals.mcp.models import MCPFaultKind, MCPFaultSpec

_TOOL = "lookup_customer"
_SCENARIO = "a" * 64
_SUBJECT = "b" * 64
_TTL_MS = 60_000
_STALE_TEXT = "schema rejected"
_RECOVERY_TEXT = "replacement:7:true"


def fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="unit-protocol-delivery-schema-drift",
        revision="1",
        kind=MCPFaultKind.TOOL_SCHEMA_DRIFT,
        tool_name=_TOOL,
        payload={
            "ttl_ms": _TTL_MS,
            "initial_required": {"query": "string"},
            "replacement_required": {
                "customer_id": "integer",
                "include_history": "boolean",
            },
        },
    )


def initial_schema() -> dict[str, object]:
    return {
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }


def replacement_schema() -> dict[str, object]:
    return {
        "properties": {
            "customer_id": {"type": "integer"},
            "include_history": {"type": "boolean"},
        },
        "required": ["customer_id", "include_history"],
    }


def receipt() -> MCPAgentToolSchemaDriftReceipt:
    controlled_fault = fault()
    protocol_receipt = create_schema_drift_protocol_receipt(
        fault=controlled_fault,
        ttl_ms=_TTL_MS,
        initial_schema=initial_schema(),
        cached_schema=initial_schema(),
        refreshed_schema=replacement_schema(),
        stale_protocol_text=_STALE_TEXT,
        protocol_recovery_text=_RECOVERY_TEXT,
        initial_list_ordinal=0,
        schema_swap_ordinal=1,
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
        recovery_call_ordinal=6,
    )
    return MCPAgentToolSchemaDriftReceipt.create(
        scenario_identity=_SCENARIO,
        fault=controlled_fault,
        protocol_receipt=protocol_receipt,
        agent_tool_name=_TOOL,
        stale_call_id="call_stale",
        recovery_call_id="call_recovery",
        mcp_cache_hint_ttl_ms=_TTL_MS,
        initial_schema=initial_schema(),
        cached_schema=initial_schema(),
        refreshed_schema=replacement_schema(),
        stale_arguments={"query": "stale"},
        recovery_arguments={"customer_id": 7, "include_history": True},
        stale_protocol_text=_STALE_TEXT,
        agent_error_output={"type": "text", "text": _STALE_TEXT},
        protocol_recovery_text=_RECOVERY_TEXT,
        agent_recovery_output={"type": "text", "text": _RECOVERY_TEXT},
        initial_list_ordinal=0,
        schema_swap_ordinal=1,
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
        recovery_call_ordinal=6,
    )


def request(sequence: int, *, call_id: str, arguments: str) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_REQUEST,
        source="adapter:test",
        payload={"tool": _TOOL, "call_id": call_id, "arguments": arguments},
    )


def result(sequence: int, *, call_id: str, text: str) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_RESULT,
        source="adapter:test",
        payload={"call_id": call_id, "output": {"type": "text", "text": text}},
    )


def evidence(
    payload: dict[str, object] | None = None,
    *,
    stale_arguments: str = '{"query":"stale"}',
    recovery_text: str = _RECOVERY_TEXT,
) -> TrialEvidence:
    bridge = receipt()
    delivery_payload = payload or bridge.model_dump(mode="json")
    delivery = EvidenceEvent(
        sequence=4,
        kind=EvidenceKind.PROTOCOL_DELIVERY,
        source="bridge:mcp-agent:tool-schema-drift",
        payload=delivery_payload,
    )
    return TrialEvidence(
        trial_id="schema-drift-delivery",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        events=(
            request(0, call_id=bridge.stale_call_id, arguments=stale_arguments),
            result(1, call_id=bridge.stale_call_id, text=_STALE_TEXT),
            request(
                2,
                call_id=bridge.recovery_call_id,
                arguments='{"customer_id":7,"include_history":true}',
            ),
            result(3, call_id=bridge.recovery_call_id, text=recovery_text),
            delivery,
        ),
        final_state={},
    )


def test_protocol_delivery_revalidates_schema_drift_receipt_and_normalized_relation() -> None:
    verified = verify_protocol_delivery(evidence())
    assert len(verified) == 1
    assert isinstance(verified[0], MCPAgentToolSchemaDriftReceipt)


def test_protocol_delivery_rejects_schema_drift_receipt_only_replay() -> None:
    bridge = receipt()
    detached = TrialEvidence(
        trial_id="schema-drift-detached",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        events=(bridge.to_event(sequence=0),),
    )
    with pytest.raises(ProtocolDeliveryError, match="exactly two normalized target requests"):
        verify_protocol_delivery(detached)


def test_protocol_delivery_rejects_changed_schema_drift_arguments() -> None:
    with pytest.raises(ProtocolDeliveryError, match="stale request arguments"):
        verify_protocol_delivery(evidence(stale_arguments='{"query":"changed"}'))


def test_protocol_delivery_rejects_changed_schema_drift_recovery_output() -> None:
    with pytest.raises(ProtocolDeliveryError, match="recovery output"):
        verify_protocol_delivery(evidence(recovery_text="changed"))


def test_protocol_delivery_rejects_tampered_schema_drift_relation() -> None:
    tampered = receipt().model_dump(mode="json")
    tampered["refreshed_list_ordinal"] = 2
    with pytest.raises(ProtocolDeliveryError, match="malformed or internally inconsistent"):
        verify_protocol_delivery(evidence(tampered))


def test_protocol_delivery_rejects_schema_drift_scenario_mismatch() -> None:
    bridge = receipt().model_dump(mode="json")
    bridge["scenario_identity"] = "c" * 64
    with pytest.raises(ProtocolDeliveryError):
        verify_protocol_delivery(evidence(bridge))
