from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.mcp.agent_schema_bridge import (
    MCPAgentToolSchemaDriftReceipt,
    create_schema_drift_protocol_receipt,
    schema_projection,
)
from agent_evals.mcp.models import MCPFaultKind, MCPFaultSpec

_TOOL = "lookup_customer"
_TTL_MS = 60_000
_STALE_TEXT = "Error executing tool lookup_customer: Input validation error for replacement schema"
_RECOVERY_TEXT = "replacement:7:true"


def fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="unit-agent-mcp-schema-drift",
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
        "type": "object",
        "properties": {"query": {"type": "string", "title": "Query"}},
        "required": ["query"],
    }


def replacement_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "customer_id": {"type": "integer", "title": "Customer Id"},
            "include_history": {"type": "boolean", "title": "Include History"},
        },
        "required": ["customer_id", "include_history"],
    }


def protocol_receipt():
    controlled_fault = fault()
    return create_schema_drift_protocol_receipt(
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


def create_receipt() -> MCPAgentToolSchemaDriftReceipt:
    controlled_fault = fault()
    return MCPAgentToolSchemaDriftReceipt.create(
        scenario_identity="a" * 64,
        fault=controlled_fault,
        protocol_receipt=protocol_receipt(),
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
        cached_list_ordinal=2,
        stale_call_ordinal=3,
        cache_invalidation_ordinal=4,
        refreshed_list_ordinal=5,
        recovery_call_ordinal=6,
    )


def test_schema_projection_binds_only_required_scalar_contract() -> None:
    assert schema_projection(replacement_schema()) == {
        "property_types": {
            "customer_id": "integer",
            "include_history": "boolean",
        },
        "required": ["customer_id", "include_history"],
    }


def test_schema_drift_receipt_binds_adaptation_without_raw_results() -> None:
    receipt = create_receipt()

    assert receipt.initial_schema_sha256 == receipt.cached_schema_sha256
    assert receipt.refreshed_schema_sha256 != receipt.initial_schema_sha256
    assert receipt.stale_protocol_observation_sha256 == receipt.agent_error_observation_sha256
    assert receipt.expected_recovery_sha256 == receipt.agent_recovery_observation_sha256
    serialized = json.dumps(receipt.model_dump(mode="json"), sort_keys=True)
    assert _STALE_TEXT not in serialized
    assert _RECOVERY_TEXT not in serialized
    assert '"query":"stale"' not in serialized


def test_schema_drift_protocol_receipt_rejects_noncausal_refresh_order() -> None:
    with pytest.raises(ValueError, match="chronology"):
        create_schema_drift_protocol_receipt(
            fault=fault(),
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
            cache_invalidation_ordinal=5,
            refreshed_list_ordinal=4,
            recovery_call_ordinal=6,
        )


def test_schema_drift_receipt_rejects_stale_recovery_arguments() -> None:
    controlled_fault = fault()
    with pytest.raises(ValueError, match="replacement arguments"):
        MCPAgentToolSchemaDriftReceipt.create(
            scenario_identity="a" * 64,
            fault=controlled_fault,
            protocol_receipt=protocol_receipt(),
            agent_tool_name=_TOOL,
            stale_call_id="call_stale",
            recovery_call_id="call_recovery",
            ttl_ms=_TTL_MS,
            initial_schema=initial_schema(),
            cached_schema=initial_schema(),
            refreshed_schema=replacement_schema(),
            stale_arguments={"query": "stale"},
            recovery_arguments={"query": "stale"},
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


def test_schema_drift_receipt_rejects_agent_error_mismatch() -> None:
    controlled_fault = fault()
    with pytest.raises(ValueError, match="agent-observed schema rejection"):
        MCPAgentToolSchemaDriftReceipt.create(
            scenario_identity="a" * 64,
            fault=controlled_fault,
            protocol_receipt=protocol_receipt(),
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
            agent_error_output={"type": "text", "text": "different rejection"},
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


def test_schema_drift_receipt_rejects_tampered_chronology() -> None:
    tampered = create_receipt().model_dump(mode="json")
    tampered["refreshed_list_ordinal"] = 2

    with pytest.raises(ValidationError, match="chronology"):
        MCPAgentToolSchemaDriftReceipt.model_validate(tampered)


def test_schema_drift_receipt_rejects_tampered_root() -> None:
    tampered = create_receipt().model_dump(mode="json")
    tampered["recovery_call_id"] = "call_recovery_tampered"

    with pytest.raises(ValidationError, match="receipt root"):
        MCPAgentToolSchemaDriftReceipt.model_validate(tampered)


def test_schema_drift_receipt_ordinals_are_strict_integers() -> None:
    tampered = create_receipt().model_dump(mode="json")
    tampered["initial_list_ordinal"] = True

    with pytest.raises(ValidationError):
        MCPAgentToolSchemaDriftReceipt.model_validate(tampered)


def test_schema_drift_receipt_rejects_wrong_fault_kind() -> None:
    wrong_fault = MCPFaultSpec.from_payload(
        fault_id="unit-agent-mcp-tool-error",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={"code": "TRANSIENT"},
    )

    with pytest.raises(ValueError, match="TOOL_SCHEMA_DRIFT"):
        create_schema_drift_protocol_receipt(
            fault=wrong_fault,
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


@pytest.mark.parametrize("cached_list_ordinal", [0, 1])
def test_schema_drift_protocol_receipt_rejects_cached_discovery_not_after_schema_swap(
    cached_list_ordinal: int,
) -> None:
    with pytest.raises(ValueError, match="chronology"):
        create_schema_drift_protocol_receipt(
            fault=fault(),
            ttl_ms=_TTL_MS,
            initial_schema=initial_schema(),
            cached_schema=initial_schema(),
            refreshed_schema=replacement_schema(),
            stale_protocol_text=_STALE_TEXT,
            protocol_recovery_text=_RECOVERY_TEXT,
            initial_list_ordinal=0,
            schema_swap_ordinal=1,
            cached_list_ordinal=cached_list_ordinal,
            stale_call_ordinal=3,
            cache_invalidation_ordinal=4,
            refreshed_list_ordinal=5,
            recovery_call_ordinal=6,
        )
