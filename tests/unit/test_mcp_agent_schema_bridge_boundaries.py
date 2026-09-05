from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_evals.mcp.agent_schema_bridge import (
    MCPAgentToolSchemaDriftReceipt,
    create_schema_drift_protocol_receipt,
    schema_projection,
)
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_TOOL = "lookup_customer"
_TTL_MS = 60_000
_STALE_TEXT = "Error executing tool lookup_customer: Input validation error for replacement schema"
_RECOVERY_TEXT = "replacement:7:true"
_PROTOCOL_VERSION = "2026-07-28"


def _fault(
    *,
    fault_id: str = "schema-drift-boundaries",
    ttl_ms: int = _TTL_MS,
    initial_required: object = None,
    replacement_required: object = None,
) -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id=fault_id,
        revision="1",
        kind=MCPFaultKind.TOOL_SCHEMA_DRIFT,
        tool_name=_TOOL,
        payload={
            "ttl_ms": ttl_ms,
            "initial_required": (
                {"query": "string"} if initial_required is None else initial_required
            ),
            "replacement_required": (
                {"customer_id": "integer", "include_history": "boolean"}
                if replacement_required is None
                else replacement_required
            ),
        },
    )


def _initial_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }


def _replacement_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "customer_id": {"type": "integer"},
            "include_history": {"type": "boolean"},
        },
        "required": ["customer_id", "include_history"],
    }


