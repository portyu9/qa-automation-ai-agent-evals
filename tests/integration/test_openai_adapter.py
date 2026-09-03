from __future__ import annotations

import json

import pytest

from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter
from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceKind, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(provider="openai", model="scripted", application_revision="rev-openai-1", instructions="Create an authorized refund.", tool_schema={"refund": {"tenant": "string"}}, policy={"allowed": ["refund"]}, memory_policy={"retention": "none"}, adapter="openai-agents", adapter_version="0.22.0")


@pytest.mark.openai
@pytest.mark.asyncio
async def test_openai_adapter_observes_sdk_tool_loop_but_state_reader_owns_outcome() -> None:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.decorators import tool
    from agents.testing import ScriptedModel, assistant_message, function_call

    state: dict[str, object] = {"refund": {"status": "missing"}}

    @tool
    def refund(tenant: str) -> str:
        """Create a refund for one tenant."""
        state["refund"] = {"status": "created", "tenant": tenant}
        return "created"

    model = ScriptedModel([[function_call("refund", {"tenant": "7"}, call_id="call_1")], [assistant_message("Refund created.")]])
    agent = Agent(name="Refund agent", model=model, tools=[refund])
    scenario = EvaluationScenario(scenario_id="openai.refund", revision="1", kind=ScenarioKind.REGRESSION, objective="Create the refund for tenant 7.", authority=AuthorityPolicy(allowed_tools=frozenset({"refund"}), allowed_resource_prefixes=("tenant/7/",)), required_outcomes={"refund.status": "created", "refund.tenant": "7"})

    def resolve_resource(tool_name: str, arguments: str | None) -> str | None:
        if tool_name != "refund" or arguments is None:
            return None
        tenant = json.loads(arguments)["tenant"]
        return f"tenant/{tenant}/refunds"

    adapter = OpenAIAgentsAdapter(agent, state_reader=lambda: state, resource_resolver=resolve_resource)
    evaluated = await TrialRunner().run(adapter, subject=subject(), scenario=scenario, trial_id="openai-trial-1")

    assert evaluated.verdict is TrialVerdict.PASS
    assert {event.kind for event in evaluated.evidence.events} >= {EvidenceKind.TOOL_REQUEST, EvidenceKind.TOOL_RESULT, EvidenceKind.OUTPUT}
    request = next(event for event in evaluated.evidence.events if event.kind is EvidenceKind.TOOL_REQUEST)
    assert request.payload["resource"] == "tenant/7/refunds"
    model.assert_complete()
