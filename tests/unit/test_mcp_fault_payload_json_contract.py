from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.mcp import MCPFaultKind, MCPFaultSpec


def test_mcp_stale_cache_fault_rejects_duplicate_ttl_keys() -> None:
    with pytest.raises(ValidationError, match="must not contain duplicate object keys"):
        MCPFaultSpec(
            fault_id="stale-cache-json",
            revision="1",
            kind=MCPFaultKind.TOOL_LIST_STALE_CACHE,
            tool_name="lookup_customer",
            payload_json='{"ttl_ms":1000,"ttl_ms":2000}',
        )


def test_mcp_content_fault_rejects_nested_duplicate_keys() -> None:
    with pytest.raises(ValidationError, match="must not contain duplicate object keys"):
        MCPFaultSpec(
            fault_id="nested-json",
            revision="1",
            kind=MCPFaultKind.TOOL_RESULT_POISON,
            tool_name="lookup_customer",
            payload_json='{"outer":{"scope":"tenant/7","scope":"tenant/9"}}',
        )


def test_mcp_fault_preserves_valid_json_canonicalization_and_identity() -> None:
    direct = MCPFaultSpec(
        fault_id="canonical-json",
        revision="1",
        kind=MCPFaultKind.TOOL_RESULT_POISON,
        tool_name="lookup_customer",
        payload_json=' { "b": 2, "a": { "y": 2, "x": 1 } } ',
    )
    from_payload = MCPFaultSpec.from_payload(
        fault_id="canonical-json",
        revision="1",
        kind=MCPFaultKind.TOOL_RESULT_POISON,
        tool_name="lookup_customer",
        payload={"a": {"x": 1, "y": 2}, "b": 2},
    )

    assert direct.payload_json == '{"a":{"x":1,"y":2},"b":2}'
    assert direct.payload_json == from_payload.payload_json
    assert direct.identity == from_payload.identity