def _protocol_receipt(*, fault: MCPFaultSpec | None = None) -> MCPFaultReceipt:
    controlled = fault or _fault()
    return create_schema_drift_protocol_receipt(
        fault=controlled,
        ttl_ms=_TTL_MS,
        initial_schema=_initial_schema(),
        cached_schema=_initial_schema(),
        refreshed_schema=_replacement_schema(),
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


def _bridge_kwargs() -> dict[str, Any]:
    return {
        "scenario_identity": "a" * 64,
        "fault": _fault(),
        "protocol_receipt": _protocol_receipt(),
        "agent_tool_name": _TOOL,
        "stale_call_id": "call-stale",
        "recovery_call_id": "call-recovery",
        "mcp_cache_hint_ttl_ms": _TTL_MS,
        "initial_schema": _initial_schema(),
        "cached_schema": _initial_schema(),
        "refreshed_schema": _replacement_schema(),
        "stale_arguments": {"query": "stale"},
        "recovery_arguments": {"customer_id": 7, "include_history": True},
        "stale_protocol_text": _STALE_TEXT,
        "agent_error_output": {"type": "text", "text": _STALE_TEXT},
        "protocol_recovery_text": _RECOVERY_TEXT,
        "agent_recovery_output": {"type": "text", "text": _RECOVERY_TEXT},
        "initial_list_ordinal": 0,
        "schema_swap_ordinal": 1,
        "cached_list_ordinal": 2,
        "stale_call_ordinal": 3,
        "cache_invalidation_ordinal": 4,
        "refreshed_list_ordinal": 5,
        "recovery_call_ordinal": 6,
    }


def _create_bridge(**overrides: Any) -> MCPAgentToolSchemaDriftReceipt:
    values = _bridge_kwargs()
    values.update(overrides)
    return MCPAgentToolSchemaDriftReceipt.create(**values)


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"required": "query", "properties": {}}, "required/properties structure"),
        ({"required": [], "properties": []}, "required/properties structure"),
        ({"required": [1], "properties": {}}, "non-string required property"),
        ({"required": ["query"], "properties": {}}, "lacks property definition"),
        (
            {"required": ["query"], "properties": {"query": {"type": ["string"]}}},
            "lacks a scalar type",
        ),
    ],
)
def test_schema_projection_rejects_malformed_contract(
    schema: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        schema_projection(schema)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("agent_tool_name", " ", "non-empty"),
        ("agent_tool_name", f" {_TOOL}", "surrounding whitespace"),
        ("stale_call_id", " ", "non-empty"),
        ("stale_call_id", " call-stale", "surrounding whitespace"),
        ("recovery_call_id", " ", "non-empty"),
        ("recovery_call_id", "call-recovery ", "surrounding whitespace"),
        ("agent_tool_name", "different_tool", "does not match controlled"),
    ],
)
def test_bridge_rejects_malformed_or_unbound_identity(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(**{field: value})


def test_bridge_rejects_reused_call_identity() -> None:
    with pytest.raises(ValueError, match="distinct OpenAI call IDs"):
        _create_bridge(recovery_call_id="call-stale")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("stale_arguments", None, "bound stale arguments"),
        ("recovery_arguments", None, "bound replacement arguments"),
        ("stale_arguments", [("query", "stale")], "mapping or None"),
        ("recovery_arguments", [("customer_id", 7)], "mapping or None"),
        ("stale_arguments", {1: "stale"}, "keys must be strings"),
        ("recovery_arguments", {1: 7}, "keys must be strings"),
    ],
)
def test_bridge_rejects_malformed_arguments(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(**{field: value})


def test_bridge_rejects_non_finite_arguments() -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        _create_bridge(stale_arguments={"query": "stale", "score": float("nan")})

    with pytest.raises(ValueError, match="Out of range float values"):
        _create_bridge(
            recovery_arguments={
                "customer_id": 7,
                "include_history": True,
                "score": float("inf"),
            }
        )


@pytest.mark.parametrize("phase_field", ["agent_error_output", "agent_recovery_output"])
@pytest.mark.parametrize(
    ("output", "message"),
    [
        ("not-an-output-object", "model-visible text output object"),
        ({"type": "text"}, "contain exactly 'type' and 'text'"),
        ({"type": "text", "text": "x", "extra": True}, "contain exactly"),
        ({"type": "json", "text": "x"}, "one text output object"),
        ({"type": "text", "text": 1}, "one text output object"),
    ],
)
def test_bridge_rejects_malformed_model_visible_outputs(
    phase_field: str, output: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(**{phase_field: output})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "initial_schema",
            {"type": "object", "properties": {"other": {"type": "string"}}, "required": ["other"]},
            "initial MCP schema",
        ),
        (
            "cached_schema",
            _replacement_schema(),
            "cached MCP schema",
        ),
        (
            "refreshed_schema",
            _initial_schema(),
            "refreshed MCP schema",
        ),
        ("stale_arguments", {"query": "changed"}, "bound stale arguments"),
        (
            "recovery_arguments",
            {"customer_id": 8, "include_history": True},
            "bound replacement arguments",
        ),
        ("stale_protocol_text", "", "non-empty rejection"),
        (
            "agent_error_output",
            {"type": "text", "text": "different rejection"},
            "does not match MCP protocol observation",
        ),
        ("protocol_recovery_text", "wrong", "bound replacement result"),
        (
            "agent_recovery_output",
            {"type": "text", "text": "wrong"},
            "does not match expected replacement result",
        ),
    ],
)
def test_bridge_rejects_relation_drift(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _create_bridge(**{field: value})


@pytest.mark.parametrize(
    ("fault", "ttl_ms", "message"),
    [
        (_fault(ttl_ms=59_999), _TTL_MS, "TTL"),
        (_fault(initial_required={"query": "integer"}), _TTL_MS, "initial contract"),
        (
            _fault(replacement_required={"customer_id": "integer"}),
            _TTL_MS,
            "replacement contract",
        ),
    ],
)
def test_protocol_receipt_rejects_invalid_fault_payload(
    fault: MCPFaultSpec, ttl_ms: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        create_schema_drift_protocol_receipt(
            fault=fault,
            ttl_ms=ttl_ms,
            initial_schema=_initial_schema(),
            cached_schema=_initial_schema(),
            refreshed_schema=_replacement_schema(),
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


def test_protocol_receipt_rejects_wrong_fault_kind() -> None:
    wrong = MCPFaultSpec.from_payload(
        fault_id="schema-drift-wrong-kind",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={"message": "controlled"},
    )
    with pytest.raises(ValueError, match="requires TOOL_SCHEMA_DRIFT"):
        create_schema_drift_protocol_receipt(
            fault=wrong,
            ttl_ms=_TTL_MS,
            initial_schema=_initial_schema(),
            cached_schema=_initial_schema(),
            refreshed_schema=_replacement_schema(),
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


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"initial_schema": _replacement_schema()}, "initial MCP schema"),
        ({"cached_schema": _replacement_schema()}, "cached MCP schema"),
        ({"refreshed_schema": _initial_schema()}, "refreshed MCP schema"),
        ({"stale_protocol_text": ""}, "non-empty rejection"),
        ({"protocol_recovery_text": "wrong"}, "bound replacement result"),
        ({"schema_swap_ordinal": -1}, "non-negative integers"),
        ({"schema_swap_ordinal": True}, "non-negative integers"),
        ({"cached_list_ordinal": 1}, "chronology"),
        ({"stale_call_ordinal": 2}, "chronology"),
        ({"refreshed_list_ordinal": 4}, "chronology"),
    ],
)
def test_protocol_receipt_rejects_invalid_relation(
    overrides: dict[str, object], message: str
) -> None:
    values: dict[str, Any] = {
        "fault": _fault(),
        "ttl_ms": _TTL_MS,
        "initial_schema": _initial_schema(),
        "cached_schema": _initial_schema(),
        "refreshed_schema": _replacement_schema(),
        "stale_protocol_text": _STALE_TEXT,
        "protocol_recovery_text": _RECOVERY_TEXT,
        "initial_list_ordinal": 0,
        "schema_swap_ordinal": 1,
        "cached_list_ordinal": 2,
        "stale_call_ordinal": 3,
        "cache_invalidation_ordinal": 4,
        "refreshed_list_ordinal": 5,
        "recovery_call_ordinal": 6,
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        create_schema_drift_protocol_receipt(**values)


def test_bridge_rejects_wrong_protocol_receipt_kind() -> None:
    wrong_fault = MCPFaultSpec.from_payload(
        fault_id="schema-drift-wrong-receipt-kind",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={"message": "controlled"},
    )
    wrong_receipt = MCPFaultReceipt.create(
        fault=wrong_fault,
        protocol_version=_PROTOCOL_VERSION,
        injection_point="mcp:2026-07-28:tools/call:controlled",
        observed_text="controlled",
    )
    with pytest.raises(ValueError, match="TOOL_SCHEMA_DRIFT protocol receipt"):
        _create_bridge(protocol_receipt=wrong_receipt)


def test_bridge_rejects_wrong_protocol_version_and_boundary() -> None:
    wrong_version = MCPFaultReceipt.create(
        fault=_fault(),
        protocol_version="2025-06-18",
        injection_point="wrong",
        observed_text="wrong",
    )
    with pytest.raises(ValueError, match="requires protocol version"):
        _create_bridge(protocol_receipt=wrong_version)

    wrong_boundary = MCPFaultReceipt.create(
        fault=_fault(),
        protocol_version=_PROTOCOL_VERSION,
        injection_point="wrong",
        observed_text="wrong",
    )
    with pytest.raises(ValueError, match="unexpected protocol observation boundary"):
        _create_bridge(protocol_receipt=wrong_boundary)


def test_bridge_rejects_protocol_receipt_from_different_fault_identity() -> None:
    different_fault = _fault(fault_id="schema-drift-different-identity")
    different_receipt = _protocol_receipt(fault=different_fault)
    with pytest.raises(ValueError, match="identity does not match controlled fault"):
        _create_bridge(protocol_receipt=different_receipt)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("initial_schema_sha256", "0" * 64, "initial schema digest"),
        ("cached_schema_sha256", "1" * 64, "cached schema digest"),
        ("refreshed_schema_sha256", "2" * 64, "refreshed schema digest"),
        ("stale_arguments_sha256", "3" * 64, "stale argument digest"),
        ("recovery_arguments_sha256", "4" * 64, "recovery argument digest"),
        (
            "agent_error_observation_sha256",
            "5" * 64,
            "rejection digest does not match protocol rejection digest",
        ),
        ("expected_recovery_sha256", "6" * 64, "expected recovery digest"),
        (
            "protocol_recovery_observation_sha256",
            "7" * 64,
            "protocol recovery digest",
        ),
        (
            "agent_recovery_observation_sha256",
            "8" * 64,
            "agent recovery digest",
        ),
        ("mcp_cache_hint_ttl_ms", 1, "root-bound relation"),
        ("cached_list_ordinal", 1, "chronology"),
    ],
)
def test_receipt_model_validation_rechecks_semantic_bindings(
    field: str, value: object, message: str
) -> None:
    payload = _create_bridge().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError, match=message):
        MCPAgentToolSchemaDriftReceipt.model_validate(payload)


def test_receipt_model_validation_rejects_verified_tool_mismatch() -> None:
    payload = _create_bridge().model_dump(mode="json")
    payload["agent_tool_name"] = "different_tool"
    with pytest.raises(ValidationError, match="verified MCP schema-drift tool"):
        MCPAgentToolSchemaDriftReceipt.model_validate(payload)


def test_receipt_model_validation_rejects_reused_call_id() -> None:
    payload = _create_bridge().model_dump(mode="json")
    payload["recovery_call_id"] = payload["stale_call_id"]
    with pytest.raises(ValidationError, match="distinct OpenAI call IDs"):
        MCPAgentToolSchemaDriftReceipt.model_validate(payload)


def test_receipt_model_validation_rejects_root_tampering() -> None:
    payload = _create_bridge().model_dump(mode="json")
    payload["receipt_root"] = "f" * 64
    with pytest.raises(ValidationError, match="receipt root"):
        MCPAgentToolSchemaDriftReceipt.model_validate(payload)
