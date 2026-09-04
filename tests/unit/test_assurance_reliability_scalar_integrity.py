from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.assurance.report import AssuranceReport, ReliabilitySnapshot
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.gates.release import ReleasePolicy
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
            OracleResult(name="outcome", verdict=TrialVerdict.PASS),
        ),
        verdict=TrialVerdict.PASS,
    )
    reliability = ReliabilityReport.from_verdicts((TrialVerdict.PASS,), k=1)
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
    )
    return AssuranceReport.from_session(session, release_policy=policy)


@pytest.mark.parametrize(
    "field",
    [
        "trials",
        "resolved_trials",
        "passes",
        "failures",
        "blocked",
        "inconclusive",
        "success_rate",
        "wilson_low",
        "wilson_high",
        "pass_at_k",
        "pass_power_k",
        "k",
    ],
)
def test_reliability_snapshot_rejects_numeric_string_type_drift(field: str) -> None:
    data = _report().reliability.model_dump(mode="python")
    data[field] = str(data[field])

    with pytest.raises(ValidationError):
        ReliabilitySnapshot.model_validate(data)


@pytest.mark.parametrize("field", ["trials", "resolved_trials", "passes", "k"])
def test_reliability_snapshot_integer_fields_reject_bool_and_integral_float(field: str) -> None:
    original = _report().reliability.model_dump(mode="python")
    valid_value = original[field]

    for invalid in (True, float(valid_value)):
        data = dict(original)
        data[field] = invalid
        with pytest.raises(ValidationError):
            ReliabilitySnapshot.model_validate(data)


def test_report_rejects_root_preserving_reliability_json_type_drift() -> None:
    report = _report()
    payload = report.model_dump(mode="json")
    original_root = payload["report_root"]
    payload["reliability"]["trials"] = str(payload["reliability"]["trials"])

    assert payload["report_root"] == original_root
    with pytest.raises(ValidationError):
        AssuranceReport.model_validate(payload)


def test_valid_assurance_report_json_round_trip_remains_supported() -> None:
    report = _report()

    assert AssuranceReport.model_validate_json(report.model_dump_json()) == report
