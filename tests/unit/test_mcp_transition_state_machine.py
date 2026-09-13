from __future__ import annotations

import json

import pytest
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_identity_bridge import (
    MCPAgentToolIdentityDriftReceipt,
    create_identity_drift_protocol_receipt,
)
from agent_evals.mcp.agent_metadata_bridge import MCPAgentToolMetadataReceipt
from agent_evals.mcp.agent_schema_bridge import (
    MCPAgentToolSchemaDriftReceipt,
    create_schema_drift_protocol_receipt,
)
from agent_evals.mcp.agent_stale_cache_bridge import (
    MCPAgentToolStaleCacheReceipt,
    create_stale_cache_protocol_receipt,
)
from agent_evals.mcp.delivery import ProtocolDeliveryError, verify_protocol_delivery
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_SCENARIO = "d" * 64
_SUBJECT = "e" * 64
_TTL_MS = 60_000
_INITIAL_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}
_REPLACEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "integer"},
        "include_history": {"type": "boolean"},
    },
    "required": ["customer_id", "include_history"],
}
_SCHEMA_RECOVERY_TEXT = "replacement:7:true"
_IDENTITY_RECOVERY_TEXT = "replacement:fresh"


def _arguments(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _request(
    sequence: int,
    *,
    tool: str,
    call_id: str,
    arguments: dict[str, object],
) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_REQUEST,
        source="state-machine:mcp",
        payload={"tool": tool, "call_id": call_id, "arguments": _arguments(arguments)},
    )


def _result(sequence: int, *, call_id: str, text: str) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_RESULT,
        source="state-machine:mcp",
        payload={"call_id": call_id, "output": {"type": "text", "text": text}},
    )


def _trial(events: tuple[EvidenceEvent, ...], *, trial_id: str) -> TrialEvidence:
    return TrialEvidence(
        trial_id=trial_id,
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        events=events,
    )


def _resequence(events: list[EvidenceEvent]) -> tuple[EvidenceEvent, ...]:
    return tuple(
        EvidenceEvent.model_validate({**event.model_dump(), "sequence": sequence})
        for sequence, event in enumerate(events)
    )


def _replace_events(evidence: TrialEvidence, events: list[EvidenceEvent]) -> TrialEvidence:
    material = evidence.model_dump()
    material["events"] = [event.model_dump() for event in _resequence(events)]
    return TrialEvidence.model_validate(material)


def _metadata_evidence(
    *,
    tool: str,
    schema: dict[str, object],
    schema_phase: int,
    snapshot_ordinal: int,
) -> TrialEvidence:
    fault = MCPFaultSpec.from_payload(
        fault_id=f"metadata-p{schema_phase}-s{snapshot_ordinal}",
        revision="1",
        kind=MCPFaultKind.TOOL_METADATA_POISON,
        tool_name=tool,
        payload={"instruction": f"controlled-metadata-phase-{schema_phase}"},
    )
    protocol = MCPFaultReceipt.create(
        fault=fault,
        protocol_version="2026-07-28",
        injection_point=f"mcp:2026-07-28:tools/list:{tool}:description",
        observed_text=fault.payload_json,
    )
    receipt = MCPAgentToolMetadataReceipt.create(
        scenario_identity=_SCENARIO,
        protocol_receipt=protocol,
        agent_tool_name=tool,
        protocol_schema=schema,
        model_description=fault.payload_json,
        model_schema=schema,
        model_snapshot_ordinal=snapshot_ordinal,
    )
    return _trial(
        (receipt.to_event(sequence=0),),
        trial_id=f"metadata-p{schema_phase}-s{snapshot_ordinal}",
    )


