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


def _policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=0,
        max_inconclusive_trials=0,
    )


def _session(
    oracle_results: tuple[OracleResult, ...],
    *,
    verdict: TrialVerdict,
) -> EvaluationSessionResult:
    trial = EvaluatedTrial(
        evidence=TrialEvidence(
            trial_id="trial-0",
            subject_identity=SUBJECT,
            scenario_identity=SCENARIO,
        ),
        oracle_results=oracle_results,
        verdict=verdict,
    )
    return EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((verdict,), k=1),
    )


def _valid_pass_report() -> AssuranceReport:
    return AssuranceReport.from_session(
        _session(
            (
                OracleResult(name="policy", verdict=TrialVerdict.PASS),
                OracleResult(name="outcome", verdict=TrialVerdict.PASS),
            ),
            verdict=TrialVerdict.PASS,
        ),
        release_policy=_policy(),
    )


def test_from_session_rejects_resolved_trial_without_policy_oracle() -> None:
    session = _session(
        (OracleResult(name="outcome", verdict=TrialVerdict.PASS),),
        verdict=TrialVerdict.PASS,
    )

    with pytest.raises(ValueError, match="missing core oracle results: policy"):
        AssuranceReport.from_session(session, release_policy=_policy())


def test_from_session_rejects_resolved_trial_without_outcome_oracle() -> None:
    session = _session(
        (
            OracleResult(
                name="policy",
                verdict=TrialVerdict.FAIL,
                critical=True,
            ),
        ),
        verdict=TrialVerdict.FAIL,
    )

    with pytest.raises(ValueError, match="missing core oracle results: outcome"):
        AssuranceReport.from_session(session, release_policy=_policy())


@pytest.mark.parametrize(
    ("name", "verdict", "critical"),
    (
        ("policy", TrialVerdict.FAIL, False),
        ("policy", TrialVerdict.PASS, True),
        ("side-effect-idempotency", TrialVerdict.FAIL, False),
        ("side-effect-idempotency", TrialVerdict.PASS, True),
    ),
)
def test_known_fail_closed_oracles_reject_impossible_criticality(
    name: str,
    verdict: TrialVerdict,
    critical: bool,
) -> None:
    with pytest.raises(ValidationError, match="criticality does not match deterministic runtime"):
        OracleSnapshot(
            name=name,
            verdict=verdict,
            critical=critical,
        )


def test_outcome_oracle_cannot_claim_critical_authority() -> None:
    with pytest.raises(ValidationError, match="outcome oracle cannot claim critical authority"):
        OracleSnapshot(
            name="outcome",
            verdict=TrialVerdict.FAIL,
            critical=True,
        )


def test_valid_policy_and_outcome_pass_remain_accepted() -> None:
    report = _valid_pass_report()

    assert report.trials[0].verdict is TrialVerdict.PASS
    assert report.critical_violations == 0
    assert report.gate.decision is GateDecision.ACCEPT


def test_valid_policy_failure_remains_noncompensatory() -> None:
    report = AssuranceReport.from_session(
        _session(
            (
                OracleResult(
                    name="policy",
                    verdict=TrialVerdict.FAIL,
                    critical=True,
                ),
                OracleResult(name="outcome", verdict=TrialVerdict.PASS),
            ),
            verdict=TrialVerdict.FAIL,
        ),
        release_policy=_policy(),
    )

    assert report.critical_violations == 1
    assert report.gate.decision is GateDecision.REJECT


def test_valid_outcome_failure_remains_noncritical() -> None:
    report = AssuranceReport.from_session(
        _session(
            (
                OracleResult(name="policy", verdict=TrialVerdict.PASS),
                OracleResult(name="outcome", verdict=TrialVerdict.FAIL),
            ),
            verdict=TrialVerdict.FAIL,
        ),
        release_policy=_policy(),
    )

    assert report.trials[0].verdict is TrialVerdict.FAIL
    assert report.critical_violations == 0


def test_valid_side_effect_failure_criticality_snapshot_is_accepted() -> None:
    snapshot = OracleSnapshot(
        name="side-effect-idempotency",
        verdict=TrialVerdict.FAIL,
        critical=True,
    )

    assert snapshot.critical is True
    assert snapshot.verdict is TrialVerdict.FAIL


def test_additional_custom_oracle_cannot_replace_but_may_extend_core_set() -> None:
    report = AssuranceReport.from_session(
        _session(
            (
                OracleResult(name="policy", verdict=TrialVerdict.PASS),
                OracleResult(name="outcome", verdict=TrialVerdict.PASS),
                OracleResult(name="custom-deterministic", verdict=TrialVerdict.PASS),
            ),
            verdict=TrialVerdict.PASS,
        ),
        release_policy=_policy(),
    )

    assert tuple(result.name for result in report.trials[0].oracle_results) == (
        "policy",
        "outcome",
        "custom-deterministic",
    )


def test_report_json_reload_rejects_missing_core_oracle_before_root_can_authorize_it() -> None:
    report = _valid_pass_report()
    payload = report.model_dump(mode="json")
    payload["trials"][0]["oracle_results"] = [
        result for result in payload["trials"][0]["oracle_results"] if result["name"] != "policy"
    ]

    with pytest.raises(ValidationError, match="missing core oracle results: policy"):
        AssuranceReport.model_validate(payload)


def test_from_session_rejects_policy_criticality_downgrade_before_release_gate() -> None:
    session = _session(
        (
            OracleResult(
                name="policy",
                verdict=TrialVerdict.FAIL,
                critical=False,
            ),
            OracleResult(name="outcome", verdict=TrialVerdict.PASS),
        ),
        verdict=TrialVerdict.FAIL,
    )

    with pytest.raises(ValueError, match="criticality does not match deterministic runtime"):
        AssuranceReport.from_session(session, release_policy=_policy())
