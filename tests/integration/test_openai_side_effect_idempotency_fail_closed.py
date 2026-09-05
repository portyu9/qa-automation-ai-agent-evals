from __future__ import annotations

from typing import Any

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


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="openai.side-effect-fail-closed",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Apply the exact logical operation twice.",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"apply_change"}),
            max_turns=8,
            max_tool_calls=3,
        ),
        side_effect_idempotency=SideEffectIdempotencySpec(
            tool="apply_change",
            key_argument="operation_id",
            expected_arguments={"operation_id": "op-7", "value": 3},
        ),
    )


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="openai",
        model="scripted",
        application_revision="side-effect-fail-closed-1",
        instructions="Exercise one duplicate logical operation.",
        tool_schema={"apply_change": {"operation_id": "string", "value": "integer"}},
        policy={"allowed": ["apply_change"]},
        memory_policy={"retention": "none"},
        adapter="openai-agents-side-effect-idempotency",
        adapter_version="0.22.0",
    )


def _scripted_model(calls: list[tuple[str, dict[str, Any]]]) -> object:
    from agents.testing import ScriptedModel, assistant_message, function_call

    steps: list[list[object]] = [
        [function_call("apply_change", arguments, call_id=call_id)] for call_id, arguments in calls
    ]
    steps.append([assistant_message("Done.")])
    return ScriptedModel(steps)


async def _run(
    calls: list[tuple[str, dict[str, Any]]],
    *,
    effect_reader_mode: str = "normal",
    require_model_complete: bool = True,
) -> tuple[object, int, list[dict[str, Any]]]:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.decorators import tool

    callback_calls = 0
    effects: list[dict[str, Any]] = []

    @tool
    def apply_change(operation_id: str, value: int) -> str:
        """Apply one controlled logical change."""
        nonlocal callback_calls
        callback_calls += 1
        if not effects:
            effects.append({"operation_id": operation_id, "value": value})
            return "created"
        return "duplicate"

    def effect_reader() -> object:
        if effect_reader_mode == "unsupported":
            return object()
        if effect_reader_mode == "non_finite":
            return {"count": float("nan")}
        return {"effects": [dict(effect) for effect in effects]}

    model = _scripted_model(calls)
    evaluated = await TrialRunner().run(
        OpenAIAgentsSideEffectIdempotencyAdapter(
            Agent(name="Side-effect fail-closed agent", model=model, tools=[apply_change]),
            state_reader=lambda: {"callback_calls": callback_calls},
            effect_reader=effect_reader,
        ),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="side-effect-fail-closed",
    )
    if require_model_complete:
        model.assert_complete()  # type: ignore[attr-defined]
    return evaluated, callback_calls, effects


@pytest.mark.openai
@pytest.mark.asyncio
async def test_three_target_calls_block_after_all_subject_callbacks_execute() -> None:
    evaluated, callback_calls, _ = await _run(
        [
            ("call-1", {"operation_id": "op-7", "value": 3}),
            ("call-2", {"operation_id": "op-7", "value": 3}),
            ("call-3", {"operation_id": "op-7", "value": 3}),
        ]
    )

    assert callback_calls == 3
    assert evaluated.verdict is TrialVerdict.BLOCKED  # type: ignore[attr-defined]
    event = evaluated.evidence.events[-1]  # type: ignore[attr-defined]
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.payload["code"] == "side_effect_call_ambiguous"


@pytest.mark.openai
@pytest.mark.asyncio
async def test_missing_sdk_call_identity_blocks_before_subject_callback_execution() -> None:
    evaluated, callback_calls, _ = await _run(
        [
            ("", {"operation_id": "op-7", "value": 3}),
            ("call-2", {"operation_id": "op-7", "value": 3}),
        ],
        require_model_complete=False,
    )

    assert callback_calls == 0
    assert evaluated.verdict is TrialVerdict.BLOCKED  # type: ignore[attr-defined]
    event = evaluated.evidence.events[-1]  # type: ignore[attr-defined]
    assert event.kind is EvidenceKind.RUNTIME_ERROR
    assert event.payload["detail_retained"] is False


@pytest.mark.openai
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second_arguments",
    [
        {"operation_id": "op-7", "value": 4},
        {"operation_id": "op-8", "value": 3},
    ],
)
async def test_changed_duplicate_operation_blocks_without_suppressing_second_callback(
    second_arguments: dict[str, Any],
) -> None:
    evaluated, callback_calls, _ = await _run(
        [
            ("call-1", {"operation_id": "op-7", "value": 3}),
            ("call-2", second_arguments),
        ]
    )

    assert callback_calls == 2
    assert evaluated.verdict is TrialVerdict.BLOCKED  # type: ignore[attr-defined]
    event = evaluated.evidence.events[-1]  # type: ignore[attr-defined]
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.payload["code"] == "side_effect_observation_unavailable"


@pytest.mark.openai
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unsupported", "non_finite"])
async def test_non_json_or_non_finite_effect_projection_blocks_after_both_callbacks(
    mode: str,
) -> None:
    evaluated, callback_calls, _ = await _run(
        [
            ("call-1", {"operation_id": "op-7", "value": 3}),
            ("call-2", {"operation_id": "op-7", "value": 3}),
        ],
        effect_reader_mode=mode,
    )

    assert callback_calls == 2
    assert evaluated.verdict is TrialVerdict.BLOCKED  # type: ignore[attr-defined]
    event = evaluated.evidence.events[-1]  # type: ignore[attr-defined]
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.payload["code"] == "side_effect_observation_unavailable"
