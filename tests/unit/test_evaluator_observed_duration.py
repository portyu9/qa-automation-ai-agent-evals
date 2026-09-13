from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.runtime.evaluator import EvaluatedTrial, TrialRunner
from agent_evals.runtime.session import EvaluationSession


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="timing-test",
        model="subject-model",
        application_revision="rev-1",
        instructions="Complete the task.",
        tool_schema={"tools": []},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="timing-test",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="runtime.evaluator-timing",
        revision="1",
        kind=ScenarioKind.CAPABILITY,
        objective="Complete the test task.",
        authority=AuthorityPolicy(),
        required_outcomes={"status": "ok"},
    )


@dataclass(slots=True)
class _StaticAdapter:
    elapsed_ms: float = 1_000_000.0

    @property
    def name(self) -> str:
        return "timing-test"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        return AdapterResult(
            final_state={"status": "ok"},
            final_output="done",
            elapsed_ms=self.elapsed_ms,
        )


class _BlockingAdapter:
    @property
    def name(self) -> str:
        return "timing-blocking"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def _manual_evidence() -> TrialEvidence:
    return TrialEvidence(
        trial_id="manual",
        subject_identity="a" * 64,
        scenario_identity="b" * 64,
        final_state={"status": "ok"},
    )


def test_manual_evaluated_trial_remains_compatible_without_runtime_measurement() -> None:
    trial = EvaluatedTrial(
        evidence=_manual_evidence(),
        oracle_results=(),
        verdict=TrialVerdict.PASS,
    )

    assert trial.evaluator_elapsed_ms is None
    assert trial.completion_evidence_root == trial.evidence.evidence_root


@pytest.mark.parametrize(
    "value",
    [True, False, "1", -1, float("inf"), float("-inf"), float("nan")],
)
def test_evaluator_elapsed_validation_rejects_invalid_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        EvaluatedTrial(
            evidence=_manual_evidence(),
            oracle_results=(),
            verdict=TrialVerdict.PASS,
            evaluator_elapsed_ms=value,  # type: ignore[arg-type]
        )


def test_evaluator_elapsed_validation_normalizes_numeric_values() -> None:
    trial = EvaluatedTrial(
        evidence=_manual_evidence(),
        oracle_results=(),
        verdict=TrialVerdict.PASS,
        evaluator_elapsed_ms=7,
    )

    assert trial.evaluator_elapsed_ms == 7.0
    assert isinstance(trial.evaluator_elapsed_ms, float)


@pytest.mark.asyncio
async def test_trial_runner_measures_evaluator_time_separately_from_adapter_telemetry() -> None:
    result = await TrialRunner().run(
        _StaticAdapter(),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="live-timing",
    )

    assert result.verdict is TrialVerdict.PASS
    assert result.evidence.elapsed_ms == 1_000_000.0
    assert result.evaluator_elapsed_ms is not None
    assert 0.0 <= result.evaluator_elapsed_ms < result.evidence.elapsed_ms


@pytest.mark.asyncio
async def test_replay_preserves_historical_elapsed_and_measures_live_replay_duration() -> None:
    subject = _subject()
    scenario = _scenario()
    trial_id = "replay-timing"
    recorded = TrialEvidence(
        trial_id=trial_id,
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        final_state={"status": "ok"},
        final_output="recorded",
        elapsed_ms=60_000.0,
    )

    result = await TrialRunner(deadline_seconds=1.0).run(
        EvidenceReplayAdapter(recorded),
        subject=subject,
        scenario=scenario,
        trial_id=trial_id,
    )

    assert result.verdict is TrialVerdict.PASS
    assert result.evidence.elapsed_ms == 60_000.0
    assert result.evaluator_elapsed_ms is not None
    assert 0.0 <= result.evaluator_elapsed_ms < result.evidence.elapsed_ms


@pytest.mark.asyncio
async def test_deadline_result_carries_separate_evaluator_runtime_measurement() -> None:
    result = await TrialRunner(deadline_seconds=0.01).run(
        _BlockingAdapter(),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="deadline-timing",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.evidence.events[-1].kind is EvidenceKind.EVALUATION_ERROR
    assert result.evidence.events[-1].source == "evaluator:deadline"
    assert result.evaluator_elapsed_ms is not None
    assert result.evidence.elapsed_ms > 0.0
    assert result.evaluator_elapsed_ms >= result.evidence.elapsed_ms


@pytest.mark.asyncio
async def test_evaluation_session_retains_per_trial_evaluator_measurements() -> None:
    result = await EvaluationSession(runner=TrialRunner()).run(
        _StaticAdapter(elapsed_ms=123_456.0),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="evaluator-timing-session",
    )

    assert len(result.trials) == 2
    assert all(trial.verdict is TrialVerdict.PASS for trial in result.trials)
    assert all(trial.evidence.elapsed_ms == 123_456.0 for trial in result.trials)
    assert all(trial.evaluator_elapsed_ms is not None for trial in result.trials)
