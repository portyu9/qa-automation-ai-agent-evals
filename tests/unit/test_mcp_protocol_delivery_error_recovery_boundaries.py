from __future__ import annotations

from collections.abc import Iterable

import pytest

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_error_bridge import MCPAgentToolErrorRecoveryReceipt
from agent_evals.mcp.delivery import ProtocolDeliveryError, verify_protocol_delivery
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_TOOL = "lookup_customer"
_SCENARIO = "a" * 64
_SUBJECT = "b" * 64
_PROTOCOL_VERSION = "2026-07-28"
_ARGUMENTS = '{"customer_id":"7"}'
_RECOVERY_TEXT = "benign"


def _fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="delivery-tool-error-boundaries",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={"code": "TRANSIENT_UPSTREAM"},
    )


def _error_text(fault: MCPFaultSpec) -> str:
    return f"Error executing tool {fault.tool_name}: {fault.payload_json}"


def _receipt() -> MCPAgentToolErrorRecoveryReceipt:
    fault = _fault()
    protocol = MCPFaultReceipt.create(
        fault=fault,
        protocol_version=_PROTOCOL_VERSION,
        injection_point=(
            f"mcp:{_PROTOCOL_VERSION}:tools/call:{_TOOL}:error.content[0].text:message-suffix"
        ),
        observed_text=_error_text(fault),
    )
    return MCPAgentToolErrorRecoveryReceipt.create(
        scenario_identity=_SCENARIO,
        fault=fault,
        protocol_receipt=protocol,
        agent_tool_name=_TOOL,
        error_call_id="call-error",
        retry_call_id="call-retry",
        error_arguments={"customer_id": "7"},
        retry_arguments={"customer_id": "7"},
        agent_error_output={"type": "text", "text": _error_text(fault)},
        expected_recovery_text=_RECOVERY_TEXT,
        agent_recovery_output={"type": "text", "text": _RECOVERY_TEXT},
    )


def _request(
    sequence: int,
    *,
    call_id: str,
    arguments: object = _ARGUMENTS,
    tool: str = _TOOL,
) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_REQUEST,
        source="adapter:test",
        payload={"tool": tool, "call_id": call_id, "arguments": arguments},
    )


def _result(sequence: int, *, call_id: str, output: object) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.TOOL_RESULT,
        source="adapter:test",
        payload={"call_id": call_id, "output": output},
    )


