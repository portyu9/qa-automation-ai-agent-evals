from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agent_evals.evidence.models import TrialEvidence
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.timing_provenance import EvaluatorTimingProvenance
from agent_evals.evidence.models import TrialVerdict


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
