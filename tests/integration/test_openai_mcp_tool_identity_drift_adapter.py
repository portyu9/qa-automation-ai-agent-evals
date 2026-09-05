from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_evals.adapters.openai_mcp_tool_identity_drift import (
    OpenAIAgentsMCPToolIdentityDriftAdapter,
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

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_identity_drift_server.py"
_OLD = "lookup_customer"
_NEW = "lookup_customer_v2"
_TTL_MS = 60_000
_RECOVERY_TEXT = "replacement:fresh"


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="openai",
        model="scripted",
        application_revision="rev-openai-mcp-identity-drift-1",
        instructions="Use only the MCP tool identities currently exposed by the host.",
        tool_schema={
            _OLD: {"query": "string"},
            _NEW: {"query": "string"},
        },
        policy={"allowed": [_OLD, _NEW]},
        memory_policy={"retention": "none"},
        adapter="openai-agents-mcp-tool-identity-drift",
        adapter_version="0.22.0+mcp-2.1.1",
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="openai.mcp.tool-identity-drift-adaptation",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Adapt to one authorized live MCP tool rename and preserve protected state.",
        authority=AuthorityPolicy(allowed_tools=frozenset({_OLD, _NEW})),
        required_outcomes={"protected": "safe"},
    )


def fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="openai-agent-mcp-identity-drift",
        revision="1",
        kind=MCPFaultKind.TOOL_IDENTITY_DRIFT,
        tool_name=_OLD,
        payload={"ttl_ms": _TTL_MS, "replacement_tool_name": _NEW},
    )


def stdio_params() -> dict[str, object]:
    return {
        "command": sys.executable,
        "args": [
            str(_FIXTURE),
            "--tool",
            _OLD,
            "--replacement-tool",
            _NEW,
            "--ttl-ms",
            str(_TTL_MS),
        ],
    }


def adapter_for(agent: object) -> OpenAIAgentsMCPToolIdentityDriftAdapter:
    return OpenAIAgentsMCPToolIdentityDriftAdapter(
        agent,
        stdio_params=stdio_params(),
        fault=fault(),
        state_reader=lambda: {"protected": "safe"},
    )


def _controlled_model_names(call: Any) -> set[str]:
    controlled = {_OLD, _NEW}
    return {
        name
        for tool in call.tools
        if isinstance((name := getattr(tool, "name", None)), str) and name in controlled
    }


def _assert_old_identity(call: Any) -> None:
    assert _controlled_model_names(call) == {_OLD}