def _text_output(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _trial(events: Iterable[EvidenceEvent]) -> TrialEvidence:
    return TrialEvidence(
        trial_id="tool-error-delivery-boundaries",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        events=tuple(events),
    )


def _valid_events(receipt: MCPAgentToolErrorRecoveryReceipt | None = None) -> list[EvidenceEvent]:
    bridge = receipt or _receipt()
    return [
        _request(0, call_id=bridge.error_call_id),
        _result(1, call_id=bridge.error_call_id, output=_text_output(_error_text(_fault()))),
        _request(2, call_id=bridge.retry_call_id),
        _result(3, call_id=bridge.retry_call_id, output=_text_output(_RECOVERY_TEXT)),
        bridge.to_event(sequence=4),
    ]


def test_replay_accepts_exact_tool_error_recovery_relation() -> None:
    bridge = _receipt()
    assert verify_protocol_delivery(_trial(_valid_events(bridge))) == (bridge,)


@pytest.mark.parametrize(
    ("request_index", "call_id", "phase"),
    [
        (0, "substituted-error-call", "ToolError request call identity"),
        (2, "substituted-retry-call", "ToolError retry call identity"),
    ],
)
def test_replay_rejects_substituted_request_call_identity(
    request_index: int, call_id: str, phase: str
) -> None:
    bridge = _receipt()
    events = _valid_events(bridge)
    events[request_index] = _request(
        request_index,
        call_id=call_id,
    )
    with pytest.raises(ProtocolDeliveryError, match=phase):
        verify_protocol_delivery(_trial(events))


@pytest.mark.parametrize("result_index", [1, 3])
def test_replay_rejects_missing_result(result_index: int) -> None:
    bridge = _receipt()
    original = _valid_events(bridge)
    kept = [event for index, event in enumerate(original) if index != result_index]
    events = [event.model_copy(update={"sequence": index}) for index, event in enumerate(kept)]
    with pytest.raises(ProtocolDeliveryError, match="exactly one normalized result"):
        verify_protocol_delivery(_trial(events))


@pytest.mark.parametrize("call_id", ["call-error", "call-retry"])
def test_replay_rejects_duplicate_result(call_id: str) -> None:
    bridge = _receipt()
    error_text = _error_text(_fault())
    events = [
        _request(0, call_id=bridge.error_call_id),
        _result(1, call_id=bridge.error_call_id, output=_text_output(error_text)),
        _request(2, call_id=bridge.retry_call_id),
        _result(3, call_id=bridge.retry_call_id, output=_text_output(_RECOVERY_TEXT)),
        _result(
            4,
            call_id=call_id,
            output=_text_output(error_text if call_id == bridge.error_call_id else _RECOVERY_TEXT),
        ),
        bridge.to_event(sequence=5),
    ]
    with pytest.raises(ProtocolDeliveryError, match="exactly one normalized result"):
        verify_protocol_delivery(_trial(events))


def test_replay_rejects_cross_bound_result_identity() -> None:
    bridge = _receipt()
    events = [
        _request(0, call_id=bridge.error_call_id),
        _result(1, call_id="unbound-result", output=_text_output(_error_text(_fault()))),
        _request(2, call_id=bridge.retry_call_id),
        _result(3, call_id=bridge.retry_call_id, output=_text_output(_RECOVERY_TEXT)),
        bridge.to_event(sequence=4),
    ]
    with pytest.raises(ProtocolDeliveryError, match="exactly one normalized result"):
        verify_protocol_delivery(_trial(events))


@pytest.mark.parametrize(
    ("request_index", "arguments", "message"),
    [
        (0, '{"customer_id":"8"}', "ToolError request arguments"),
        (2, '{"customer_id":"8"}', "ToolError retry arguments"),
        (0, None, "arguments are missing"),
        (2, "", "arguments are missing"),
        (0, "{", "not strict finite JSON"),
        (0, '{"customer_id":"7","customer_id":"7"}', "not strict finite JSON"),
        (0, '{"customer_id":"7","score":NaN}', "not strict finite JSON"),
        (0, '{"customer_id":"7","score":1e999}', "not strict finite JSON"),
        (0, '["customer_id","7"]', "not a string-keyed object"),
    ],
)
def test_replay_rejects_unbound_or_non_strict_arguments(
    request_index: int, arguments: object, message: str
) -> None:
    bridge = _receipt()
    events = _valid_events(bridge)
    call_id = bridge.error_call_id if request_index == 0 else bridge.retry_call_id
    events[request_index] = _request(request_index, call_id=call_id, arguments=arguments)
    with pytest.raises(ProtocolDeliveryError, match=message):
        verify_protocol_delivery(_trial(events))


@pytest.mark.parametrize(
    ("result_index", "output"),
    [
        (1, "not-an-output-object"),
        (1, {"type": "text"}),
        (1, {"type": "text", "text": "x", "extra": True}),
        (1, {"type": "json", "text": "x"}),
        (3, "not-an-output-object"),
        (3, {"type": "text", "text": 7}),
    ],
)
def test_replay_rejects_malformed_normalized_output(result_index: int, output: object) -> None:
    bridge = _receipt()
    events = _valid_events(bridge)
    call_id = bridge.error_call_id if result_index == 1 else bridge.retry_call_id
    events[result_index] = _result(result_index, call_id=call_id, output=output)
    with pytest.raises(ProtocolDeliveryError, match="not one exact text output object"):
        verify_protocol_delivery(_trial(events))


@pytest.mark.parametrize(
    ("result_index", "text", "message"),
    [
        (1, "changed error", "ToolError rejection output"),
        (3, "changed recovery", "ToolError recovery output"),
    ],
)
def test_replay_rejects_changed_result_text(result_index: int, text: str, message: str) -> None:
    bridge = _receipt()
    events = _valid_events(bridge)
    call_id = bridge.error_call_id if result_index == 1 else bridge.retry_call_id
    events[result_index] = _result(result_index, call_id=call_id, output=_text_output(text))
    with pytest.raises(ProtocolDeliveryError, match=message):
        verify_protocol_delivery(_trial(events))


def test_replay_rejects_retry_before_error_result() -> None:
    bridge = _receipt()
    events = [
        _request(0, call_id=bridge.error_call_id),
        _request(1, call_id=bridge.retry_call_id),
        _result(2, call_id=bridge.error_call_id, output=_text_output(_error_text(_fault()))),
        _result(3, call_id=bridge.retry_call_id, output=_text_output(_RECOVERY_TEXT)),
        bridge.to_event(sequence=4),
    ]
    with pytest.raises(ProtocolDeliveryError, match="causality"):
        verify_protocol_delivery(_trial(events))


def test_replay_rejects_delivery_before_recovery_result() -> None:
    bridge = _receipt()
    events = [
        _request(0, call_id=bridge.error_call_id),
        _result(1, call_id=bridge.error_call_id, output=_text_output(_error_text(_fault()))),
        _request(2, call_id=bridge.retry_call_id),
        bridge.to_event(sequence=3),
        _result(4, call_id=bridge.retry_call_id, output=_text_output(_RECOVERY_TEXT)),
    ]
    with pytest.raises(ProtocolDeliveryError, match="causality"):
        verify_protocol_delivery(_trial(events))


def test_replay_rejects_extra_controlled_target_request() -> None:
    bridge = _receipt()
    events = [
        _request(0, call_id=bridge.error_call_id),
        _result(1, call_id=bridge.error_call_id, output=_text_output(_error_text(_fault()))),
        _request(2, call_id=bridge.retry_call_id),
        _result(3, call_id=bridge.retry_call_id, output=_text_output(_RECOVERY_TEXT)),
        _request(4, call_id="call-extra"),
        bridge.to_event(sequence=5),
    ]
    with pytest.raises(ProtocolDeliveryError, match="exactly two normalized target requests"):
        verify_protocol_delivery(_trial(events))