def _identity_evidence(*, original: str, replacement: str, generation: int) -> TrialEvidence:
    stale_text = f"Error executing tool {original}: unknown tool '{original}'"
    stale_call = f"identity-stale-g{generation}"
    recovery_call = f"identity-recovery-g{generation}"
    fault = MCPFaultSpec.from_payload(
        fault_id=f"identity-g{generation}",
        revision="1",
        kind=MCPFaultKind.TOOL_IDENTITY_DRIFT,
        tool_name=original,
        payload={"ttl_ms": _TTL_MS, "replacement_tool_name": replacement},
    )
    protocol = create_identity_drift_protocol_receipt(
        fault=fault,
        ttl_ms=_TTL_MS,
        original_tool_name=original,
        replacement_tool_name=replacement,
        stale_protocol_text=stale_text,
        protocol_recovery_text=_IDENTITY_RECOVERY_TEXT,
        initial_list_ordinal=0,
        identity_swap_ordinal=1,
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
        recovery_call_ordinal=6,
    )
    receipt = MCPAgentToolIdentityDriftReceipt.create(
        scenario_identity=_SCENARIO,
        fault=fault,
        protocol_receipt=protocol,
        original_tool_name=original,
        replacement_tool_name=replacement,
        stale_call_id=stale_call,
        recovery_call_id=recovery_call,
        mcp_cache_hint_ttl_ms=_TTL_MS,
        stale_arguments={"query": "stale"},
        recovery_arguments={"query": "fresh"},
        stale_protocol_text=stale_text,
        agent_error_output={"type": "text", "text": stale_text},
        protocol_recovery_text=_IDENTITY_RECOVERY_TEXT,
        agent_recovery_output={"type": "text", "text": _IDENTITY_RECOVERY_TEXT},
        initial_model_tool_names=(original,),
        refreshed_model_tool_names=(replacement,),
        initial_list_ordinal=0,
        identity_swap_ordinal=1,
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
        recovery_call_ordinal=6,
    )
    return _trial(
        (
            _request(0, tool=original, call_id=stale_call, arguments={"query": "stale"}),
            _result(1, call_id=stale_call, text=stale_text),
            _request(
                2,
                tool=replacement,
                call_id=recovery_call,
                arguments={"query": "fresh"},
            ),
            _result(3, call_id=recovery_call, text=_IDENTITY_RECOVERY_TEXT),
            receipt.to_event(sequence=4),
        ),
        trial_id=f"identity-g{generation}",
    )


def _schema_evidence(*, tool: str, transition_id: int) -> TrialEvidence:
    stale_text = f"Error executing tool {tool}: Input validation error for replacement schema"
    stale_call = f"schema-stale-{transition_id}"
    recovery_call = f"schema-recovery-{transition_id}"
    fault = MCPFaultSpec.from_payload(
        fault_id=f"schema-transition-{transition_id}",
        revision="1",
        kind=MCPFaultKind.TOOL_SCHEMA_DRIFT,
        tool_name=tool,
        payload={
            "ttl_ms": _TTL_MS,
            "initial_required": {"query": "string"},
            "replacement_required": {
                "customer_id": "integer",
                "include_history": "boolean",
            },
        },
    )
    protocol = create_schema_drift_protocol_receipt(
        fault=fault,
        ttl_ms=_TTL_MS,
        initial_schema=_INITIAL_SCHEMA,
        cached_schema=_INITIAL_SCHEMA,
        refreshed_schema=_REPLACEMENT_SCHEMA,
        stale_protocol_text=stale_text,
        protocol_recovery_text=_SCHEMA_RECOVERY_TEXT,
        initial_list_ordinal=0,
        schema_swap_ordinal=1,
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
        recovery_call_ordinal=6,
    )
    receipt = MCPAgentToolSchemaDriftReceipt.create(
        scenario_identity=_SCENARIO,
        fault=fault,
        protocol_receipt=protocol,
        agent_tool_name=tool,
        stale_call_id=stale_call,
        recovery_call_id=recovery_call,
        mcp_cache_hint_ttl_ms=_TTL_MS,
        initial_schema=_INITIAL_SCHEMA,
        cached_schema=_INITIAL_SCHEMA,
        refreshed_schema=_REPLACEMENT_SCHEMA,
        stale_arguments={"query": "stale"},
        recovery_arguments={"customer_id": 7, "include_history": True},
        stale_protocol_text=stale_text,
        agent_error_output={"type": "text", "text": stale_text},
        protocol_recovery_text=_SCHEMA_RECOVERY_TEXT,
        agent_recovery_output={"type": "text", "text": _SCHEMA_RECOVERY_TEXT},
        initial_list_ordinal=0,
        schema_swap_ordinal=1,
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
        recovery_call_ordinal=6,
    )
    return _trial(
        (
            _request(0, tool=tool, call_id=stale_call, arguments={"query": "stale"}),
            _result(1, call_id=stale_call, text=stale_text),
            _request(
                2,
                tool=tool,
                call_id=recovery_call,
                arguments={"customer_id": 7, "include_history": True},
            ),
            _result(3, call_id=recovery_call, text=_SCHEMA_RECOVERY_TEXT),
            receipt.to_event(sequence=4),
        ),
        trial_id=f"schema-transition-{transition_id}",
    )