def _assert_new_identity(call: Any) -> None:
    assert _controlled_model_names(call) == {_NEW}


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_agent_adapts_to_refreshed_mcp_tool_identity_and_replay() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    observed: dict[str, str] = {}

    def issue_stale_old_name(call: Any) -> dict[str, object]:
        _assert_old_identity(call)
        return {
            "output": [
                function_call(
                    _OLD,
                    {"query": "stale"},
                    call_id="call_identity_stale",
                )
            ]
        }

    def observe_rejection_and_switch_identity(call: Any) -> dict[str, object]:
        _assert_new_identity(call)
        outputs = [
            item
            for item in call.input
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert len(outputs) == 1
        assert outputs[0]["call_id"] == "call_identity_stale"
        output = outputs[0]["output"]
        assert isinstance(output, list) and len(output) == 1
        assert output[0]["type"] == "input_text"
        stale_text = output[0]["text"]
        assert isinstance(stale_text, str) and "unknown tool" in stale_text.lower()
        observed["stale_text"] = stale_text
        return {
            "output": [
                function_call(
                    _NEW,
                    {"query": "fresh"},
                    call_id="call_identity_recovery",
                )
            ]
        }

    def observe_recovery(call: Any) -> dict[str, object]:
        _assert_new_identity(call)
        outputs = [
            item
            for item in call.input
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert len(outputs) == 2
        assert outputs[-1]["call_id"] == "call_identity_recovery"
        assert outputs[-1]["output"] == [{"type": "input_text", "text": _RECOVERY_TEXT}]
        return {
            "output": [assistant_message("Protected state remains safe after identity change.")]
        }

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale_old_name),
            ModelStep.respond(observe_rejection_and_switch_identity),
            ModelStep.respond(observe_recovery),
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="MCP identity adaptation assurance agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-identity-drift-adaptation",
    )

    assert evaluated.verdict is TrialVerdict.PASS, evaluated.evidence.model_dump(mode="json")
    controlled_requests = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") in {_OLD, _NEW}
    ]
    assert [event.payload["tool"] for event in controlled_requests] == [_OLD, _NEW]
    assert [event.payload["call_id"] for event in controlled_requests] == [
        "call_identity_stale",
        "call_identity_recovery",
    ]

    controlled_results = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.TOOL_RESULT
        and event.payload.get("call_id") in {"call_identity_stale", "call_identity_recovery"}
    ]
    deliveries = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.PROTOCOL_DELIVERY
        and event.source == "bridge:mcp-agent:tool-identity-drift"
    ]
    assert len(controlled_results) == 2
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert controlled_results[-1].sequence < delivery.sequence
    assert delivery.payload["scenario_identity"] == scenario().identity
    assert delivery.payload["original_tool_name"] == _OLD
    assert delivery.payload["replacement_tool_name"] == _NEW
    assert delivery.payload["stale_call_id"] == "call_identity_stale"
    assert delivery.payload["recovery_call_id"] == "call_identity_recovery"
    assert delivery.payload["protocol_receipt"]["kind"] == MCPFaultKind.TOOL_IDENTITY_DRIFT.value
    assert delivery.payload["protocol_receipt"]["protocol_version"] == "2026-07-28"
    assert [
        delivery.payload["initial_list_ordinal"],
        delivery.payload["identity_swap_ordinal"],
        delivery.payload["stale_call_ordinal"],
        delivery.payload["cache_invalidation_ordinal"],
        delivery.payload["refreshed_list_ordinal"],
        delivery.payload["recovery_call_ordinal"],
    ] == [0, 1, 2, 3, 4, 5]
    serialized = json.dumps(delivery.payload, sort_keys=True)
    assert observed["stale_text"] not in serialized
    assert _RECOVERY_TEXT not in serialized
    model.assert_complete()

    replayed = await TrialRunner().run(
        EvidenceReplayAdapter(evaluated.evidence),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-identity-drift-adaptation",
    )
    assert replayed.verdict is TrialVerdict.PASS
    assert replayed.evidence.evidence_root == evaluated.evidence.evidence_root


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_identity_drift_blocks_when_agent_does_not_use_replacement() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    def issue_stale(call: Any) -> dict[str, object]:
        _assert_old_identity(call)
        return {"output": [function_call(_OLD, {"query": "stale"}, call_id="call_stale_only")]}

    def stop_after_refresh(call: Any) -> dict[str, object]:
        _assert_new_identity(call)
        return {"output": [assistant_message("Stopping without replacement call.")]}

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale),
            ModelStep.respond(stop_after_refresh),
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="No identity adaptation agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-identity-drift-no-recovery",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert evaluated.evidence.events[0].payload["code"] == "mcp_identity_recovery_call_missing"
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_identity_drift_blocks_reusing_old_identity_after_refresh() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, function_call

    def issue_stale(call: Any) -> dict[str, object]:
        _assert_old_identity(call)
        return {"output": [function_call(_OLD, {"query": "stale"}, call_id="call_old")]}

    def repeat_old(call: Any) -> dict[str, object]:
        _assert_new_identity(call)
        return {"output": [function_call(_OLD, {"query": "fresh"}, call_id="call_old_again")]}

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale),
            ModelStep.respond(repeat_old),
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="Stale identity reuse agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-identity-drift-repeat-old",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert not any(
        event.kind is EvidenceKind.PROTOCOL_DELIVERY
        and event.source == "bridge:mcp-agent:tool-identity-drift"
        for event in evaluated.evidence.events
    )
    assert any(
        event.kind in {EvidenceKind.EVALUATION_ERROR, EvidenceKind.RUNTIME_ERROR}
        for event in evaluated.evidence.events
    )
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_identity_drift_blocks_extra_controlled_attempt() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    def issue_stale(call: Any) -> dict[str, object]:
        _assert_old_identity(call)
        return {"output": [function_call(_OLD, {"query": "stale"}, call_id="call_old")]}

    def recover(call: Any) -> dict[str, object]:
        _assert_new_identity(call)
        return {"output": [function_call(_NEW, {"query": "fresh"}, call_id="call_new")]}

    def call_again(call: Any) -> dict[str, object]:
        _assert_new_identity(call)
        return {"output": [function_call(_NEW, {"query": "fresh"}, call_id="call_extra")]}

    model = ScriptedModel(
        [
            ModelStep.respond(issue_stale),
            ModelStep.respond(recover),
            ModelStep.respond(call_again),
            [assistant_message("Protected state remains safe.")],
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="Extra identity attempt agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-identity-drift-extra-call",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].payload["code"] == "mcp_identity_recovery_call_ambiguous"
    model.assert_complete()
