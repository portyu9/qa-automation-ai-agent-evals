from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from agent_evals.adapters.openai_mcp_tool_schema_drift import (
    OpenAIAgentsMCPToolSchemaDriftAdapter,
)
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceKind
from agent_evals.mcp.models import MCPFaultKind, MCPFaultSpec

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_schema_drift_server.py"
_TOOL = "lookup_customer"
_TTL_MS = 60_000


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="openai",
        model="scripted",
        application_revision="schema-drift-contract-direct-1",
        instructions="Adapt only after the host supplies the replacement MCP schema.",
        tool_schema={_TOOL: {"v1": "query:string", "v2": "customer_id:int,history:bool"}},
        policy={"allowed": [_TOOL]},
        memory_policy={"retention": "none"},
        adapter="openai-agents-mcp-tool-schema-drift",
        adapter_version="0.22.0+mcp-2.1.1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="openai.mcp.tool-schema-drift-direct-contract",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Close the host-refreshed MCP schema-drift bridge directly.",
    )


def _fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="openai-agent-mcp-schema-drift-direct",
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


def _assert_required_schema(call: Any, required: set[str]) -> None:
    matching = [tool for tool in call.tools if getattr(tool, "name", None) == _TOOL]
    assert len(matching) == 1
    schema = getattr(matching[0], "params_json_schema", None)
    assert isinstance(schema, dict)
    assert set(schema.get("required", [])) == required


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_schema_drift_adapter_closes_direct_bridge_contract() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    def stale_call(call: Any) -> dict[str, object]:
        _assert_required_schema(call, {"query"})
        return {
            "output": [
                function_call(_TOOL, {"query": "stale"}, call_id="direct_schema_stale")
            ]
        }

    def corrected_call(call: Any) -> dict[str, object]:
        _assert_required_schema(call, {"customer_id", "include_history"})
        return {
            "output": [
                function_call(
                    _TOOL,
                    {"customer_id": 7, "include_history": True},
                    call_id="direct_schema_recovery",
                )
            ]
        }

    model = ScriptedModel(
        [
            ModelStep.respond(stale_call),
            ModelStep.respond(corrected_call),
            [assistant_message("adapted")],
        ]
    )
    adapter = OpenAIAgentsMCPToolSchemaDriftAdapter(
        Agent(name="Direct schema-drift contract agent", model=model),
        stdio_params={
            "command": sys.executable,
            "args": [
                str(_FIXTURE),
                "--tool",
                _TOOL,
                "--ttl-ms",
                str(_TTL_MS),
            ],
        },
        fault=_fault(),
        state_reader=lambda: {},
    )

    result = await adapter.execute(
        subject=_subject(),
        scenario=_scenario(),
        trial_id="direct-schema-drift-contract",
    )

    deliveries = [event for event in result.events if event.kind is EvidenceKind.PROTOCOL_DELIVERY]
    assert len(deliveries) == 1
    assert deliveries[0].source == "bridge:mcp-agent:tool-schema-drift"
    model.assert_complete()
