from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.assurance.report import AssuranceReport
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.gates.release import ReleasePolicy
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


def _report() -> AssuranceReport:
    evidence = TrialEvidence(
        trial_id="trial-0",
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
    )
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=(OracleResult(name="outcome", verdict=TrialVerdict.PASS),),
        verdict=TrialVerdict.PASS,
    )
    reliability = ReliabilityReport.from_verdicts((TrialVerdict.PASS,), k=1)
    session = EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        trials=(trial,),
        reliability=reliability,
    )
    return AssuranceReport.from_session(session, release_policy=_policy())


@pytest.mark.parametrize(
    "field",
    [
        "min_resolved_trials",
        "min_success_rate",
        "min_wilson_low",
        "max_critical_violations",
        "max_blocked_trials",
        "max_inconclusive_trials",
    ],
)
def test_release_policy_rejects_numeric_string_type_drift(field: str) -> None:
    data = _policy().model_dump(mode="python")
    data[field] = str(data[field])

    with pytest.raises(ValidationError):
        ReleasePolicy.model_validate(data)


@pytest.mark.parametrize(
    "field",
    [
        "min_resolved_trials",
        "max_critical_violations",
        "max_blocked_trials",
        "max_inconclusive_trials",
    ],
)
def test_release_policy_integer_fields_reject_bool_and_integral_float(field: str) -> None:
    original = _policy().model_dump(mode="python")
    valid_value = original[field]

    for invalid in (True, float(valid_value)):
        data = dict(original)
        data[field] = invalid
        with pytest.raises(ValidationError):
            ReleasePolicy.model_validate(data)


def test_release_policy_strict_float_fields_accept_numeric_json_integers() -> None:
    policy = ReleasePolicy(min_success_rate=0, min_wilson_low=1)

    assert policy.min_success_rate == 0.0
    assert policy.min_wilson_low == 1.0


def test_report_rejects_root_preserving_release_policy_json_type_drift() -> None:
    report = _report()
    payload = report.model_dump(mode="json")
    original_root = payload["report_root"]
    payload["release_policy"]["max_blocked_trials"] = str(
        payload["release_policy"]["max_blocked_trials"]
    )

    assert payload["report_root"] == original_root
    with pytest.raises(ValidationError):
        AssuranceReport.model_validate(payload)


def test_valid_release_policy_assurance_report_json_round_trip_remains_supported() -> None:
    report = _report()

    assert AssuranceReport.model_validate_json(report.model_dump_json()) == report
