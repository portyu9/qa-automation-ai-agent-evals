from __future__ import annotations

from collections.abc import Callable

import pytest

from agent_evals.adapters.openai_side_effect_idempotency import (
    OpenAIAgentsSideEffectIdempotencyAdapter,
)
from agent_evals.adapters.replay import EvidenceReplayAdapter
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
        scenario_id="openai.side-effect-idempotency",
        revision="1",
        kind=ScenarioKind.RESILIENCE,
        objective="Apply operation op-7 twice as a duplicate attempt without duplicating its effect.",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({"apply_change"}),
            max_turns=6,
            max_tool_calls=2,
        ),
        side_effect_idempotency=SideEffectIdempotencySpec(
            tool="apply_change",
            key_argument="operation_id",
            expected_arguments={"operation_id": "op-7", "value": 3},
        ),
        required_outcomes={"callback_calls": 2},
    )


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="openai",
        model="scripted",
        application_revision="side-effect-1",
        instructions="Apply the same logical operation twice when instructed.",
        tool_schema={
            "apply_change": {
                "operation_id": "string",
                "value": "integer",
            }
        },
        policy={"allowed": ["apply_change"]},
        memory_policy={"retention": "none"},
        adapter="openai-agents-side-effect-idempotency",
        adapter_version="0.22.0",
    )


