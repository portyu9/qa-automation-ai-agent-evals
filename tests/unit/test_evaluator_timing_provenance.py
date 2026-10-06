from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.runtime.evaluator import EvaluatedTrial, TrialRunner
from agent_evals.runtime.timing_provenance import EvaluatorTimingProvenance


def _evidence() -> TrialEvidence:
    return TrialEvidence(
        trial_id="trial-1",
        subject_identity="1" * 64,
        scenario_identity="2" * 64,
    )


def test_timing_provenance_binds_monotonic_clock_elapsed_and_evidence() -> None:
    evidence = _evidence()
    timing = EvaluatorTimingProvenance.create(evidence, elapsed_ms=12.5)

    assert timing.clock_source == "time.perf_counter"
    assert timing.monotonic is True
    assert timing.includes_metric_provenance_resolution is True
    assert timing.elapsed_ms == 12.5
    timing.validate_against_evidence(evidence)

    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=(),
        verdict=TrialVerdict.BLOCKED,
        evaluator_elapsed_ms=12.5,
        timing_provenance=timing,
    )
    assert trial.timing_provenance == timing


def test_timing_provenance_rejects_root_and_elapsed_drift() -> None:
    evidence = _evidence()
    timing = EvaluatorTimingProvenance.create(evidence, elapsed_ms=1.0)

    payload = json.loads(timing.model_dump_json())
    payload["clock_source"] = "time.time"
    with pytest.raises(ValidationError):
        EvaluatorTimingProvenance.model_validate(payload)

    with pytest.raises(ValueError, match="elapsed_ms does not match"):
        EvaluatedTrial(
            evidence=evidence,
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
            evaluator_elapsed_ms=2.0,
            timing_provenance=timing,
        )



@pytest.mark.asyncio
async def test_public_trial_runner_attaches_monotonic_timing_provenance() -> None:
    subject = SubjectFingerprint.from_material(
        provider="fixture",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="scripted",
        adapter_version="1",
    )
    scenario = EvaluationScenario(
        scenario_id="timing.provenance",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Bind evaluator timing metadata",
    )
    result = await TrialRunner().run(
        ScriptedAdapter(lambda _subject, _scenario, _trial: AdapterResult()),
        subject=subject,
        scenario=scenario,
        trial_id="timed-trial",
    )

    assert result.timing_provenance is not None
    assert result.evaluator_elapsed_ms is not None
    assert result.timing_provenance.elapsed_ms == result.evaluator_elapsed_ms
    assert result.timing_provenance.clock_source == "time.perf_counter"
    result.timing_provenance.validate_against_evidence(result.evidence)
