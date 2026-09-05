from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_stale_cache_bridge import (
    MCPAgentToolStaleCacheReceipt,
    create_stale_cache_protocol_receipt,
)
from agent_evals.mcp.delivery import ProtocolDeliveryError, verify_protocol_delivery
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_TOOL = "lookup_customer"
_TTL_MS = 60_000
_STALE_TEXT = "Error executing tool lookup_customer: unknown tool 'lookup_customer'"


def _fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="stale-cache-agent-bridge",
        revision="1",
        kind=MCPFaultKind.TOOL_LIST_STALE_CACHE,
        tool_name=_TOOL,
        payload={"ttl_ms": _TTL_MS},
    )


def _protocol_receipt() -> MCPFaultReceipt:
    return create_stale_cache_protocol_receipt(
        fault=_fault(),
        ttl_ms=_TTL_MS,
        initial_tool_names=(_TOOL,),
        cached_tool_names=(_TOOL,),
        refreshed_tool_names=(),
    )


def _bridge(*, scenario_identity: str = "a" * 64) -> MCPAgentToolStaleCacheReceipt:
    return MCPAgentToolStaleCacheReceipt.create(
        scenario_identity=scenario_identity,
        fault=_fault(),
        protocol_receipt=_protocol_receipt(),
        tool_name=_TOOL,
        stale_call_id="call-stale",
        mcp_cache_hint_ttl_ms=_TTL_MS,
        stale_arguments={"query": "stale"},
        stale_protocol_text=_STALE_TEXT,
        agent_error_output={"type": "text", "text": _STALE_TEXT},
        initial_model_tool_names=(_TOOL,),
        refreshed_model_tool_names=(),
        initial_list_ordinal=0,
        removal_ordinal=1,
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
    )


def _evidence(
    *,
    scenario_identity: str = "a" * 64,
    arguments: str = '{"query":"stale"}',
    result_text: str = _STALE_TEXT,
    delivery_payload: dict[str, object] | None = None,
    delivery_sequence: int = 2,
) -> TrialEvidence:
    receipt = _bridge(scenario_identity=scenario_identity)
    delivery = receipt.to_event(sequence=delivery_sequence)
    if delivery_payload is not None:
        delivery = EvidenceEvent(
            sequence=delivery_sequence,
            kind=EvidenceKind.PROTOCOL_DELIVERY,
            source=delivery.source,
            payload=delivery_payload,
        )

    request = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.TOOL_REQUEST,
        source="openai-agents",
        payload={
            "tool": _TOOL,
            "call_id": "call-stale",
            "arguments": arguments,
        },
    )
    result = EvidenceEvent(
        sequence=1,
        kind=EvidenceKind.TOOL_RESULT,
        source="openai-agents",
        payload={
            "tool": _TOOL,
            "call_id": "call-stale",
            "output": {"type": "text", "text": result_text},
        },
    )
    if delivery_sequence == 2:
        events = (request, result, delivery)
    elif delivery_sequence == 1:
        delivery = delivery.model_copy(update={"sequence": 1})
        result = result.model_copy(update={"sequence": 2})
        events = (request, delivery, result)
    else:
        raise ValueError("test helper supports delivery sequence 1 or 2")

    return TrialEvidence(
        trial_id="stale-cache",
        subject_identity="b" * 64,
        scenario_identity=scenario_identity,
        events=events,
    )


def test_stale_cache_receipt_binds_removal_without_raw_rejection_or_arguments() -> None:
    receipt = _bridge()

    assert receipt.tool_name == _TOOL
    assert receipt.stale_call_id == "call-stale"
    assert receipt.protocol_receipt.kind is MCPFaultKind.TOOL_LIST_STALE_CACHE
    serialized = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)
    assert _STALE_TEXT not in serialized
    assert '"query": "stale"' not in serialized


