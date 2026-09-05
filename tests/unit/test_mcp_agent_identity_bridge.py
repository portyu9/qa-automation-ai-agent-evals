from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_identity_bridge import (
    MCPAgentToolIdentityDriftReceipt,
    create_identity_drift_protocol_receipt,
)
from agent_evals.mcp.delivery import ProtocolDeliveryError, verify_protocol_delivery
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_OLD = "lookup_customer"
_NEW = "lookup_customer_v2"
_STALE_TEXT = "Error executing tool lookup_customer: unknown tool 'lookup_customer'"
_RECOVERY_TEXT = "replacement:fresh"


def _fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="identity-drift-agent-bridge",
        revision="1",
        kind=MCPFaultKind.TOOL_IDENTITY_DRIFT,
        tool_name=_OLD,
        payload={"ttl_ms": 60_000, "replacement_tool_name": _NEW},
    )


def _protocol_receipt() -> MCPFaultReceipt:
    return create_identity_drift_protocol_receipt(
        fault=_fault(),
        ttl_ms=60_000,
        original_tool_name=_OLD,
        replacement_tool_name=_NEW,
        stale_protocol_text=_STALE_TEXT,
        protocol_recovery_text=_RECOVERY_TEXT,
        initial_list_ordinal=0,
        identity_swap_ordinal=1,
        stale_call_ordinal=2,
        cache_invalidation_ordinal=3,
        refreshed_list_ordinal=4,
        recovery_call_ordinal=5,
    )


def _bridge(*, scenario_identity: str = "a" * 64) -> MCPAgentToolIdentityDriftReceipt:
    return MCPAgentToolIdentityDriftReceipt.create(
        scenario_identity=scenario_identity,
        fault=_fault(),
        protocol_receipt=_protocol_receipt(),
        original_tool_name=_OLD,
        replacement_tool_name=_NEW,
        stale_call_id="call-old",
        recovery_call_id="call-new",
        ttl_ms=60_000,
        stale_arguments={"query": "stale"},
        recovery_arguments={"query": "fresh"},
        stale_protocol_text=_STALE_TEXT,
        agent_error_output={"type": "text", "text": _STALE_TEXT},
        protocol_recovery_text=_RECOVERY_TEXT,
        agent_recovery_output={"type": "text", "text": _RECOVERY_TEXT},
        initial_model_tool_names=(_OLD,),
        refreshed_model_tool_names=(_NEW,),
        initial_list_ordinal=0,
        identity_swap_ordinal=1,
        stale_call_ordinal=2,
        cache_invalidation_ordinal=3,
        refreshed_list_ordinal=4,
        recovery_call_ordinal=5,
    )


def _request(sequence: int, *, tool: str, call_id: str, arguments: str) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_REQUEST,
        source="adapter:test",
        payload={"tool": tool, "call_id": call_id, "arguments": arguments},
    )


def _result(sequence: int, *, call_id: str, text: str) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_RESULT,
        source="adapter:test",
        payload={"call_id": call_id, "output": {"type": "text", "text": text}},
    )


def _evidence(
    receipt: MCPAgentToolIdentityDriftReceipt | None = None,
    *,
    recovery_tool: str = _NEW,
    recovery_arguments: str = '{"query":"fresh"}',
    recovery_text: str = _RECOVERY_TEXT,
) -> TrialEvidence:
    bridge = receipt or _bridge()
    return TrialEvidence(
        trial_id="identity-drift",
        subject_identity="b" * 64,
        scenario_identity=bridge.scenario_identity,
        events=(
            _request(
                0,
                tool=_OLD,
                call_id=bridge.stale_call_id,
                arguments='{"query":"stale"}',
            ),
            _result(1, call_id=bridge.stale_call_id, text=_STALE_TEXT),
            _request(
                2,
                tool=recovery_tool,
                call_id=bridge.recovery_call_id,
                arguments=recovery_arguments,
            ),
            _result(3, call_id=bridge.recovery_call_id, text=recovery_text),
            bridge.to_event(sequence=4),
        ),
    )


def test_identity_drift_receipt_binds_exact_relation_without_raw_outputs() -> None:
    receipt = _bridge()

    assert receipt.original_tool_name == _OLD
    assert receipt.replacement_tool_name == _NEW
    assert receipt.stale_call_id == "call-old"
    assert receipt.recovery_call_id == "call-new"
    assert receipt.protocol_receipt.kind is MCPFaultKind.TOOL_IDENTITY_DRIFT
    serialized = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)
    assert _STALE_TEXT not in serialized
    assert _RECOVERY_TEXT not in serialized


def test_identity_drift_protocol_receipt_requires_strict_chronology() -> None:
    with pytest.raises(ValueError, match="chronology"):
        create_identity_drift_protocol_receipt(
            fault=_fault(),
            ttl_ms=60_000,
            original_tool_name=_OLD,
            replacement_tool_name=_NEW,
            stale_protocol_text=_STALE_TEXT,
            protocol_recovery_text=_RECOVERY_TEXT,
            initial_list_ordinal=0,
            identity_swap_ordinal=1,
            stale_call_ordinal=2,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=3,
            recovery_call_ordinal=5,
        )


