from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.assurance.report import AssuranceReport, OracleSnapshot
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.gates.release import GateDecision, ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def _report() -> AssuranceReport:
    evidence = TrialEvidence(
        trial_id="trial-0",
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
    )
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=(
            OracleResult(
                name="policy",
                verdict=TrialVerdict.FAIL,
                critical=True,
            ),
        ),
        verdict=TrialVerdict.FAIL,
    )
    reliability = ReliabilityReport.from_verdicts((TrialVerdict.FAIL,), k=1)
    session = EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        trials=(trial,),
        reliability=reliability,
    )
    policy = ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
    )
    return AssuranceReport.from_session(session, release_policy=policy)


@pytest.mark.parametrize("invalid", ["true", "false", 1, 0])
def test_oracle_snapshot_rejects_coercible_criticality_surrogates(invalid: object) -> None:
    data = {
        "name": "policy",
        "verdict": TrialVerdict.FAIL,
        "critical": invalid,
    }

    with pytest.raises(ValidationError):
        OracleSnapshot.model_validate(data)


def test_oracle_snapshot_accepts_actual_booleans() -> None:
    assert (
        OracleSnapshot(
            name="policy",
            verdict=TrialVerdict.FAIL,
            critical=True,
        ).critical
        is True
    )
    assert (
        OracleSnapshot(
            name="outcome",
            verdict=TrialVerdict.PASS,
            critical=False,
        ).critical
        is False
    )


def test_report_preserves_critical_violation_gate_semantics() -> None:
    report = _report()

    assert report.trials[0].oracle_results[0].critical is True
    assert report.critical_violations == 1
    assert report.gate.decision is GateDecision.REJECT


def test_report_rejects_root_preserving_oracle_criticality_json_type_drift() -> None:
    report = _report()
    payload = report.model_dump(mode="json")
    original_root = payload["report_root"]
    payload["trials"][0]["oracle_results"][0]["critical"] = "true"

    assert payload["report_root"] == original_root
    with pytest.raises(ValidationError):
        AssuranceReport.model_validate(payload)


def test_valid_oracle_criticality_report_json_round_trip_remains_supported() -> None:
    report = _report()

    assert AssuranceReport.model_validate_json(report.model_dump_json()) == report
