from __future__ import annotations

import asyncio
from typing import cast

import pytest

import agent_evals.runtime._evaluator_core as evaluator_core
from agent_evals.adapters.base import AgentAdapter
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime._evaluator_core import EvaluatedTrial, TrialRunner
from agent_evals.semantic.receipt import SemanticJudgmentReceipt


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="mutation-wrapper",
        instructions="Exercise the evaluator wrapper only.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="scripted",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="mutation.evaluator-wrapper",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Preserve exact TrialRunner.run forwarding and timing semantics.",
        authority=AuthorityPolicy(),
    )


def _adapter() -> AgentAdapter:
    return ScriptedAdapter(lambda *_: pytest.fail("wrapper test must not execute the adapter"))


def _inner_result(subject: SubjectFingerprint, scenario: EvaluationScenario) -> EvaluatedTrial:
    evidence = TrialEvidence(
        trial_id="inner-trial",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
    )
    oracle = OracleResult(
        name="wrapper-probe",
        verdict=TrialVerdict.FAIL,
        reasons=("probe",),
        critical=True,
    )
    semantic = cast(SemanticJudgmentReceipt, object())
    return EvaluatedTrial(
        evidence=evidence,
        oracle_results=(oracle,),
        verdict=TrialVerdict.FAIL,
        semantic_judgment=semantic,
        evaluator_elapsed_ms=7.0,
    )


def test_run_forwards_exact_inputs_and_rewraps_exact_inner_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    adapter = _adapter()
    inner = _inner_result(subject, scenario)
    observed: list[tuple[AgentAdapter, SubjectFingerprint, EvaluationScenario, str, float]] = []

    async def fake_run_trial(
        self: TrialRunner,
        adapter_arg: AgentAdapter,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        started: float,
    ) -> EvaluatedTrial:
        assert isinstance(self, TrialRunner)
        observed.append((adapter_arg, subject, scenario, trial_id, started))
        return inner

    times = iter((10.0, 10.25))
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: next(times))
    monkeypatch.setattr(TrialRunner, "_run_trial", fake_run_trial)

    result = asyncio.run(
        TrialRunner().run(
            adapter,
            subject=subject,
            scenario=scenario,
            trial_id="outer-trial",
        )
    )

    assert observed == [(adapter, subject, scenario, "outer-trial", 10.0)]
    assert result.evidence is inner.evidence
    assert result.oracle_results is inner.oracle_results
    assert result.verdict is inner.verdict
    assert result.semantic_judgment is inner.semantic_judgment
    assert result.evaluator_elapsed_ms == 250.0
    assert result.completion_evidence_root == inner.evidence.evidence_root


def test_run_clamps_negative_observed_elapsed_time_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    scenario = _scenario()
    inner = _inner_result(subject, scenario)

    async def fake_run_trial(
        self: TrialRunner,
        adapter_arg: AgentAdapter,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        started: float,
    ) -> EvaluatedTrial:
        assert isinstance(self, TrialRunner)
        assert isinstance(adapter_arg, AgentAdapter)
        assert subject.identity == inner.evidence.subject_identity
        assert scenario.identity == inner.evidence.scenario_identity
        assert trial_id == "negative-clock"
        assert started == 20.0
        return inner

    times = iter((20.0, 19.0))
    monkeypatch.setattr(evaluator_core, "perf_counter", lambda: next(times))
    monkeypatch.setattr(TrialRunner, "_run_trial", fake_run_trial)

    result = asyncio.run(
        TrialRunner().run(
            _adapter(),
            subject=subject,
            scenario=scenario,
            trial_id="negative-clock",
        )
    )

    assert result.evaluator_elapsed_ms == 0.0