def test_identity_drift_receipt_rejects_reused_call_identity() -> None:
    with pytest.raises(ValueError, match="distinct OpenAI call IDs"):
        MCPAgentToolIdentityDriftReceipt.create(
            scenario_identity="a" * 64,
            fault=_fault(),
            protocol_receipt=_protocol_receipt(),
            original_tool_name=_OLD,
            replacement_tool_name=_NEW,
            stale_call_id="same-call",
            recovery_call_id="same-call",
            ttl_ms=60_000,
            stale_arguments={"query": "stale"},
            recovery_arguments={"query": "fresh"},
            stale_protocol_text=_STALE_TEXT,
            agent_error_output={"type": "text", "text": _STALE_TEXT},
            protocol_recovery_text=_RECOVERY_TEXT,
            agent_recovery_output={"type": "text", "text": _RECOVERY_TEXT},
            initial_model_tool_names=(_OLD,),
            refreshed_model_tool_names=(_NEW,),
            initial_list_ordinal=0,
            identity_swap_ordinal=1,
            stale_call_ordinal=2,
            cache_invalidation_ordinal=3,
            refreshed_list_ordinal=4,
            recovery_call_ordinal=5,
        )


def test_identity_drift_receipt_rejects_model_visible_identity_drift_mismatch() -> None:
    with pytest.raises(ValueError, match="refreshed model-visible controlled identity set"):
        MCPAgentToolIdentityDriftReceipt.create(
            scenario_identity="a" * 64,
            fault=_fault(),
            protocol_receipt=_protocol_receipt(),
            original_tool_name=_OLD,
            replacement_tool_name=_NEW,
            stale_call_id="call-old",
            recovery_call_id="call-new",
            ttl_ms=60_000,
            stale_arguments={"query": "stale"},
            recovery_arguments={"query": "fresh"},
            stale_protocol_text=_STALE_TEXT,
            agent_error_output={"type": "text", "text": _STALE_TEXT},
            protocol_recovery_text=_RECOVERY_TEXT,
            agent_recovery_output={"type": "text", "text": _RECOVERY_TEXT},
            initial_model_tool_names=(_OLD,),
            refreshed_model_tool_names=(_OLD, _NEW),
            initial_list_ordinal=0,
            identity_swap_ordinal=1,
            stale_call_ordinal=2,
            cache_invalidation_ordinal=3,
            refreshed_list_ordinal=4,
            recovery_call_ordinal=5,
        )


def test_identity_drift_receipt_rejects_replacement_name_not_bound_to_fault() -> None:
    with pytest.raises(ValueError, match="unexpected protocol boundary"):
        MCPAgentToolIdentityDriftReceipt.create(
            scenario_identity="a" * 64,
            fault=_fault(),
            protocol_receipt=_protocol_receipt(),
            original_tool_name=_OLD,
            replacement_tool_name="unbound_replacement",
            stale_call_id="call-old",
            recovery_call_id="call-new",
            ttl_ms=60_000,
            stale_arguments={"query": "stale"},
            recovery_arguments={"query": "fresh"},
            stale_protocol_text=_STALE_TEXT,
            agent_error_output={"type": "text", "text": _STALE_TEXT},
            protocol_recovery_text=_RECOVERY_TEXT,
            agent_recovery_output={"type": "text", "text": _RECOVERY_TEXT},
            initial_model_tool_names=(_OLD,),
            refreshed_model_tool_names=("unbound_replacement",),
            initial_list_ordinal=0,
            identity_swap_ordinal=1,
            stale_call_ordinal=2,
            cache_invalidation_ordinal=3,
            refreshed_list_ordinal=4,
            recovery_call_ordinal=5,
        )


def test_identity_drift_receipt_root_tampering_is_rejected() -> None:
    payload = _bridge().model_dump(mode="json")
    payload["receipt_root"] = "0" * 64

    with pytest.raises(ValidationError, match="receipt root"):
        MCPAgentToolIdentityDriftReceipt.model_validate(payload)


def test_protocol_delivery_revalidates_identity_receipt_and_scenario() -> None:
    scenario_identity = "a" * 64
    receipt = _bridge(scenario_identity=scenario_identity)
    evidence = _evidence(receipt)

    assert verify_protocol_delivery(evidence) == (receipt,)

    changed = evidence.model_copy(update={"scenario_identity": "c" * 64})
    with pytest.raises(ProtocolDeliveryError, match="scenario identity"):
        verify_protocol_delivery(changed)


def test_identity_delivery_rejects_receipt_only_replay() -> None:
    receipt = _bridge()
    detached = TrialEvidence(
        trial_id="identity-drift-detached",
        subject_identity="b" * 64,
        scenario_identity=receipt.scenario_identity,
        events=(receipt.to_event(sequence=0),),
    )
    with pytest.raises(ProtocolDeliveryError, match="exactly two normalized controlled requests"):
        verify_protocol_delivery(detached)


def test_identity_delivery_rejects_wrong_recovery_identity() -> None:
    with pytest.raises(ProtocolDeliveryError, match="replacement identity"):
        verify_protocol_delivery(_evidence(recovery_tool=_OLD))


def test_identity_delivery_rejects_changed_recovery_arguments() -> None:
    with pytest.raises(ProtocolDeliveryError, match="recovery request arguments"):
        verify_protocol_delivery(_evidence(recovery_arguments='{"query":"changed"}'))


def test_identity_delivery_rejects_changed_recovery_output() -> None:
    with pytest.raises(ProtocolDeliveryError, match="recovery output"):
        verify_protocol_delivery(_evidence(recovery_text="changed"))


def test_identity_delivery_payload_tampering_fails_closed() -> None:
    receipt = _bridge()
    event = receipt.to_event(sequence=0)
    payload = dict(event.payload)
    payload["replacement_tool_name"] = "tampered"
    tampered = TrialEvidence(
        trial_id="identity-drift-tampered",
        subject_identity="b" * 64,
        scenario_identity="a" * 64,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.PROTOCOL_DELIVERY,
                source=event.source,
                payload=payload,
            ),
        ),
    )

    with pytest.raises(ProtocolDeliveryError, match="malformed or internally inconsistent"):
        verify_protocol_delivery(tampered)
