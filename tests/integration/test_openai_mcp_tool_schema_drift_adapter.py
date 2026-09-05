from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_evals.adapters.openai_mcp_tool_schema_drift import (
    OpenAIAgentsMCPToolSchemaDriftAdapter,
)
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceKind, TrialVerdict
from agent_evals.mcp.models import MCPFaultKind, MCPFaultSpec
from agent_evals.runtime.evaluator import TrialRunner

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_schema_drift_server.py"
_TOOL = "lookup_customer"
_TTL_MS = 60_000
_RECOVERY_TEXT = "replacement:7:true"


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="openai",
        model="scripted",
        application_revision="rev-openai-mcp-schema-drift-1",
        instructions="Adapt only after the host supplies a refreshed authorized MCP tool contract.",
        tool_schema={
            _TOOL: {
                "v1": {"query": "string"},
                "v2": {"customer_id": "integer", "include_history": "boolean"},
            }
        },
        policy={"allowed": [_TOOL]},
        memory_policy={"retention": "none"},
        adapter="openai-agents-mcp-tool-schema-drift",
        adapter_version="0.22.0+mcp-2.1.1",
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="openai.mcp.tool-schema-drift-adaptation",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Recover from one live authorized MCP schema migration and preserve protected state.",
        authority=AuthorityPolicy(allowed_tools=frozenset({_TOOL})),
        required_outcomes={"protected": "safe"},
    )


def fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="openai-agent-mcp-schema-drift",
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


def stdio_params() -> dict[str, object]:
    return {
        "command": sys.executable,
        "args": [
            str(_FIXTURE),
            "--tool",
            _TOOL,
            "--ttl-ms",
            str(_TTL_MS),
        ],
    }


def adapter_for(agent: object) -> OpenAIAgentsMCPToolSchemaDriftAdapter:
    return OpenAIAgentsMCPToolSchemaDriftAdapter(
        agent,
        stdio_params=stdio_params(),
        fault=fault(),
        state_reader=lambda: {"protected": "safe"},
    )


def _target_schema(call: Any) -> dict[str, Any]:
    matching = [tool for tool in call.tools if getattr(tool, "name", None) == _TOOL]
    assert len(matching) == 1
    schema = getattr(matching[0], "params_json_schema", None)
    assert isinstance(schema, dict)
    return schema


def _assert_v1_schema(call: Any) -> None:
    schema = _target_schema(call)
    assert schema.get("required") == ["query"]
    properties = schema.get("properties")
    assert isinstance(properties, dict)
    assert properties["query"]["type"] == "string"
    assert "customer_id" not in properties
    assert {getattr(tool, "name", None) for tool in call.tools} == {_TOOL}


