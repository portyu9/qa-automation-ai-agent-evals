from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from agent_evals.assurance.report import AssuranceReport
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.gates.release import GateDecision, ReleaseGate, ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.comparison import PairedComparison
from agent_evals.statistics.reliability import ReliabilityReport

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def _pass_trial() -> EvaluatedTrial:
    return EvaluatedTrial(
        evidence=TrialEvidence(
            trial_id="statistical-integrity-trial",
            subject_identity=SUBJECT,
            scenario_identity=SCENARIO,
            final_state={"ok": True},
        ),
        oracle_results=(
            OracleResult(name="policy", verdict=TrialVerdict.PASS),
            OracleResult(name="outcome", verdict=TrialVerdict.PASS, critical=False),
        ),
        verdict=TrialVerdict.PASS,
    )


def _session(*, confidence_z: float) -> EvaluationSessionResult:
    trial = _pass_trial()
    return EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts(
            (trial.verdict,),
            k=2,
            confidence_z=confidence_z,
        ),
    )


def _release_policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=0,
        max_inconclusive_trials=0,
    )


def test_reliability_rejects_non_enum_runtime_verdicts() -> None:
    with pytest.raises(ValueError, match="exact TrialVerdict members"):
        ReliabilityReport.from_verdicts(
            [TrialVerdict.PASS, "fail"],  # type: ignore[list-item]
        )


def test_reliability_rejects_boolean_and_noninteger_k() -> None:
    for invalid in (True, 1.5):
        with pytest.raises(ValueError, match="k must be an integer >= 1"):
            ReliabilityReport.from_verdicts(
                [TrialVerdict.PASS],
                k=invalid,  # type: ignore[arg-type]
            )


def test_reliability_rejects_nonfloat_confidence_contract() -> None:
    for invalid in (True, 2):
        with pytest.raises(ValueError, match="confidence_z must be finite and positive"):
            ReliabilityReport.from_verdicts(
                [TrialVerdict.PASS],
                confidence_z=invalid,  # type: ignore[arg-type]
            )


def test_direct_reliability_construction_rejects_count_drift() -> None:
    report = ReliabilityReport.from_verdicts(
        [TrialVerdict.PASS, TrialVerdict.FAIL, TrialVerdict.BLOCKED],
        k=2,
    )

    with pytest.raises(ValueError, match=r"resolved_trials must equal passes \+ failures"):
        replace(report, failures=0)


def test_direct_reliability_construction_rejects_derived_metric_drift() -> None:
    report = ReliabilityReport.from_verdicts(
        [TrialVerdict.PASS, TrialVerdict.FAIL],
        k=2,
    )

    with pytest.raises(ValueError, match="success_rate does not recompute"):
        replace(report, success_rate=0.75)


def test_direct_reliability_construction_rejects_scalar_type_drift() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS])

    with pytest.raises(ValueError, match="trials must be an integer"):
        replace(report, trials=1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="wilson_low must be a finite float"):
        replace(report, wilson_low=True)  # type: ignore[arg-type]


def test_release_gate_revalidates_tampered_reliability_object() -> None:
    report = ReliabilityReport.from_verdicts(
        [TrialVerdict.PASS, TrialVerdict.FAIL],
    )
    object.__setattr__(report, "success_rate", 1.0)

    gate = ReleaseGate(_release_policy())
    with pytest.raises(ValueError, match="success_rate does not recompute"):
        gate.decide(report, critical_violations=0)


def test_release_gate_rejects_non_report_runtime_object() -> None:
    gate = ReleaseGate(_release_policy())
    with pytest.raises(ValueError, match="exact ReliabilityReport"):
        gate.decide(object(), critical_violations=0)  # type: ignore[arg-type]


def test_paired_comparison_rejects_non_enum_runtime_verdicts() -> None:
    with pytest.raises(ValueError, match="exact TrialVerdict members"):
        PairedComparison.compare(
            [TrialVerdict.PASS],
            ["fail"],  # type: ignore[list-item]
        )


def test_paired_comparison_rejects_nonfloat_alpha() -> None:
    with pytest.raises(ValueError, match="alpha must be a finite float"):
        PairedComparison.compare(
            [TrialVerdict.PASS],
            [TrialVerdict.PASS],
            alpha=True,  # type: ignore[arg-type]
        )


def test_custom_confidence_round_trips_through_assurance_report_v3() -> None:
    custom_z = 1.6448536269514722
    session = _session(confidence_z=custom_z)

    report = AssuranceReport.from_session(session, release_policy=_release_policy())
    loaded = AssuranceReport.model_validate_json(report.model_dump_json())

    assert report.schema_version == "agent-evals/assurance-report/v3"
    assert report.reliability.confidence_z == custom_z
    assert loaded == report
    assert loaded.reliability.wilson_low == session.reliability.wilson_low
    assert loaded.reliability.wilson_high == session.reliability.wilson_high


def test_confidence_parameter_participates_in_assurance_report_root() -> None:
    default = AssuranceReport.from_session(
        _session(confidence_z=1.959963984540054),
        release_policy=_release_policy(),
    )
    custom = AssuranceReport.from_session(
        _session(confidence_z=1.6448536269514722),
        release_policy=_release_policy(),
    )

    assert default.reliability.success_rate == custom.reliability.success_rate
    assert default.reliability.confidence_z != custom.reliability.confidence_z
    assert default.report_root != custom.report_root


def test_assurance_report_v2_is_not_silently_reinterpreted_as_v3() -> None:
    report = AssuranceReport.from_session(
        _session(confidence_z=1.959963984540054),
        release_policy=_release_policy(),
    )
    payload = report.model_dump(mode="json")
    payload["schema_version"] = "agent-evals/assurance-report/v2"

    with pytest.raises(ValidationError, match="schema_version"):
        AssuranceReport.model_validate(payload)


def test_valid_reliability_still_allows_release_acceptance() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS])

    result = ReleaseGate(_release_policy()).decide(report, critical_violations=0)

    assert result.decision is GateDecision.ACCEPT