def test_stale_cache_protocol_receipt_rejects_non_stale_cached_discovery() -> None:
    with pytest.raises(ValueError, match="cached discovery"):
        create_stale_cache_protocol_receipt(
            fault=_fault(),
            ttl_ms=_TTL_MS,
            initial_tool_names=(_TOOL,),
            cached_tool_names=(),
            refreshed_tool_names=(),
        )


def test_stale_cache_protocol_receipt_rejects_refresh_that_still_advertises_target() -> None:
    with pytest.raises(ValueError, match="target absence"):
        create_stale_cache_protocol_receipt(
            fault=_fault(),
            ttl_ms=_TTL_MS,
            initial_tool_names=(_TOOL,),
            cached_tool_names=(_TOOL,),
            refreshed_tool_names=(_TOOL,),
        )


def test_stale_cache_receipt_rejects_changed_arguments() -> None:
    with pytest.raises(ValueError, match="bound stale arguments"):
        MCPAgentToolStaleCacheReceipt.create(
            scenario_identity="a" * 64,
            fault=_fault(),
            protocol_receipt=_protocol_receipt(),
            tool_name=_TOOL,
            stale_call_id="call-stale",
            mcp_cache_hint_ttl_ms=_TTL_MS,
            stale_arguments={"query": "different"},
            stale_protocol_text=_STALE_TEXT,
            agent_error_output={"type": "text", "text": _STALE_TEXT},
            initial_model_tool_names=(_TOOL,),
            refreshed_model_tool_names=(),
            initial_list_ordinal=0,
            removal_ordinal=1,
            cached_list_ordinal=2,
            stale_call_ordinal=3,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=5,
        )


def test_stale_cache_receipt_rejects_protocol_model_rejection_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match MCP observation"):
        MCPAgentToolStaleCacheReceipt.create(
            scenario_identity="a" * 64,
            fault=_fault(),
            protocol_receipt=_protocol_receipt(),
            tool_name=_TOOL,
            stale_call_id="call-stale",
            mcp_cache_hint_ttl_ms=_TTL_MS,
            stale_arguments={"query": "stale"},
            stale_protocol_text=_STALE_TEXT,
            agent_error_output={"type": "text", "text": "different rejection"},
            initial_model_tool_names=(_TOOL,),
            refreshed_model_tool_names=(),
            initial_list_ordinal=0,
            removal_ordinal=1,
            cached_list_ordinal=2,
            stale_call_ordinal=3,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=5,
        )


def test_stale_cache_receipt_rejects_refreshed_model_still_advertising_target() -> None:
    with pytest.raises(ValueError, match="target absence"):
        MCPAgentToolStaleCacheReceipt.create(
            scenario_identity="a" * 64,
            fault=_fault(),
            protocol_receipt=_protocol_receipt(),
            tool_name=_TOOL,
            stale_call_id="call-stale",
            mcp_cache_hint_ttl_ms=_TTL_MS,
            stale_arguments={"query": "stale"},
            stale_protocol_text=_STALE_TEXT,
            agent_error_output={"type": "text", "text": _STALE_TEXT},
            initial_model_tool_names=(_TOOL,),
            refreshed_model_tool_names=(_TOOL,),
            initial_list_ordinal=0,
            removal_ordinal=1,
            cached_list_ordinal=2,
            stale_call_ordinal=3,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=5,
        )


def test_stale_cache_receipt_rejects_noncausal_protocol_chronology() -> None:
    with pytest.raises(ValueError, match="chronology"):
        MCPAgentToolStaleCacheReceipt.create(
            scenario_identity="a" * 64,
            fault=_fault(),
            protocol_receipt=_protocol_receipt(),
            tool_name=_TOOL,
            stale_call_id="call-stale",
            mcp_cache_hint_ttl_ms=_TTL_MS,
            stale_arguments={"query": "stale"},
            stale_protocol_text=_STALE_TEXT,
            agent_error_output={"type": "text", "text": _STALE_TEXT},
            initial_model_tool_names=(_TOOL,),
            refreshed_model_tool_names=(),
            initial_list_ordinal=0,
            removal_ordinal=1,
            cached_list_ordinal=3,
            stale_call_ordinal=2,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=5,
        )


