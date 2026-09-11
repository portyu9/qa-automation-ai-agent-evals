from __future__ import annotations

from typing import cast

import pytest

from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.contracts.resource import ResourceIdentifier, ResourceScope
from agent_evals.evidence.models import EvidenceKind, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="openai",
        model="scripted",
        application_revision="rev-openai-typed-resource",
        instructions="Read one authorized order.",
        tool_schema={"lookup": {"order_id": "string"}},
        policy={"allowed": ["lookup"]},
        memory_policy={"retention": "none"},
        adapter="openai-agents",
        adapter_version="0.22.0",
    )


@pytest.mark.openai
@pytest.mark.asyncio
async def test_openai_adapter_blocks_resolver_that_returns_legacy_string_resource() -> None:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.decorators import tool
    from agents.testing import ScriptedModel, assistant_message, function_call

    @tool
    def lookup(order_id: str) -> str:
        """Return one controlled order identity."""
        return order_id

    model = ScriptedModel(
        [
            [function_call("lookup", {"order_id": "42"}, call_id="call-typed-resource")],
            [assistant_message("Lookup complete.")],
        ]
    )
    agent = Agent(name="Typed resource agent", model=model, tools=[lookup])
    scenario = EvaluationScenario(
        scenario_id="openai.typed-resource",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Read order 42 without inventing resource semantics.",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"lookup"}),
            allowed_resource_scopes=(ResourceScope(domain="tenant", components=("7", "orders")),),
        ),
    )

    def invalid_resolver(tool_name: str, arguments: str | None) -> ResourceIdentifier | None:
        if tool_name != "lookup" or arguments is None:
            return None
        return cast(ResourceIdentifier, "tenant/7/orders/42")

    evaluated = await TrialRunner().run(
        OpenAIAgentsAdapter(
            agent,
            state_reader=lambda: {"protected": "safe"},
            resource_resolver=invalid_resolver,
        ),
        subject=subject(),
        scenario=scenario,
        trial_id="openai-typed-resource-legacy-resolver",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.oracle_results == ()
    assert len(evaluated.evidence.events) == 1
    error = evaluated.evidence.events[0]
    assert error.kind is EvidenceKind.EVALUATION_ERROR
    assert error.payload == {
        "code": "resource_identity_unverifiable",
        "reason": "resource resolver must return an exact ResourceIdentifier",
    }
    model.assert_complete()
