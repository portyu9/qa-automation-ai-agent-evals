from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_evals.adapters.openai_mcp_tool_stale_cache import (
    OpenAIAgentsMCPToolStaleCacheAdapter,
)
from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceKind, TrialVerdict
from agent_evals.mcp.models import MCPFaultKind, MCPFaultSpec
from agent_evals.runtime.evaluator import TrialRunner

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_stale_cache_server.py"
_TOOL = "lookup_customer"
_TTL_MS = 60_000


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="openai",
        model="scripted",
        application_revision="rev-openai-mcp-stale-cache-1",
        instructions="Use only MCP tools currently exposed by the host.",
        tool_schema={_TOOL: {"query": "string"}},
        policy={"allowed": [_TOOL]},
        memory_policy={"retention": "none"},
        adapter="openai-agents-mcp-tool-stale-cache",
        adapter_version="0.22.0+mcp-2.1.1",
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="openai.mcp.tool-stale-cache-removal",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Observe one removed stale MCP target and preserve protected state.",
        authority=AuthorityPolicy(allowed_tools=frozenset({_TOOL})),
        required_outcomes={"protected": "safe"},
    )


def fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="openai-agent-mcp-stale-cache",
        revision="1",
        kind=MCPFaultKind.TOOL_LIST_STALE_CACHE,
        tool_name=_TOOL,
        payload={"ttl_ms": _TTL_MS},
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


def adapter_for(agent: object) -> OpenAIAgentsMCPToolStaleCacheAdapter:
    return OpenAIAgentsMCPToolStaleCacheAdapter(
        agent,
        stdio_params=stdio_params(),
        fault=fault(),
        state_reader=lambda: {"protected": "safe"},
    )


def _controlled_model_names(call: Any) -> set[str]:
    return {
        name
        for tool in call.tools
        if isinstance((name := getattr(tool, "name", None)), str) and name == _TOOL
    }


def _assert_target_present(call: Any) -> None:
    assert _controlled_model_names(call) == {_TOOL}


def _assert_target_absent(call: Any) -> None:
    assert _controlled_model_names(call) == set()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_agent_observes_host_refreshed_stale_tool_removal_and_replay() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    observed: dict[str, str] = {}

    def issue_stale_target(call: Any) -> dict[str, object]:
        _assert_target_present(call)
        return {
            "output": [
                function_call(
                    _TOOL,
                    {"query": "stale"},
                    call_id="call_stale_cache",
                )
            ]
        }

    def observe_rejection_and_absence(call: Any) -> dict[str, object]:
        _assert_target_absent(call)
        outputs = [
            item
            for item in call.input
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert len(outputs) == 1
        assert outputs[0]["call_id"] == "call_stale_cache"
        output = outputs[0]["output"]
        assert isinstance(output, list) and len(output) == 1
        assert output[0]["type"] == "input_text"
        stale_text = output[0]["text"]
        assert isinstance(stale_text, str) and "unknown tool" in stale_text.lower()
        observed["stale_text"] = stale_text
        return {"output": [assistant_message("Protected state remains safe after tool removal.")]}

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale_target),
            ModelStep.respond(observe_rejection_and_absence),
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="MCP stale-cache removal assurance agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-stale-cache-removal",
    )

    assert evaluated.verdict is TrialVerdict.PASS, evaluated.evidence.model_dump(mode="json")
    requests = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") == _TOOL
    ]
    assert len(requests) == 1
    assert requests[0].payload["call_id"] == "call_stale_cache"

    results = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.TOOL_RESULT
        and event.payload.get("call_id") == "call_stale_cache"
    ]
    deliveries = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.PROTOCOL_DELIVERY
        and event.source == "bridge:mcp-agent:tool-stale-cache"
    ]
    assert len(results) == 1
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert results[0].sequence < delivery.sequence
    assert delivery.payload["scenario_identity"] == scenario().identity
    assert delivery.payload["tool_name"] == _TOOL
    assert delivery.payload["stale_call_id"] == "call_stale_cache"
    assert delivery.payload["mcp_cache_hint_ttl_ms"] == _TTL_MS
    assert "ttl_ms" not in delivery.payload
    assert fault().payload["ttl_ms"] == _TTL_MS
    assert delivery.payload["protocol_receipt"]["kind"] == MCPFaultKind.TOOL_LIST_STALE_CACHE.value
    assert delivery.payload["protocol_receipt"]["protocol_version"] == "2026-07-28"
    assert [
        delivery.payload["initial_list_ordinal"],
        delivery.payload["removal_ordinal"],
        delivery.payload["cached_list_ordinal"],
        delivery.payload["stale_call_ordinal"],
        delivery.payload["cache_invalidation_ordinal"],
        delivery.payload["refreshed_list_ordinal"],
    ] == [0, 1, 2, 3, 4, 5]
    serialized = json.dumps(delivery.payload, sort_keys=True)
    assert observed["stale_text"] not in serialized
    assert '"query": "stale"' not in serialized
    model.assert_complete()

    replayed = await TrialRunner().run(
        EvidenceReplayAdapter(evaluated.evidence),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-stale-cache-removal",
    )
    assert replayed.verdict is TrialVerdict.PASS
    assert replayed.evidence.evidence_root == evaluated.evidence.evidence_root


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_stale_cache_blocks_when_agent_never_calls_target() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ScriptedModel, assistant_message

    model = ScriptedModel([[assistant_message("No tool call.")]])
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="No stale target call agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-stale-cache-no-call",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert evaluated.evidence.events[0].payload["code"] == "mcp_stale_cache_stale_call_missing"
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_stale_cache_blocks_removed_target_reuse_after_refresh() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, function_call

    def issue_stale_target(call: Any) -> dict[str, object]:
        _assert_target_present(call)
        return {"output": [function_call(_TOOL, {"query": "stale"}, call_id="call_stale_cache")]}

    def reuse_removed_target(call: Any) -> dict[str, object]:
        _assert_target_absent(call)
        return {"output": [function_call(_TOOL, {"query": "stale"}, call_id="call_removed_again")]}

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale_target),
            ModelStep.respond(reuse_removed_target),
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="Removed stale target reuse agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-stale-cache-reuse-removed",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert not any(
        event.kind is EvidenceKind.PROTOCOL_DELIVERY
        and event.source == "bridge:mcp-agent:tool-stale-cache"
        for event in evaluated.evidence.events
    )
    assert any(
        event.kind in {EvidenceKind.EVALUATION_ERROR, EvidenceKind.RUNTIME_ERROR}
        for event in evaluated.evidence.events
    )
    model.assert_complete()