def _stale_cache_evidence(*, tool: str, probe_id: int) -> TrialEvidence:
    stale_text = f"Error executing tool {tool}: unknown tool '{tool}'"
    stale_call = f"stale-cache-{probe_id}"
    fault = MCPFaultSpec.from_payload(
        fault_id=f"stale-cache-{probe_id}",
        revision="1",
        kind=MCPFaultKind.TOOL_LIST_STALE_CACHE,
        tool_name=tool,
        payload={"ttl_ms": _TTL_MS},
    )
    protocol = create_stale_cache_protocol_receipt(
        fault=fault,
        ttl_ms=_TTL_MS,
        initial_tool_names=(tool,),
        cached_tool_names=(tool,),
        refreshed_tool_names=(),
    )
    receipt = MCPAgentToolStaleCacheReceipt.create(
        scenario_identity=_SCENARIO,
        fault=fault,
        protocol_receipt=protocol,
        tool_name=tool,
        stale_call_id=stale_call,
        mcp_cache_hint_ttl_ms=_TTL_MS,
        stale_arguments={"query": "stale"},
        stale_protocol_text=stale_text,
        agent_error_output={"type": "text", "text": stale_text},
        initial_model_tool_names=(tool,),
        refreshed_model_tool_names=(),
        initial_list_ordinal=0,
        removal_ordinal=1,
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
    )
    return _trial(
        (
            _request(0, tool=tool, call_id=stale_call, arguments={"query": "stale"}),
            _result(1, call_id=stale_call, text=stale_text),
            receipt.to_event(sequence=2),
        ),
        trial_id=f"stale-cache-{probe_id}",
    )


def _duplicate_delivery(evidence: TrialEvidence) -> TrialEvidence:
    events = list(evidence.events)
    delivery = next(
        event for event in reversed(events) if event.kind is EvidenceKind.PROTOCOL_DELIVERY
    )
    events.append(delivery)
    return _replace_events(evidence, events)


def _current_schema(schema_phase: int) -> dict[str, object]:
    if schema_phase == 0:
        return _INITIAL_SCHEMA
    if schema_phase == 1:
        return _REPLACEMENT_SCHEMA
    raise AssertionError(f"unexpected schema phase: {schema_phase}")


def test_protocol_delivery_rejects_duplicate_receipt_event() -> None:
    evidence = _stale_cache_evidence(tool="lookup_customer_g0", probe_id=0)

    with pytest.raises(ProtocolDeliveryError, match="duplicate protocol delivery receipt root"):
        verify_protocol_delivery(_duplicate_delivery(evidence))


