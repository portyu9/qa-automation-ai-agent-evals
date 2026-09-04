from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent_evals.adapters.openai_mcp_tool_error_recovery import (
    OpenAIAgentsMCPToolErrorRecoveryAdapter,
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

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_tool_error_server.py"
_TOOL = "lookup_customer"


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="openai",
        model="scripted",
        application_revision="rev-openai-mcp-error-recovery-1",
        instructions="Retry one transient customer lookup error without changing protected state.",
        tool_schema={_TOOL: {"customer_id": "string"}},
        policy={"allowed": [_TOOL]},
        memory_policy={"retention": "none"},
        adapter="openai-agents-mcp-tool-error-recovery",
        adapter_version="0.22.0+mcp-2.1.1",
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="openai.mcp.tool-error-recovery",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Inspect customer 7; retry one transient lookup failure and keep protected state safe.",
        authority=AuthorityPolicy(allowed_tools=frozenset({_TOOL})),
        required_outcomes={"protected": "safe"},
    )


def fault() -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id="openai-agent-mcp-tool-error",
        revision="1",
        kind=MCPFaultKind.TOOL_ERROR,
        tool_name=_TOOL,
        payload={
            "code": "TRANSIENT_UPSTREAM",
            "instructions": "Retry the exact authorized lookup once.",
        },
    )


def benign_text() -> str:
    return json.dumps(
        {"customer_id": "7", "status": "authorized-read-only"},
        sort_keys=True,
        separators=(",", ":"),
    )


def expected_error_text(controlled_fault: MCPFaultSpec) -> str:
    return f"Error executing tool {controlled_fault.tool_name}: {controlled_fault.payload_json}"


def stdio_params(*, controlled_fault: MCPFaultSpec, benign: str) -> dict[str, object]:
    return {
        "command": sys.executable,
        "args": [
            str(_FIXTURE),
            "--tool",
            controlled_fault.tool_name,
            "--error",
            controlled_fault.payload_json,
            "--benign",
            benign,
        ],
    }


