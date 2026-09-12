from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.assurance.report import AssuranceReport, OracleSnapshot
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import GateDecision, ReleasePolicy
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.runtime.sampling import (
    RandomnessStatus,
    SamplingPolicy,
    SessionSamplingMetadata,
    StoppingRule,
)
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

SUBJECT = "a" * 64
_CAMPAIGN_ID = "assurance-criticality"
_RUNTIME_ADAPTER = "fixture-runtime"
_SUBJECT_ADAPTER = "fixture-subject"
_SUBJECT_ADAPTER_VERSION = "1"
SCENARIO_CONTRACT = EvaluationScenario(
    scenario_id="assurance.criticality",
    revision="1",
    kind=ScenarioKind.REGRESSION,
    objective="Verify deterministic oracle criticality integrity.",
)
SCENARIO = SCENARIO_CONTRACT.identity


def _report() -> AssuranceReport:
    request = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.TOOL_REQUEST,
        source="adapter:test",
        payload={"tool": "forbidden-tool", "call_id": "call-1", "arguments": "{}"},
    )
    evidence = TrialEvidence(
        trial_id=f"campaign:{_CAMPAIGN_ID}:attempt:0000",
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        events=(request,),
    )
    oracle_results = grade_deterministic_evidence(SCENARIO_CONTRACT, evidence)
    assert oracle_results[0].verdict is TrialVerdict.FAIL
    assert oracle_results[0].critical is True
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=oracle_results,
        verdict=TrialVerdict.FAIL,
    )
    reliability = ReliabilityReport.from_verdicts((TrialVerdict.FAIL,), k=1)
    session = EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        trials=(trial,),
        reliability=reliability,
        campaign_id=_CAMPAIGN_ID,
        runtime_adapter_name=_RUNTIME_ADAPTER,
        subject_adapter=_SUBJECT_ADAPTER,
        subject_adapter_version=_SUBJECT_ADAPTER_VERSION,
        sampling_metadata=SessionSamplingMetadata(
            sampling_policy=SamplingPolicy.PREDECLARED_ALL_ATTEMPTS,
            randomness_status=RandomnessStatus.UNKNOWN,
            stopping_rule=StoppingRule.FIXED_HORIZON,
            planned_trials=1,
        ),
    )
    policy = ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
    )
    return AssuranceReport.from_session(
        session,
        scenario=SCENARIO_CONTRACT,
        release_policy=policy,
    )


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
