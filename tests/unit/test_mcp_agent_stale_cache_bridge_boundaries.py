from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.mcp.agent_stale_cache_bridge import (
    MCPAgentToolStaleCacheReceipt,
    create_stale_cache_protocol_receipt,
)
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_TOOL = "lookup_customer"
_TTL_MS = 60_000
_PROTOCOL_VERSION = "2026-07-28"
_STALE_TEXT = "Error executing tool lookup_customer: unknown tool 'lookup_customer'"


def _fault(*, fault_id: str = "stale-cache-agent-boundaries") -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id=fault_id,
        revision="1",
        kind=MCPFaultKind.TOOL_LIST_STALE_CACHE,
        tool_name=_TOOL,
        payload={"ttl_ms": _TTL_MS},
    )


def _protocol_point() -> str:
    return (
        f"mcp:{_PROTOCOL_VERSION}:tools/list:cache-use-stale-after-remove:"
        f"{_TOOL}:refresh-proves-absent"
    )


def _protocol_observation() -> str:
    return json.dumps(
        {
            "cached_tool_names": [_TOOL],
            "initial_tool_names": [_TOOL],
            "refreshed_tool_names": [],
            "ttl_ms": _TTL_MS,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _protocol_receipt() -> MCPFaultReceipt:
    return create_stale_cache_protocol_receipt(
        fault=_fault(),
        ttl_ms=_TTL_MS,
        initial_tool_names=(_TOOL,),
        cached_tool_names=(_TOOL,),
        refreshed_tool_names=(),
    )


def _bridge_kwargs() -> dict[str, object]:
    return {
        "scenario_identity": "a" * 64,
        "fault": _fault(),
        "protocol_receipt": _protocol_receipt(),
        "tool_name": _TOOL,
        "stale_call_id": "call-stale",
        "ttl_ms": _TTL_MS,
        "stale_arguments": {"query": "stale"},
        "stale_protocol_text": _STALE_TEXT,
        "agent_error_output": {"type": "text", "text": _STALE_TEXT},
        "initial_model_tool_names": (_TOOL,),
        "refreshed_model_tool_names": (),
        "initial_list_ordinal": 0,
        "removal_ordinal": 1,
        "cached_list_ordinal": 2,
        "stale_call_ordinal": 3,
        "cache_invalidation_ordinal": 4,
        "refreshed_list_ordinal": 5,
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tool_name", "different_tool", "does not match controlled MCP fault"),
        ("tool_name", " lookup_customer", "surrounding whitespace"),
        ("stale_call_id", " ", "non-empty"),
        ("stale_call_id", " call-stale", "surrounding whitespace"),
        ("stale_arguments", None, "bound stale arguments"),
        ("stale_arguments", ["stale"], "mapping or None"),
        ("stale_arguments", {1: "stale"}, "keys must be strings"),
        ("stale_protocol_text", "permission denied", "unknown-tool rejection"),
        ("agent_error_output", _STALE_TEXT, "text output object"),
        ("agent_error_output", {"text": _STALE_TEXT}, "exactly 'type' and 'text'"),
        (
            "agent_error_output",
            {"type": "json", "text": _STALE_TEXT},
            "one text output object",
        ),
        ("initial_model_tool_names", (), "contain only target"),
        ("initial_model_tool_names", (1,), "contain only strings"),
        ("initial_model_tool_names", (_TOOL, _TOOL), "must not contain duplicates"),
        ("initial_list_ordinal", True, "non-negative integers"),
    ],
)
def test_stale_cache_bridge_create_rejects_malformed_relation_inputs(
    field: str,
    value: object,
    message: str,
) -> None:
    kwargs = _bridge_kwargs()
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        MCPAgentToolStaleCacheReceipt.create(**kwargs)  # type: ignore[arg-type]


def test_stale_cache_protocol_receipt_rejects_wrong_fault_kind() -> None:
    wrong_fault = MCPFaultSpec.from_payload(
        fault_id="stale-cache-wrong-kind",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={"message": "controlled error"},
    )

    with pytest.raises(ValueError, match="requires TOOL_LIST_STALE_CACHE"):
        create_stale_cache_protocol_receipt(
            fault=wrong_fault,
            ttl_ms=_TTL_MS,
            initial_tool_names=(_TOOL,),
            cached_tool_names=(_TOOL,),
            refreshed_tool_names=(),
        )


def test_stale_cache_protocol_receipt_rejects_initial_discovery_without_target() -> None:
    with pytest.raises(ValueError, match="initial discovery"):
        create_stale_cache_protocol_receipt(
            fault=_fault(),
            ttl_ms=_TTL_MS,
            initial_tool_names=(),
            cached_tool_names=(),
            refreshed_tool_names=(),
        )


def test_stale_cache_bridge_rejects_wrong_protocol_receipt_kind() -> None:
    wrong_fault = MCPFaultSpec.from_payload(
        fault_id="stale-cache-wrong-receipt-kind",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={"message": "controlled error"},
    )
    wrong_receipt = MCPFaultReceipt.create(
        fault=wrong_fault,
        protocol_version=_PROTOCOL_VERSION,
        injection_point=_protocol_point(),
        observed_text=_protocol_observation(),
    )
    kwargs = _bridge_kwargs()
    kwargs["protocol_receipt"] = wrong_receipt

    with pytest.raises(ValueError, match="TOOL_LIST_STALE_CACHE protocol receipt"):
        MCPAgentToolStaleCacheReceipt.create(**kwargs)  # type: ignore[arg-type]


def test_stale_cache_bridge_rejects_wrong_protocol_version() -> None:
    wrong_receipt = MCPFaultReceipt.create(
        fault=_fault(),
        protocol_version="2025-06-18",
        injection_point=_protocol_point(),
        observed_text=_protocol_observation(),
    )
    kwargs = _bridge_kwargs()
    kwargs["protocol_receipt"] = wrong_receipt

    with pytest.raises(ValueError, match="requires protocol version"):
        MCPAgentToolStaleCacheReceipt.create(**kwargs)  # type: ignore[arg-type]


def test_stale_cache_bridge_rejects_wrong_protocol_boundary() -> None:
    wrong_receipt = MCPFaultReceipt.create(
        fault=_fault(),
        protocol_version=_PROTOCOL_VERSION,
        injection_point="mcp:2026-07-28:tools/list:wrong-boundary",
        observed_text=_protocol_observation(),
    )
    kwargs = _bridge_kwargs()
    kwargs["protocol_receipt"] = wrong_receipt

    with pytest.raises(ValueError, match="unexpected protocol boundary"):
        MCPAgentToolStaleCacheReceipt.create(**kwargs)  # type: ignore[arg-type]


def test_stale_cache_bridge_rejects_wrong_protocol_observation() -> None:
    wrong_receipt = MCPFaultReceipt.create(
        fault=_fault(),
        protocol_version=_PROTOCOL_VERSION,
        injection_point=_protocol_point(),
        observed_text="different discovery relation",
    )
    kwargs = _bridge_kwargs()
    kwargs["protocol_receipt"] = wrong_receipt

    with pytest.raises(ValueError, match="does not match bound discovery relation"):
        MCPAgentToolStaleCacheReceipt.create(**kwargs)  # type: ignore[arg-type]


def test_stale_cache_bridge_rejects_protocol_receipt_from_different_fault_identity() -> None:
    different_fault = _fault(fault_id="stale-cache-different-identity")
    different_receipt = MCPFaultReceipt.create(
        fault=different_fault,
        protocol_version=_PROTOCOL_VERSION,
        injection_point=_protocol_point(),
        observed_text=_protocol_observation(),
    )
    kwargs = _bridge_kwargs()
    kwargs["protocol_receipt"] = different_receipt

    with pytest.raises(ValueError, match="identity does not match controlled fault"):
        MCPAgentToolStaleCacheReceipt.create(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tool_name", "different_tool", "verified MCP protocol receipt"),
        ("ttl_ms", 1, "payload digest does not match bound TTL"),
        ("stale_arguments_sha256", "0" * 64, "stale argument digest"),
        (
            "stale_protocol_observation_sha256",
            "1" * 64,
            "rejection digest does not match protocol rejection",
        ),
        (
            "initial_model_tool_names_sha256",
            "2" * 64,
            "initial model-visible tool digest",
        ),
        (
            "refreshed_model_tool_names_sha256",
            "3" * 64,
            "refreshed model-visible tool digest",
        ),
        ("cached_list_ordinal", 1, "protocol chronology"),
    ],
)
def test_stale_cache_receipt_model_validation_rechecks_semantic_bindings(
    field: str,
    value: object,
    message: str,
) -> None:
    receipt = MCPAgentToolStaleCacheReceipt.create(**_bridge_kwargs())  # type: ignore[arg-type]
    payload = receipt.model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError, match=message):
        MCPAgentToolStaleCacheReceipt.model_validate(payload)