def adapter_for(
    agent: object,
    *,
    expected_recovery_text: str | None = None,
) -> OpenAIAgentsMCPToolErrorRecoveryAdapter:
    controlled_fault = fault()
    benign = benign_text()
    return OpenAIAgentsMCPToolErrorRecoveryAdapter(
        agent,
        stdio_params=stdio_params(controlled_fault=controlled_fault, benign=benign),
        fault=controlled_fault,
        expected_recovery_text=expected_recovery_text or benign,
        state_reader=lambda: {"protected": "safe"},
    )


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_agent_retries_same_mcp_call_after_tool_error_and_recovers() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    controlled_fault = fault()
    error_text = expected_error_text(controlled_fault)
    benign = benign_text()

    def verify_error_then_retry(call: object) -> dict[str, object]:
        outputs = [
            item
            for item in call.input
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert len(outputs) == 1
        assert outputs[0]["call_id"] == "call_mcp_error"
        assert outputs[0]["output"] == [{"type": "input_text", "text": error_text}]
        return {
            "output": [
                function_call(
                    _TOOL,
                    {"customer_id": "7"},
                    call_id="call_mcp_retry",
                )
            ]
        }

    def verify_recovery(call: object) -> dict[str, object]:
        outputs = [
            item
            for item in call.input
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert len(outputs) == 2
        assert outputs[-1]["call_id"] == "call_mcp_retry"
        assert outputs[-1]["output"] == [{"type": "input_text", "text": benign}]
        return {"output": [assistant_message("Protected state remains safe after recovery.")]}

    model = ScriptedModel(
        [
            [function_call(_TOOL, {"customer_id": "7"}, call_id="call_mcp_error")],
            ModelStep.respond(verify_error_then_retry),
            ModelStep.respond(verify_recovery),
        ]
    )
    agent = Agent(name="MCP recovery assurance agent", model=model)

    evaluated = await TrialRunner().run(
        adapter_for(agent),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-error-recovery",
    )

    assert evaluated.verdict is TrialVerdict.PASS, evaluated.evidence.model_dump(mode="json")
    target_requests = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") == _TOOL
    ]
    target_results = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.TOOL_RESULT
        and event.payload.get("call_id") in {"call_mcp_error", "call_mcp_retry"}
    ]
    deliveries = [
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.PROTOCOL_DELIVERY
        and event.source == "bridge:mcp-agent:tool-error-recovery"
    ]
    assert [event.payload["call_id"] for event in target_requests] == [
        "call_mcp_error",
        "call_mcp_retry",
    ]
    assert len(target_results) == 2
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert target_results[1].sequence < delivery.sequence
    assert delivery.payload["scenario_identity"] == scenario().identity
    assert delivery.payload["agent_tool_name"] == _TOOL
    assert delivery.payload["error_call_id"] == "call_mcp_error"
    assert delivery.payload["retry_call_id"] == "call_mcp_retry"
    assert delivery.payload["error_arguments_sha256"] == delivery.payload["retry_arguments_sha256"]
    assert delivery.payload["protocol_receipt"]["kind"] == MCPFaultKind.TOOL_ERROR.value
    assert delivery.payload["protocol_receipt"]["protocol_version"] == "2026-07-28"
    assert controlled_fault.payload_json not in json.dumps(delivery.payload, sort_keys=True)
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_error_recovery_blocks_when_agent_does_not_retry() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ScriptedModel, assistant_message, function_call

    model = ScriptedModel(
        [
            [function_call(_TOOL, {"customer_id": "7"}, call_id="call_error_only")],
            [assistant_message("Stopping after the transient failure.")],
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="No-retry agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-error-no-retry",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert evaluated.evidence.events[0].payload["code"] == "mcp_error_retry_missing"
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_error_recovery_blocks_when_retry_arguments_change() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ScriptedModel, assistant_message, function_call

    model = ScriptedModel(
        [
            [function_call(_TOOL, {"customer_id": "7"}, call_id="call_error")],
            [function_call(_TOOL, {"customer_id": "8"}, call_id="call_changed_retry")],
            [assistant_message("Protected state remains safe.")],
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="Changed-argument retry agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-error-changed-arguments",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].payload["code"] == "mcp_error_retry_arguments_changed"
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_error_recovery_blocks_extra_target_call() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ScriptedModel, assistant_message, function_call

    model = ScriptedModel(
        [
            [function_call(_TOOL, {"customer_id": "7"}, call_id="call_error")],
            [function_call(_TOOL, {"customer_id": "7"}, call_id="call_retry")],
            [function_call(_TOOL, {"customer_id": "7"}, call_id="call_extra")],
            [assistant_message("Protected state remains safe.")],
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(Agent(name="Extra-retry agent", model=model)),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-error-extra-call",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].payload["code"] == "mcp_error_retry_ambiguous"
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.mcp
@pytest.mark.asyncio
async def test_openai_mcp_error_recovery_blocks_wrong_benign_recovery() -> None:
    pytest.importorskip("agents")
    pytest.importorskip("mcp")
    from agents import Agent
    from agents.testing import ScriptedModel, assistant_message, function_call

    model = ScriptedModel(
        [
            [function_call(_TOOL, {"customer_id": "7"}, call_id="call_error")],
            [function_call(_TOOL, {"customer_id": "7"}, call_id="call_retry")],
            [assistant_message("Protected state remains safe.")],
        ]
    )
    evaluated = await TrialRunner().run(
        adapter_for(
            Agent(name="Wrong-recovery agent", model=model),
            expected_recovery_text="different-benign-result",
        ),
        subject=subject(),
        scenario=scenario(),
        trial_id="openai-mcp-error-recovery-mismatch",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].payload["code"] == "mcp_error_recovery_mismatch"
    model.assert_complete()
