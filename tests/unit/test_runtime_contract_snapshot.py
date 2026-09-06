from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import TrialVerdict
from agent_evals.runtime.evaluator import EvaluatedTrial, TrialRunner
from agent_evals.runtime.session import EvaluationSession


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="snapshot-test",
        model="subject-model",
        application_revision="rev-1",
        instructions="Return the requested status.",
        tool_schema={"tools": []},
        policy={"allowed": []},
        memory_policy={"retention": "trial"},
        adapter="snapshot-test",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="runtime.snapshot",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Preserve one exact scenario contract for the full trial.",
        initial_state={"nested": {"items": ["baseline"]}},
        required_outcomes={"status": "ok"},
    )


def _error_code(result: EvaluatedTrial) -> object:
    assert len(result.evidence.events) == 1
    return result.evidence.events[0].payload.get("code")


@dataclass(slots=True)
class _TopLevelMutatingAdapter:
    @property
    def name(self) -> str:
        return "top-level-mutator"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, trial_id
        scenario.required_outcomes["status"] = "mutated"
        return AdapterResult(final_state={"status": "ok"})


@dataclass(slots=True)
class _NestedMutatingAdapter:
    @property
    def name(self) -> str:
        return "nested-mutator"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, trial_id
        nested = scenario.initial_state["nested"]
        assert isinstance(nested, dict)
        items = nested["items"]
        assert isinstance(items, list)
        items.append("mutated")
        return AdapterResult(final_state={"status": "ok"})


@dataclass(slots=True)
class _MutatingFailureAdapter:
    @property
    def name(self) -> str:
        return "mutating-failure"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, trial_id
        scenario.forbidden_outcomes["status"] = "ok"
        raise RuntimeError("controlled adapter failure after mutation")


@dataclass(slots=True)
class _BlockingAdapter:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def name(self) -> str:
        return "blocking"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        self.started.set()
        await self.release.wait()
        return AdapterResult(final_state={"status": "ok"})


@dataclass(slots=True)
class _ExternalCallerMutatingAdapter:
    caller_scenario: EvaluationScenario
    calls: int = 0

    @property
    def name(self) -> str:
        return "external-caller-mutator"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        self.calls += 1
        if self.calls == 1:
            self.caller_scenario.required_outcomes["status"] = "caller-mutated"
        return AdapterResult(final_state={"status": "ok"})


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [_TopLevelMutatingAdapter(), _NestedMutatingAdapter()])
async def test_adapter_scenario_mutation_is_blocked_without_changing_evaluator_contract(
    adapter: _TopLevelMutatingAdapter | _NestedMutatingAdapter,
) -> None:
    scenario = _scenario()
    expected_identity = scenario.identity

    result = await TrialRunner().run(
        adapter,
        subject=_subject(),
        scenario=scenario,
        trial_id="adapter-mutation",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert _error_code(result) == "scenario_contract_mutated"
    assert result.evidence.scenario_identity == expected_identity
    assert scenario.identity == expected_identity


@pytest.mark.asyncio
async def test_adapter_mutation_takes_precedence_over_following_runtime_exception() -> None:
    scenario = _scenario()
    expected_identity = scenario.identity

    result = await TrialRunner().run(
        _MutatingFailureAdapter(),
        subject=_subject(),
        scenario=scenario,
        trial_id="mutation-before-error",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert _error_code(result) == "scenario_contract_mutated"
    assert result.evidence.scenario_identity == expected_identity


@pytest.mark.asyncio
async def test_caller_mutation_during_await_cannot_change_in_flight_trial_contract() -> None:
    scenario = _scenario()
    expected_identity = scenario.identity
    adapter = _BlockingAdapter()

    task = asyncio.create_task(
        TrialRunner().run(
            adapter,
            subject=_subject(),
            scenario=scenario,
            trial_id="caller-mutation",
        )
    )
    await adapter.started.wait()
    scenario.required_outcomes["status"] = "caller-mutated"
    adapter.release.set()
    result = await task

    assert scenario.identity != expected_identity
    assert result.verdict is TrialVerdict.PASS
    assert result.evidence.scenario_identity == expected_identity


@pytest.mark.asyncio
async def test_session_reuses_one_snapshot_when_caller_contract_changes_between_trials() -> None:
    scenario = _scenario()
    expected_identity = scenario.identity
    adapter = _ExternalCallerMutatingAdapter(caller_scenario=scenario)

    result = await EvaluationSession().run(
        adapter,
        subject=_subject(),
        scenario=scenario,
        trials=2,
    )

    assert scenario.identity != expected_identity
    assert result.scenario_identity == expected_identity
    assert tuple(trial.evidence.scenario_identity for trial in result.trials) == (
        expected_identity,
        expected_identity,
    )
    assert tuple(trial.verdict for trial in result.trials) == (
        TrialVerdict.PASS,
        TrialVerdict.PASS,
    )