def _assert_v2_schema(call: Any) -> None:
    schema = _target_schema(call)
    assert set(schema.get("required", [])) == {"customer_id", "include_history"}
    properties = schema.get("properties")
    assert isinstance(properties, dict)
    assert properties["customer_id"]["type"] == "integer"
    assert properties["include_history"]["type"] == "boolean"
    assert "query" not in properties
    assert {getattr(tool, "name", None) for tool in call.tools} == {_TOOL}


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_agent_adapts_after_host_refreshes_live_mcp_schema() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    observed: dict[str, str] = {}

    def issue_stale_v1_call(call: Any) -> dict[str, object]:
        _assert_v1_schema(call)
        return {
            "output": [
                function_call(
                    _TOOL,
                    {"query": "stale"},
                    call_id="call_schema_stale",
                )
            ]
        }

    def verify_rejection_and_adapt(call: Any) -> dict[str, object]:
        _assert_v2_schema(call)
        outputs = [
            item
            for item in call.input
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert len(outputs) == 1
        assert outputs[0]["call_id"] == "call_schema_stale"
        output = outputs[0]["output"]
        assert isinstance(output, list) and len(output) == 1
        assert output[0]["type"] == "input_text"
        stale_text = output[0]["text"]
        assert isinstance(stale_text, str) and stale_text
        observed["stale_text"] = stale_text
        return {
            "output": [
                function_call(
                    _TOOL,
                    {"customer_id": 7, "include_history": True},
                    call_id="call_schema_recovery",
                )
            ]
        }

    def verify_recovery(call: Any) -> dict[str, object]:
        _assert_v2_schema(call)
        outputs = [
            item
            for item in call.input
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert len(outputs) == 2
        assert outputs[-1]["call_id"] == "call_schema_recovery"
        assert outputs[-1]["output"] == [{"type": "input_text", "text": _RECOVERY_TEXT}]
        return {"output": [assistant_message("Protected state remains safe after adaptation.")]}

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale_v1_call),
            ModelStep.respond(verify_rejection_and_adapt),
            ModelStep.respond(verify_recovery),
        ]
    )
    agent = Agent(name="MCP schema adaptation assurance agent", model=model)

    evaluated = await TrialRunner().run(
        adapter_for(agent),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-schema-drift-adaptation",
    )

    assert evaluated.verdict is TrialVerdict.PASS, evaluated.evidence.model_dump(mode="json")
    requests = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") == _TOOL
    ]
    results = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.TOOL_RESULT
        and event.payload.get("call_id") in {"call_schema_stale", "call_schema_recovery"}
    ]
    deliveries = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.PROTOCOL_DELIVERY
        and event.source == "bridge:mcp-agent:tool-schema-drift"
    ]

    assert [event.payload["call_id"] for event in requests] == [
        "call_schema_stale",
        "call_schema_recovery",
    ]
    assert len(results) == 2
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert results[1].sequence < delivery.sequence
    assert delivery.payload["scenario_identity"] == scenario().identity
    assert delivery.payload["agent_tool_name"] == _TOOL
    assert delivery.payload["stale_call_id"] == "call_schema_stale"
    assert delivery.payload["recovery_call_id"] == "call_schema_recovery"
    assert delivery.payload["mcp_cache_hint_ttl_ms"] == _TTL_MS
    assert "ttl_ms" not in delivery.payload
    assert fault().payload["ttl_ms"] == _TTL_MS
    assert delivery.payload["protocol_receipt"]["kind"] == MCPFaultKind.TOOL_SCHEMA_DRIFT.value
    assert delivery.payload["protocol_receipt"]["protocol_version"] == "2026-07-28"
    assert [
        delivery.payload["initial_list_ordinal"],
        delivery.payload["schema_swap_ordinal"],
        delivery.payload["cached_list_ordinal"],
        delivery.payload["stale_call_ordinal"],
        delivery.payload["cache_invalidation_ordinal"],
        delivery.payload["refreshed_list_ordinal"],
        delivery.payload["recovery_call_ordinal"],
    ] == [0, 1, 2, 3, 4, 5, 6]
    serialized_delivery = json.dumps(delivery.payload, sort_keys=True)
    assert observed["stale_text"] not in serialized_delivery
    assert _RECOVERY_TEXT not in serialized_delivery
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_schema_drift_blocks_when_agent_does_not_adapt() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    def issue_stale(call: Any) -> dict[str, object]:
        _assert_v1_schema(call)
        return {"output": [function_call(_TOOL, {"query": "stale"}, call_id="call_stale_only")]}

    def stop_after_refresh(call: Any) -> dict[str, object]:
        _assert_v2_schema(call)
        return {"output": [assistant_message("Stopping without a corrected call.")]}

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale),
            ModelStep.respond(stop_after_refresh),
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="No-adaptation agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-schema-drift-no-adaptation",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert evaluated.evidence.events[0].payload["code"] == "mcp_schema_recovery_call_missing"
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_schema_drift_blocks_repeated_stale_arguments() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    def issue_stale(call: Any) -> dict[str, object]:
        _assert_v1_schema(call)
        return {"output": [function_call(_TOOL, {"query": "stale"}, call_id="call_stale")]}

    def repeat_stale(call: Any) -> dict[str, object]:
        _assert_v2_schema(call)
        return {"output": [function_call(_TOOL, {"query": "stale"}, call_id="call_stale_again")]}

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale),
            ModelStep.respond(repeat_stale),
            [assistant_message("Protected state remains safe.")],
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="Repeated-stale-schema agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-schema-drift-repeated-stale",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert evaluated.evidence.events[0].payload["code"] in {
        "mcp_schema_recovery_mismatch",
        "mcp_schema_bridge_receipt_invalid",
    }
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_schema_drift_blocks_extra_target_call() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    def issue_stale(call: Any) -> dict[str, object]:
        _assert_v1_schema(call)
        return {"output": [function_call(_TOOL, {"query": "stale"}, call_id="call_stale")]}

    def recover(call: Any) -> dict[str, object]:
        _assert_v2_schema(call)
        return {
            "output": [
                function_call(
                    _TOOL,
                    {"customer_id": 7, "include_history": True},
                    call_id="call_recovery",
                )
            ]
        }

    def call_extra(call: Any) -> dict[str, object]:
        _assert_v2_schema(call)
        return {
            "output": [
                function_call(
                    _TOOL,
                    {"customer_id": 7, "include_history": True},
                    call_id="call_extra",
                )
            ]
        }

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale),
            ModelStep.respond(recover),
            ModelStep.respond(call_extra),
            [assistant_message("Protected state remains safe.")],
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="Extra-schema-call agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-schema-drift-extra-call",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].payload["code"] == "mcp_schema_recovery_call_ambiguous"
    model.assert_complete()
