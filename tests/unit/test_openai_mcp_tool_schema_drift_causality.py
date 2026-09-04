from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_evals.adapters.base import AdapterPreconditionError
from agent_evals.adapters.openai_mcp_tool_schema_drift import _MCPToolSchemaDriftRecorder
from agent_evals.mcp.models import MCPFaultKind, MCPFaultSpec

_TOOL = "lookup_customer"
_CONTROL = "__agent_evals_schema_swap__"


def fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="unit-openai-mcp-schema-drift-causality",
        revision="1",
        kind=MCPFaultKind.TOOL_SCHEMA_DRIFT,
        tool_name=_TOOL,
        payload={
            "ttl_ms": 60_000,
            "initial_required": {"query": "string"},
            "replacement_required": {
                "customer_id": "integer",
                "include_history": "boolean",
            },
        },
    )


def tool(name: str, schema: dict[str, object]) -> Any:
    return SimpleNamespace(name=name, input_schema=schema)


def result(text: str, *, is_error: bool) -> Any:
    return SimpleNamespace(
        is_error=is_error,
        content=[SimpleNamespace(type="text", text=text)],
    )


@pytest.mark.asyncio
async def test_schema_drift_recorder_rejects_corrected_call_before_refreshed_discovery() -> None:
    initial_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    invalidated = False

    async def list_tools(*args: object, **kwargs: object) -> list[Any]:
        del args, kwargs
        return [tool(_TOOL, initial_schema)]

    call_count = 0

    async def call_tool(
        name: str,
        arguments: dict[str, Any] | None,
        **kwargs: object,
    ) -> Any:
        nonlocal call_count
        del arguments, kwargs
        if name == _CONTROL:
            return result("schema-swapped", is_error=False)
        assert name == _TOOL
        call_count += 1
        if call_count == 1:
            return result("stale schema rejected", is_error=True)
        return result("replacement:7:true", is_error=False)

    def invalidate() -> None:
        nonlocal invalidated
        invalidated = True

    recorder = _MCPToolSchemaDriftRecorder(
        original_list_tools=list_tools,
        original_call_tool=call_tool,
        invalidate_tools_cache=invalidate,
        fault=fault(),
        protocol_version="2026-07-28",
    )

    await recorder.list_tools()
    await recorder.call_tool(_TOOL, {"query": "stale"})
    assert invalidated

    # Deliberately bypass the next-turn list_tools() call. Even though the second call uses the
    # correct v2 arguments and the fake server returns success, it cannot be credited as adaptation
    # because the evaluator never observed refreshed v2 discovery before the call.
    await recorder.call_tool(
        _TOOL,
        {"customer_id": 7, "include_history": True},
    )

    with pytest.raises(AdapterPreconditionError) as exc_info:
        recorder.require_complete_relation()

    assert exc_info.value.code == "mcp_schema_recovery_before_refresh"
    assert "before refreshed v2 discovery" in exc_info.value.reason
