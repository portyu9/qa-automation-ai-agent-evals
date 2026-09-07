from __future__ import annotations

import pytest

from agent_evals.adapters.openai_side_effect_idempotency import (
    OpenAIAgentsSideEffectIdempotencyAdapter,
)
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceKind, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner
from agent_evals.side_effect.models import SideEffectIdempotencySpec

_ROOT = "Side-effect agent"
_TOOL = "apply_change"
_ARGUMENTS = {"operation_id": "op-7", "value": 3}


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="openai.side-effect-handoff-composition",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Apply operation op-7 twice without duplicating its physical effect.",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({_TOOL}),
            max_turns=6,
            max_tool_calls=2,
            root_agent=_ROOT,
        ),
        side_effect_idempotency=SideEffectIdempotencySpec(
            tool=_TOOL,
            key_argument="operation_id",
            expected_arguments=_ARGUMENTS,
        ),
        required_outcomes={"callback_calls": 2},
    )


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="openai",
        model="scripted",
        application_revision="side-effect-handoff-composition-1",
        instructions="Apply the same logical operation twice without duplicating its effect.",
        tool_schema={_TOOL: {"operation_id": "string", "value": "integer"}},
        policy={"handoff_authority": "scenario-bound"},
        memory_policy={"retention": "none"},
        adapter="openai-agents-side-effect-idempotency",
        adapter_version="0.22.0",
    )


@pytest.mark.openai
@pytest.mark.asyncio
async def test_side_effect_bridge_preserves_agent_provenance_under_handoff_authority() -> None:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.decorators import tool
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    effects: list[dict[str, object]] = []
    seen: set[str] = set()
    callback_calls = 0

    @tool
    def apply_change(operation_id: str, value: int) -> str:
        """Apply one controlled logical change."""
        nonlocal callback_calls
        callback_calls += 1
        if operation_id in seen:
            return "duplicate"
        seen.add(operation_id)
        effects.append({"operation_id": operation_id, "value": value})
        return "created"

    def issue_duplicate(call: object) -> dict[str, object]:
        outputs = [
            item
            for item in call.input  # type: ignore[attr-defined]
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert outputs[-1]["call_id"] == "effect-composed-1"
        return {
            "output": [
                function_call(
                    _TOOL,
                    _ARGUMENTS,
                    call_id="effect-composed-2",
                )
            ]
        }

    model = ScriptedModel(
        [
            [function_call(_TOOL, _ARGUMENTS, call_id="effect-composed-1")],
            ModelStep.respond(issue_duplicate),
            [assistant_message("Duplicate attempt complete.")],
        ]
    )

    evaluated = await TrialRunner().run(
        OpenAIAgentsSideEffectIdempotencyAdapter(
            Agent(name=_ROOT, model=model, tools=[apply_change]),
            state_reader=lambda: {
                "callback_calls": callback_calls,
                "effect_count": len(effects),
            },
            effect_reader=lambda: {"effects": [dict(item) for item in effects]},
        ),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="openai-side-effect-handoff-composition",
    )

    assert evaluated.verdict is TrialVerdict.PASS, evaluated.evidence.model_dump(mode="json")
    requests = [
        event for event in evaluated.evidence.events if event.kind is EvidenceKind.TOOL_REQUEST
    ]
    results = [
        event for event in evaluated.evidence.events if event.kind is EvidenceKind.TOOL_RESULT
    ]
    observation = next(
        event
        for event in evaluated.evidence.events
        if event.kind is EvidenceKind.SIDE_EFFECT_OBSERVATION
    )

    assert len(requests) == len(results) == 2
    assert all(event.payload["agent"] == _ROOT for event in (*requests, *results))
    assert observation.payload["mutation_count"] == 1
    assert callback_calls == 2
    assert len(effects) == 1
    assert not any(
        event.kind is EvidenceKind.EVALUATION_ERROR for event in evaluated.evidence.events
    )
    model.assert_complete()