class MCPTransitionStateMachine(RuleBasedStateMachine):
    """Compose the existing bounded MCP fault-lab contracts without widening their claims."""

    def __init__(self) -> None:
        super().__init__()
        self.identity_generation = 0
        self.schema_phase = 0
        self.snapshot_ordinal = 0
        self.reconnect_epoch = 0
        self.probe_id = 0
        self.active_tool = "lookup_customer_g0"
        self.last_behavioral: TrialEvidence | None = None
        self.last_identity: TrialEvidence | None = None
        self.last_schema: TrialEvidence | None = None

    @rule()
    def compatible_metadata_refresh(self) -> None:
        evidence = _metadata_evidence(
            tool=self.active_tool,
            schema=_current_schema(self.schema_phase),
            schema_phase=self.schema_phase,
            snapshot_ordinal=self.snapshot_ordinal,
        )
        receipts = verify_protocol_delivery(evidence)
        assert len(receipts) == 1
        assert isinstance(receipts[0], MCPAgentToolMetadataReceipt)
        assert receipts[0].agent_tool_name == self.active_tool
        assert receipts[0].model_snapshot_ordinal == self.snapshot_ordinal
        self.snapshot_ordinal += 1

    @rule()
    def reconnect_preserves_current_generation(self) -> None:
        previous_tool = self.active_tool
        previous_schema_phase = self.schema_phase
        self.reconnect_epoch += 1
        evidence = _metadata_evidence(
            tool=previous_tool,
            schema=_current_schema(previous_schema_phase),
            schema_phase=previous_schema_phase,
            snapshot_ordinal=self.snapshot_ordinal,
        )
        receipts = verify_protocol_delivery(evidence)
        assert len(receipts) == 1
        assert self.active_tool == previous_tool
        assert self.schema_phase == previous_schema_phase
        self.snapshot_ordinal += 1

    @rule()
    def identity_drift_refreshes_tool_generation(self) -> None:
        next_generation = self.identity_generation + 1
        replacement = f"lookup_customer_g{next_generation}"
        evidence = _identity_evidence(
            original=self.active_tool,
            replacement=replacement,
            generation=next_generation,
        )
        receipts = verify_protocol_delivery(evidence)
        assert len(receipts) == 1
        assert isinstance(receipts[0], MCPAgentToolIdentityDriftReceipt)
        assert receipts[0].original_tool_name == self.active_tool
        assert receipts[0].replacement_tool_name == replacement
        self.identity_generation = next_generation
        self.active_tool = replacement
        self.last_behavioral = evidence
        self.last_identity = evidence
        self.snapshot_ordinal += 1

    @precondition(lambda self: self.schema_phase == 0)
    @rule()
    def schema_drift_refreshes_bounded_v1_contract(self) -> None:
        evidence = _schema_evidence(tool=self.active_tool, transition_id=self.probe_id)
        receipts = verify_protocol_delivery(evidence)
        assert len(receipts) == 1
        assert isinstance(receipts[0], MCPAgentToolSchemaDriftReceipt)
        self.schema_phase = 1
        self.probe_id += 1
        self.last_behavioral = evidence
        self.last_schema = evidence
        self.snapshot_ordinal += 1

    @rule()
    def stale_cache_reuse_is_bound_to_rejection(self) -> None:
        evidence = _stale_cache_evidence(tool=self.active_tool, probe_id=self.probe_id)
        receipts = verify_protocol_delivery(evidence)
        assert len(receipts) == 1
        assert isinstance(receipts[0], MCPAgentToolStaleCacheReceipt)
        assert receipts[0].tool_name == self.active_tool
        self.probe_id += 1
        self.last_behavioral = evidence
        self.snapshot_ordinal += 1

    @precondition(lambda self: self.last_behavioral is not None)
    @rule()
    def duplicate_bridge_receipt_fails_closed(self) -> None:
        assert self.last_behavioral is not None
        with pytest.raises(ProtocolDeliveryError, match="duplicate protocol delivery receipt root"):
            verify_protocol_delivery(_duplicate_delivery(self.last_behavioral))

    @precondition(lambda self: self.last_behavioral is not None)
    @rule()
    def reordered_bridge_receipt_fails_closed(self) -> None:
        assert self.last_behavioral is not None
        events = list(self.last_behavioral.events)
        delivery_index = next(
            index
            for index, event in enumerate(events)
            if event.kind is EvidenceKind.PROTOCOL_DELIVERY
        )
        last_result_index = max(
            index for index, event in enumerate(events) if event.kind is EvidenceKind.TOOL_RESULT
        )
        delivery = events.pop(delivery_index)
        if delivery_index < last_result_index:
            last_result_index -= 1
        events.insert(last_result_index, delivery)
        with pytest.raises(ProtocolDeliveryError):
            verify_protocol_delivery(_replace_events(self.last_behavioral, events))

    @precondition(lambda self: self.last_behavioral is not None)
    @rule()
    def missing_result_fails_closed(self) -> None:
        assert self.last_behavioral is not None
        events = list(self.last_behavioral.events)
        result_index = max(
            index for index, event in enumerate(events) if event.kind is EvidenceKind.TOOL_RESULT
        )
        del events[result_index]
        with pytest.raises(ProtocolDeliveryError):
            verify_protocol_delivery(_replace_events(self.last_behavioral, events))

    @precondition(lambda self: self.last_behavioral is not None)
    @rule()
    def missing_bridge_yields_no_verified_protocol_relation(self) -> None:
        assert self.last_behavioral is not None
        events = [
            event
            for event in self.last_behavioral.events
            if event.kind is not EvidenceKind.PROTOCOL_DELIVERY
        ]
        assert verify_protocol_delivery(_replace_events(self.last_behavioral, events)) == ()

    @precondition(lambda self: self.last_behavioral is not None)
    @rule()
    def changed_call_identity_fails_closed(self) -> None:
        assert self.last_behavioral is not None
        events = list(self.last_behavioral.events)
        request_index = next(
            index for index, event in enumerate(events) if event.kind is EvidenceKind.TOOL_REQUEST
        )
        request = events[request_index]
        payload = dict(request.payload)
        payload["call_id"] = "cross-generation-call"
        events[request_index] = EvidenceEvent.model_validate(
            {**request.model_dump(), "payload": payload}
        )
        with pytest.raises(ProtocolDeliveryError):
            verify_protocol_delivery(_replace_events(self.last_behavioral, events))

    @precondition(lambda self: self.last_identity is not None)
    @rule()
    def old_tool_identity_cannot_replace_refreshed_identity(self) -> None:
        assert self.last_identity is not None
        events = list(self.last_identity.events)
        requests = [
            (index, event)
            for index, event in enumerate(events)
            if event.kind is EvidenceKind.TOOL_REQUEST
        ]
        assert len(requests) == 2
        _, stale_request = requests[0]
        recovery_index, recovery_request = requests[1]
        payload = dict(recovery_request.payload)
        payload["tool"] = stale_request.payload["tool"]
        events[recovery_index] = EvidenceEvent.model_validate(
            {**recovery_request.model_dump(), "payload": payload}
        )
        with pytest.raises(ProtocolDeliveryError, match="replacement identity"):
            verify_protocol_delivery(_replace_events(self.last_identity, events))

    @precondition(lambda self: self.last_schema is not None)
    @rule()
    def stale_schema_arguments_cannot_be_reused_as_refreshed_arguments(self) -> None:
        assert self.last_schema is not None
        events = list(self.last_schema.events)
        requests = [
            (index, event)
            for index, event in enumerate(events)
            if event.kind is EvidenceKind.TOOL_REQUEST
        ]
        assert len(requests) == 2
        _, stale_request = requests[0]
        recovery_index, recovery_request = requests[1]
        payload = dict(recovery_request.payload)
        payload["arguments"] = stale_request.payload["arguments"]
        events[recovery_index] = EvidenceEvent.model_validate(
            {**recovery_request.model_dump(), "payload": payload}
        )
        with pytest.raises(ProtocolDeliveryError, match="arguments"):
            verify_protocol_delivery(_replace_events(self.last_schema, events))

    @invariant()
    def current_generation_is_monotonic_and_last_valid_relation_reverifies(self) -> None:
        assert self.identity_generation >= 0
        assert self.schema_phase in {0, 1}
        assert self.snapshot_ordinal >= 0
        assert self.reconnect_epoch >= 0
        assert self.active_tool == f"lookup_customer_g{self.identity_generation}"
        if self.last_behavioral is not None:
            receipts = verify_protocol_delivery(self.last_behavioral)
            assert len(receipts) == 1


TestMCPTransitionStateMachine = MCPTransitionStateMachine.TestCase
TestMCPTransitionStateMachine.settings = settings(
    max_examples=75,
    stateful_step_count=25,
    deadline=None,
)
