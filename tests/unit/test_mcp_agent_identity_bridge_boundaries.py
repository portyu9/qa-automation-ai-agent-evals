from __future__ import annotations

from typing import Any

import pytest

from agent_evals.mcp.agent_identity_bridge import (
    MCPAgentToolIdentityDriftReceipt,
    create_identity_drift_protocol_receipt,
)
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_OLD = "lookup_customer"
_NEW = "lookup_customer_v2"
_STALE_TEXT = "Error executing tool lookup_customer: unknown tool 'lookup_customer'"
_RECOVERY_TEXT = "replacement:fresh"


def _fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="identity-drift-boundaries",
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
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
        recovery_call_ordinal=6,
    )


def _create_bridge(**overrides: Any) -> MCPAgentToolIdentityDriftReceipt:
    values: dict[str, Any] = {
        "scenario_identity": "a" * 64,
        "fault": _fault(),
        "protocol_receipt": _protocol_receipt(),
        "original_tool_name": _OLD,
        "replacement_tool_name": _NEW,
        "stale_call_id": "call-old",
        "recovery_call_id": "call-new",
        "ttl_ms": 60_000,
        "stale_arguments": {"query": "stale"},
        "recovery_arguments": {"query": "fresh"},
        "stale_protocol_text": _STALE_TEXT,
        "agent_error_output": {"type": "text", "text": _STALE_TEXT},
        "protocol_recovery_text": _RECOVERY_TEXT,
        "agent_recovery_output": {"type": "text", "text": _RECOVERY_TEXT},
        "initial_model_tool_names": (_OLD,),
        "refreshed_model_tool_names": (_NEW,),
        "initial_list_ordinal": 0,
        "identity_swap_ordinal": 1,
        "cached_list_ordinal": 2,
        "stale_call_ordinal": 3,
        "cache_invalidation_ordinal": 4,
        "refreshed_list_ordinal": 5,
        "recovery_call_ordinal": 6,
    }
    values.update(overrides)
    return MCPAgentToolIdentityDriftReceipt.create(**values)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("stale_arguments", {"query": "changed"}, "bound stale arguments"),
        ("recovery_arguments", {"query": "changed"}, "bound replacement arguments"),
        ("stale_protocol_text", "permission denied", "unknown-tool rejection"),
        (
            "agent_error_output",
            {"type": "text", "text": "different rejection"},
            "does not match MCP observation",
        ),
        ("protocol_recovery_text", "wrong result", "bound replacement result"),
        (
            "agent_recovery_output",
            {"type": "text", "text": "wrong result"},
            "does not match controlled result",
        ),
        ("initial_model_tool_names", (_NEW,), "initial model-visible controlled identity set"),
    ],
)
def test_bridge_create_rejects_relation_drift(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(**{field: value})


@pytest.mark.parametrize(
    ("names", "message"),
    [
        ((_OLD, _OLD), "must not contain duplicates"),
        ((f" {_OLD}",), "surrounding whitespace"),
        ((1,), "must contain only strings"),
    ],
)
def test_bridge_rejects_ambiguous_or_invalid_model_tool_names(
    names: tuple[object, ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(initial_model_tool_names=names)


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("not-an-output-object", "one model-visible text output object"),
        ({"type": "text", "text": _STALE_TEXT, "extra": True}, "contain exactly"),
        ({"type": "json", "text": _STALE_TEXT}, "one text output object"),
    ],
)
def test_bridge_rejects_malformed_agent_error_output(output: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(agent_error_output=output)


def test_bridge_rejects_non_mapping_and_non_string_key_arguments() -> None:
    with pytest.raises(ValueError, match="mapping or None"):
        _create_bridge(stale_arguments=[("query", "stale")])

    with pytest.raises(ValueError, match="argument keys must be strings"):
        _create_bridge(stale_arguments={1: "stale"})


def test_bridge_rejects_non_finite_arguments() -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        _create_bridge(stale_arguments={"query": "stale", "score": float("nan")})


def test_protocol_receipt_rejects_wrong_fault_kind() -> None:
    wrong = MCPFaultSpec.from_payload(
        fault_id="identity-drift-wrong-kind",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_OLD,
        payload={"message": "controlled"},
    )
    with pytest.raises(ValueError, match="requires TOOL_IDENTITY_DRIFT"):
        create_identity_drift_protocol_receipt(
            fault=wrong,
            ttl_ms=60_000,
            original_tool_name=_OLD,
            replacement_tool_name=_NEW,
            stale_protocol_text=_STALE_TEXT,
            protocol_recovery_text=_RECOVERY_TEXT,
            initial_list_ordinal=0,
            identity_swap_ordinal=1,
            cached_list_ordinal=2,
            stale_call_ordinal=3,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=5,
            recovery_call_ordinal=6,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ttl_ms": 59_999}, "TTL"),
        ({"replacement_tool_name": "another_tool"}, "replacement name"),
        ({"original_tool_name": "another_tool"}, "original tool name"),
        ({"stale_protocol_text": "permission denied"}, "unknown-tool rejection"),
        ({"protocol_recovery_text": "wrong result"}, "replacement call"),
        ({"identity_swap_ordinal": -1}, "non-negative integers"),
        ({"identity_swap_ordinal": True}, "non-negative integers"),
    ],
)
def test_protocol_receipt_rejects_invalid_controlled_relation(
    overrides: dict[str, object], message: str
) -> None:
    values: dict[str, Any] = {
        "fault": _fault(),
        "ttl_ms": 60_000,
        "original_tool_name": _OLD,
        "replacement_tool_name": _NEW,
        "stale_protocol_text": _STALE_TEXT,
        "protocol_recovery_text": _RECOVERY_TEXT,
        "initial_list_ordinal": 0,
        "identity_swap_ordinal": 1,
        "cached_list_ordinal": 2,
        "stale_call_ordinal": 3,
        "cache_invalidation_ordinal": 4,
        "refreshed_list_ordinal": 5,
        "recovery_call_ordinal": 6,
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        create_identity_drift_protocol_receipt(**values)


def test_bridge_rejects_protocol_receipt_wrong_revision_and_boundary() -> None:
    fault = _fault()
    wrong_version = MCPFaultReceipt.create(
        fault=fault,
        protocol_version="2025-03-26",
        injection_point="wrong",
        observed_text="wrong",
    )
    with pytest.raises(ValueError, match="requires protocol version"):
        _create_bridge(protocol_receipt=wrong_version)

    wrong_boundary = MCPFaultReceipt.create(
        fault=fault,
        protocol_version="2026-07-28",
        injection_point="wrong",
        observed_text="wrong",
    )
    with pytest.raises(ValueError, match="unexpected protocol boundary"):
        _create_bridge(protocol_receipt=wrong_boundary)


@pytest.mark.parametrize("cached_list_ordinal", [0, 1])
def test_protocol_receipt_rejects_cached_discovery_not_after_identity_swap(
    cached_list_ordinal: int,
) -> None:
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
            cached_list_ordinal=cached_list_ordinal,
            stale_call_ordinal=3,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=5,
            recovery_call_ordinal=6,
        )
