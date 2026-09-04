from __future__ import annotations

import pytest

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
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
        stale_call_ordinal=2,
        cache_invalidation_ordinal=3,
        refreshed_list_ordinal=4,
        recovery_call_ordinal=5,
    )
    return MCPAgentToolSchemaDriftReceipt.create(
        scenario_identity=_SCENARIO,
        fault=controlled_fault,
        protocol_receipt=protocol_receipt,
        agent_tool_name=_TOOL,
        stale_call_id="call_stale",
        recovery_call_id="call_recovery",
        ttl_ms=_TTL_MS,
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
        stale_call_ordinal=2,
        cache_invalidation_ordinal=3,
        refreshed_list_ordinal=4,
        recovery_call_ordinal=5,
    )


def evidence(payload: dict[str, object] | None = None) -> TrialEvidence:
    bridge = receipt()
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.PROTOCOL_DELIVERY,
        source="bridge:mcp-agent:tool-schema-drift",
        payload=payload or bridge.model_dump(mode="json"),
    )
    return TrialEvidence(
        trial_id="schema-drift-delivery",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        events=(event,),
        final_state={},
        verdict=TrialVerdict.PASS,
    )


def test_protocol_delivery_revalidates_schema_drift_receipt() -> None:
    verified = verify_protocol_delivery(evidence())
    assert len(verified) == 1
    assert isinstance(verified[0], MCPAgentToolSchemaDriftReceipt)


def test_protocol_delivery_rejects_tampered_schema_drift_relation() -> None:
    tampered = receipt().model_dump(mode="json")
    tampered["refreshed_list_ordinal"] = 2

    with pytest.raises(ProtocolDeliveryError, match="malformed or internally inconsistent"):
        verify_protocol_delivery(evidence(tampered))


def test_protocol_delivery_rejects_schema_drift_scenario_mismatch() -> None:
    bridge = receipt().model_dump(mode="json")
    bridge["scenario_identity"] = "c" * 64

    # Re-rooting is intentionally not attempted here: either the receipt validation or the outer
    # scenario-binding check must reject a delivery that no longer belongs to this trial.
    with pytest.raises(ProtocolDeliveryError):
        verify_protocol_delivery(evidence(bridge))