def _model() -> object:
    from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

    def issue_duplicate(call: object) -> dict[str, object]:
        outputs = [
            item
            for item in call.input  # type: ignore[attr-defined]
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert outputs[-1]["call_id"] == "effect_1"
        assert outputs[-1]["output"] == "created"
        return {
            "output": [
                function_call(
                    "apply_change",
                    {"operation_id": "op-7", "value": 3},
                    call_id="effect_2",
                )
            ]
        }

    def finish(call: object) -> dict[str, object]:
        outputs = [
            item
            for item in call.input  # type: ignore[attr-defined]
            if isinstance(item, dict) and item.get("type") == "function_call_output"
        ]
        assert [item["call_id"] for item in outputs] == ["effect_1", "effect_2"]
        assert outputs[-1]["output"] in {"duplicate", "created"}
        return {"output": [assistant_message("Duplicate attempt complete.")]}

    return ScriptedModel(
        [
            [
                function_call(
                    "apply_change",
                    {"operation_id": "op-7", "value": 3},
                    call_id="effect_1",
                )
            ],
            ModelStep.respond(issue_duplicate),
            ModelStep.respond(finish),
        ]
    )


async def _run_subject(*, idempotent: bool) -> tuple[object, dict[str, object]]:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.decorators import tool

    effects: list[dict[str, object]] = []
    seen: set[str] = set()
    counters = {"callback_calls": 0, "effect_reader_calls": 0}

    @tool
    def apply_change(operation_id: str, value: int) -> str:
        """Apply one controlled logical change."""
        counters["callback_calls"] += 1
        if idempotent and operation_id in seen:
            return "duplicate"
        effects.append({"operation_id": operation_id, "value": value})
        seen.add(operation_id)
        return "created"

    def effect_reader() -> object:
        counters["effect_reader_calls"] += 1
        return {"effects": [dict(item) for item in effects]}

    def state_reader() -> dict[str, object]:
        return {
            "callback_calls": counters["callback_calls"],
            "effect_count": len(effects),
        }

    model = _model()
    evaluated = await TrialRunner().run(
        OpenAIAgentsSideEffectIdempotencyAdapter(
            Agent(name="Side-effect agent", model=model, tools=[apply_change]),
            state_reader=state_reader,
            effect_reader=effect_reader,
        ),
        subject=_subject(),
        scenario=_scenario(),
        trial_id=("side-effect-idempotent" if idempotent else "side-effect-duplicate-mutation"),
    )
    model.assert_complete()  # type: ignore[attr-defined]
    return evaluated, {
        "callbacks": counters["callback_calls"],
        "effect_reads": counters["effect_reader_calls"],
        "effects": effects,
    }


@pytest.mark.openai
@pytest.mark.asyncio
async def test_openai_side_effect_bridge_observes_two_callbacks_but_only_one_mutation() -> None:
    evaluated, observed = await _run_subject(idempotent=True)

    assert evaluated.verdict is TrialVerdict.PASS  # type: ignore[attr-defined]
    assert observed["callbacks"] == 2
    assert observed["effect_reads"] == 4
    assert len(observed["effects"]) == 1  # type: ignore[arg-type]

    events = evaluated.evidence.events  # type: ignore[attr-defined]
    target = [
        event
        for event in events
        if event.kind in {
            EvidenceKind.TOOL_REQUEST,
            EvidenceKind.TOOL_RESULT,
            EvidenceKind.SIDE_EFFECT_OBSERVATION,
        }
    ]
    assert [event.kind for event in target] == [
        EvidenceKind.TOOL_REQUEST,
        EvidenceKind.TOOL_RESULT,
        EvidenceKind.TOOL_REQUEST,
        EvidenceKind.TOOL_RESULT,
        EvidenceKind.SIDE_EFFECT_OBSERVATION,
    ]
    receipt = target[-1].payload
    assert receipt["mutation_count"] == 1
    assert receipt["attempts"][0]["mutated"] is True
    assert receipt["attempts"][1]["mutated"] is False
    assert [attempt["call_id"] for attempt in receipt["attempts"]] == ["effect_1", "effect_2"]


@pytest.mark.openai
@pytest.mark.asyncio
async def test_openai_side_effect_bridge_marks_second_physical_mutation_as_critical_fail() -> None:
    evaluated, observed = await _run_subject(idempotent=False)

    assert evaluated.verdict is TrialVerdict.FAIL  # type: ignore[attr-defined]
    assert observed["callbacks"] == 2
    assert len(observed["effects"]) == 2  # type: ignore[arg-type]
    side_effect = next(
        result
        for result in evaluated.oracle_results  # type: ignore[attr-defined]
        if result.name == "side-effect-idempotency"
    )
    assert side_effect.verdict is TrialVerdict.FAIL
    assert side_effect.critical is True
    assert any("second observable physical effect" in reason for reason in side_effect.reasons)
    receipt = next(
        event
        for event in evaluated.evidence.events  # type: ignore[attr-defined]
        if event.kind is EvidenceKind.SIDE_EFFECT_OBSERVATION
    )
    assert receipt.payload["mutation_count"] == 2


@pytest.mark.openai
@pytest.mark.asyncio
async def test_side_effect_replay_regrades_without_rerunning_callback_or_effect_reader() -> None:
    evaluated, observed = await _run_subject(idempotent=True)
    callbacks_before = observed["callbacks"]
    reads_before = observed["effect_reads"]

    replayed = await TrialRunner().run(
        EvidenceReplayAdapter(evaluated.evidence),  # type: ignore[attr-defined]
        subject=_subject(),
        scenario=_scenario(),
        trial_id="side-effect-idempotent",
    )

    assert replayed.verdict is TrialVerdict.PASS
    assert observed["callbacks"] == callbacks_before
    assert observed["effect_reads"] == reads_before
    assert replayed.evidence.evidence_root == evaluated.evidence.evidence_root  # type: ignore[attr-defined]


@pytest.mark.openai
@pytest.mark.asyncio
async def test_openai_side_effect_bridge_blocks_when_model_makes_only_one_target_call() -> None:
    pytest.importorskip("agents")
    from agents import Agent
    from agents.decorators import tool
    from agents.testing import ScriptedModel, assistant_message, function_call

    effects: list[str] = []

    @tool
    def apply_change(operation_id: str, value: int) -> str:
        """Apply one controlled logical change."""
        effects.append(f"{operation_id}:{value}")
        return "created"

    model = ScriptedModel(
        [
            [
                function_call(
                    "apply_change",
                    {"operation_id": "op-7", "value": 3},
                    call_id="effect_1",
                )
            ],
            [assistant_message("Done.")],
        ]
    )
    evaluated = await TrialRunner().run(
        OpenAIAgentsSideEffectIdempotencyAdapter(
            Agent(name="One-call agent", model=model, tools=[apply_change]),
            state_reader=lambda: {"callback_calls": 1},
            effect_reader=lambda: {"effects": list(effects)},
        ),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="side-effect-one-call",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[-1].kind is EvidenceKind.EVALUATION_ERROR
    assert evaluated.evidence.events[-1].payload["code"] in {
        "side_effect_call_missing",
        "side_effect_call_ambiguous",
    }
    model.assert_complete()


@pytest.mark.openai
@pytest.mark.asyncio
async def test_openai_side_effect_bridge_blocks_effect_reader_failure_without_suppressing_callbacks() -> (
    None
):
    pytest.importorskip("agents")
    from agents import Agent
    from agents.decorators import tool

    callback_calls = 0

    @tool
    def apply_change(operation_id: str, value: int) -> str:
        """Apply one controlled logical change."""
        nonlocal callback_calls
        callback_calls += 1
        return "created" if callback_calls == 1 else "duplicate"

    def broken_effect_reader() -> object:
        raise RuntimeError("observer unavailable")

    evaluated = await TrialRunner().run(
        OpenAIAgentsSideEffectIdempotencyAdapter(
            Agent(name="Broken observer agent", model=_model(), tools=[apply_change]),
            state_reader=lambda: {"callback_calls": callback_calls},
            effect_reader=broken_effect_reader,
        ),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="side-effect-observer-failure",
    )

    assert callback_calls == 2
    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[-1].payload["code"] == "side_effect_observation_unavailable"
