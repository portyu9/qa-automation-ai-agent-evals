from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent_evals.assurance.report import AssuranceReport
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.gates.release import GateDecision, ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def evaluated_trial(
    trial_id: str,
    verdict: TrialVerdict,
    *,
    critical: bool = False,
    subject_identity: str = SUBJECT,
    scenario_identity: str = SCENARIO,
) -> EvaluatedTrial:
    evidence = TrialEvidence(
        trial_id=trial_id,
        subject_identity=subject_identity,
        scenario_identity=scenario_identity,
        final_state={"trial": trial_id},
    )
    oracle_results: tuple[OracleResult, ...] = ()
    if verdict in (TrialVerdict.PASS, TrialVerdict.FAIL):
        oracle_results = (
            OracleResult(
                name="policy" if critical else "outcome",
                verdict=verdict,
                critical=critical,
            ),
        )
    return EvaluatedTrial(
        evidence=evidence,
        oracle_results=oracle_results,
        verdict=verdict,
    )


def session_result() -> EvaluationSessionResult:
    trials = (
        evaluated_trial("trial-0", TrialVerdict.PASS),
        evaluated_trial("trial-1", TrialVerdict.FAIL, critical=True),
        evaluated_trial("trial-2", TrialVerdict.BLOCKED),
    )
    return EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        trials=trials,
        reliability=ReliabilityReport.from_verdicts(
            tuple(trial.verdict for trial in trials),
            k=2,
        ),
    )


def release_policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=2,
        min_success_rate=0.75,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=1,
        max_inconclusive_trials=0,
    )


def test_report_binds_trial_roots_oracles_schema_and_release_decision() -> None:
    session = session_result()
    report = AssuranceReport.from_session(session, release_policy=release_policy())

    assert report.evidence_schema == "agent-evals/trial-evidence/v2"
    assert report.subject_identity == SUBJECT
    assert report.scenario_identity == SCENARIO
    assert tuple(record.trial_id for record in report.trials) == (
        "trial-0",
        "trial-1",
        "trial-2",
    )
    assert tuple(record.evidence_root for record in report.trials) == tuple(
        trial.evidence.evidence_root for trial in session.trials
    )
    assert report.trials[0].oracle_results[0].verdict is TrialVerdict.PASS
    assert report.trials[1].oracle_results[0].critical is True
    assert report.trials[2].oracle_results == ()
    assert report.reliability == report.reliability.from_reliability(session.reliability)
    assert report.critical_violations == 1
    assert report.gate.decision is GateDecision.REJECT
    assert len(report.report_root) == 64


def test_report_json_round_trip_revalidates_all_derived_claims() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())

    loaded = AssuranceReport.model_validate_json(report.model_dump_json())

    assert loaded == report


def test_evidence_schema_is_strictly_version_bound() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["evidence_schema"] = "agent-evals/trial-evidence/v3"

    with pytest.raises(ValidationError, match="evidence_schema"):
        AssuranceReport.model_validate(payload)


def test_resolved_trial_requires_oracle_results() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["trials"][0]["oracle_results"] = []

    with pytest.raises(ValidationError, match="requires deterministic oracle results"):
        AssuranceReport.model_validate(payload)


def test_resolved_trial_rejects_nonresolved_oracle_verdict() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["trials"][0]["oracle_results"][0]["verdict"] = TrialVerdict.BLOCKED.value

    with pytest.raises(ValidationError, match="non-resolved oracle verdict"):
        AssuranceReport.model_validate(payload)


def test_duplicate_oracle_names_are_rejected() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["trials"][0]["oracle_results"].append(
        deepcopy(payload["trials"][0]["oracle_results"][0])
    )

    with pytest.raises(ValidationError, match="oracle names must be unique"):
        AssuranceReport.model_validate(payload)


def test_forged_trial_verdict_is_rejected_from_oracle_snapshots() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["trials"][0]["verdict"] = TrialVerdict.FAIL.value

    with pytest.raises(ValidationError, match="verdict does not recompute from oracle results"):
        AssuranceReport.model_validate(payload)


def test_blocked_trial_cannot_smuggle_completed_oracle_results() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["trials"][2]["oracle_results"] = payload["trials"][0]["oracle_results"]

    with pytest.raises(ValidationError, match="blocked assurance trial cannot contain"):
        AssuranceReport.model_validate(payload)


def test_forged_reliability_is_rejected_even_when_schema_valid() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["reliability"]["success_rate"] = 0.75

    with pytest.raises(ValidationError, match="reliability does not recompute"):
        AssuranceReport.model_validate(payload)