def test_stale_cache_receipt_rejects_wrong_ttl_binding() -> None:
    with pytest.raises(ValueError, match="TTL"):
        MCPAgentToolStaleCacheReceipt.create(
            scenario_identity="a" * 64,
            fault=_fault(),
            protocol_receipt=_protocol_receipt(),
            tool_name=_TOOL,
            stale_call_id="call-stale",
            mcp_cache_hint_ttl_ms=1,
            stale_arguments={"query": "stale"},
            stale_protocol_text=_STALE_TEXT,
            agent_error_output={"type": "text", "text": _STALE_TEXT},
            initial_model_tool_names=(_TOOL,),
            refreshed_model_tool_names=(),
            initial_list_ordinal=0,
            removal_ordinal=1,
            cached_list_ordinal=2,
            stale_call_ordinal=3,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=5,
        )


def test_stale_cache_receipt_root_tampering_is_rejected() -> None:
    payload = _bridge().model_dump(mode="json")
    payload["receipt_root"] = "0" * 64

    with pytest.raises(ValidationError, match="bridge root"):
        MCPAgentToolStaleCacheReceipt.model_validate(payload)


def test_stale_cache_protocol_receipt_wrong_boundary_is_rejected() -> None:
    payload = _protocol_receipt().model_dump(mode="json")
    payload["injection_point"] = "mcp:2026-07-28:wrong-boundary"
    payload["receipt_root"] = MCPFaultReceipt.create(
        fault=_fault(),
        protocol_version="2026-07-28",
        injection_point=payload["injection_point"],
        observed_text="irrelevant",
    ).receipt_root

    with pytest.raises(ValidationError):
        MCPAgentToolStaleCacheReceipt.create(
            scenario_identity="a" * 64,
            fault=_fault(),
            protocol_receipt=MCPFaultReceipt.model_construct(**payload),
            tool_name=_TOOL,
            stale_call_id="call-stale",
            mcp_cache_hint_ttl_ms=_TTL_MS,
            stale_arguments={"query": "stale"},
            stale_protocol_text=_STALE_TEXT,
            agent_error_output={"type": "text", "text": _STALE_TEXT},
            initial_model_tool_names=(_TOOL,),
            refreshed_model_tool_names=(),
            initial_list_ordinal=0,
            removal_ordinal=1,
            cached_list_ordinal=2,
            stale_call_ordinal=3,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=5,
        )


def test_protocol_delivery_revalidates_stale_cache_receipt_and_scenario() -> None:
    evidence = _evidence()
    receipt = _bridge()

    assert verify_protocol_delivery(evidence) == (receipt,)

    changed = evidence.model_copy(update={"scenario_identity": "c" * 64})
    with pytest.raises(ProtocolDeliveryError, match="scenario identity"):
        verify_protocol_delivery(changed)


def test_stale_cache_delivery_payload_tampering_fails_closed() -> None:
    receipt = _bridge()
    payload = receipt.model_dump(mode="json")
    payload["tool_name"] = "tampered"
    tampered = _evidence(delivery_payload=payload)

    with pytest.raises(ProtocolDeliveryError, match="malformed or internally inconsistent"):
        verify_protocol_delivery(tampered)


def test_stale_cache_replay_rejects_changed_normalized_arguments() -> None:
    with pytest.raises(ProtocolDeliveryError, match="arguments"):
        verify_protocol_delivery(_evidence(arguments='{"query":"changed"}'))


def test_stale_cache_replay_rejects_changed_normalized_rejection() -> None:
    with pytest.raises(ProtocolDeliveryError, match="normalized rejection"):
        verify_protocol_delivery(_evidence(result_text="different rejection"))


def test_stale_cache_replay_rejects_delivery_before_stale_result() -> None:
    with pytest.raises(ProtocolDeliveryError, match="must occur after"):
        verify_protocol_delivery(_evidence(delivery_sequence=1))