def test_forged_gate_decision_is_rejected() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["gate"]["decision"] = GateDecision.ACCEPT.value
    payload["gate"]["reasons"] = []

    with pytest.raises(ValidationError, match="gate does not recompute"):
        AssuranceReport.model_validate(payload)


def test_forged_oracle_criticality_requires_gate_recomputation() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["trials"][1]["oracle_results"][0]["critical"] = False

    with pytest.raises(ValidationError, match="gate does not recompute"):
        AssuranceReport.model_validate(payload)


def test_release_policy_drift_requires_gate_recomputation() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["release_policy"]["max_critical_violations"] = 2
    payload["release_policy"]["min_success_rate"] = 0.0

    with pytest.raises(ValidationError, match="gate does not recompute"):
        AssuranceReport.model_validate(payload)


def test_evidence_root_drift_is_caught_by_report_root() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["trials"][0]["evidence_root"] = "c" * 64

    with pytest.raises(ValidationError, match="report root does not match"):
        AssuranceReport.model_validate(payload)


def test_report_root_tampering_is_rejected() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = report.model_dump(mode="json")
    payload["report_root"] = "0" * 64

    with pytest.raises(ValidationError, match="report root does not match"):
        AssuranceReport.model_validate(payload)


def test_duplicate_trial_ids_are_rejected_on_load() -> None:
    report = AssuranceReport.from_session(session_result(), release_policy=release_policy())
    payload = deepcopy(report.model_dump(mode="json"))
    payload["trials"][1]["trial_id"] = payload["trials"][0]["trial_id"]

    with pytest.raises(ValidationError, match="trial IDs must be unique"):
        AssuranceReport.model_validate(payload)


def test_from_session_rejects_empty_session() -> None:
    empty = EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        trials=(),
        reliability=ReliabilityReport(
            trials=0,
            resolved_trials=0,
            passes=0,
            failures=0,
            blocked=0,
            inconclusive=0,
            success_rate=0.0,
            wilson_low=0.0,
            wilson_high=1.0,
            pass_at_k=0.0,
            pass_power_k=0.0,
            k=1,
        ),
    )

    with pytest.raises(ValueError, match="at least one evaluated trial"):
        AssuranceReport.from_session(empty, release_policy=release_policy())


def test_from_session_rejects_stale_reliability() -> None:
    session = session_result()
    stale = EvaluationSessionResult(
        subject_identity=session.subject_identity,
        scenario_identity=session.scenario_identity,
        trials=session.trials,
        reliability=ReliabilityReport.from_verdicts(
            (TrialVerdict.PASS, TrialVerdict.PASS, TrialVerdict.BLOCKED),
            k=2,
        ),
    )

    with pytest.raises(ValueError, match="session reliability does not recompute"):
        AssuranceReport.from_session(stale, release_policy=release_policy())


def test_from_session_rejects_trial_subject_identity_mismatch() -> None:
    session = session_result()
    mismatched_trial = evaluated_trial(
        "trial-0",
        TrialVerdict.PASS,
        subject_identity="c" * 64,
    )
    mismatched = EvaluationSessionResult(
        subject_identity=session.subject_identity,
        scenario_identity=session.scenario_identity,
        trials=(mismatched_trial, *session.trials[1:]),
        reliability=session.reliability,
    )

    with pytest.raises(ValueError, match="subject identity does not match"):
        AssuranceReport.from_session(mismatched, release_policy=release_policy())


def test_from_session_rejects_trial_scenario_identity_mismatch() -> None:
    session = session_result()
    mismatched_trial = evaluated_trial(
        "trial-0",
        TrialVerdict.PASS,
        scenario_identity="d" * 64,
    )
    mismatched = EvaluationSessionResult(
        subject_identity=session.subject_identity,
        scenario_identity=session.scenario_identity,
        trials=(mismatched_trial, *session.trials[1:]),
        reliability=session.reliability,
    )

    with pytest.raises(ValueError, match="scenario identity does not match"):
        AssuranceReport.from_session(mismatched, release_policy=release_policy())


def test_from_session_rejects_duplicate_trial_ids() -> None:
    first = evaluated_trial("trial-0", TrialVerdict.PASS)
    duplicate = evaluated_trial("trial-0", TrialVerdict.FAIL, critical=True)
    blocked = evaluated_trial("trial-2", TrialVerdict.BLOCKED)
    trials = (first, duplicate, blocked)
    duplicated = EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        trials=trials,
        reliability=ReliabilityReport.from_verdicts(
            tuple(trial.verdict for trial in trials),
            k=2,
        ),
    )

    with pytest.raises(ValueError, match="duplicate trial IDs"):
        AssuranceReport.from_session(duplicated, release_policy=release_policy())
