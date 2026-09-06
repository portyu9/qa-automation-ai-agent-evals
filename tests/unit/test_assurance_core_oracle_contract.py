from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.assurance.report import AssuranceReport, OracleSnapshot
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import GateDecision, ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

SUBJECT = "a" * 64
SCENARIO_CONTRACT = EvaluationScenario(
    scenario_id="assurance.core-oracles",
    revision="1",
    kind=ScenarioKind.REGRESSION,
    objective="Exercise deterministic assurance oracle binding.",
)


def _policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=0,
        max_inconclusive_trials=0,
    )


def _evidence(
    scenario: EvaluationScenario = SCENARIO_CONTRACT,
    *,
    events: tuple[EvidenceEvent, ...] = (),
    final_state: dict[str, object] | None = None,
) -> TrialEvidence:
    return TrialEvidence(
        trial_id="trial-0",
        subject_identity=SUBJECT,
        scenario_identity=scenario.identity,
        events=events,
        final_state={} if final_state is None else final_state,
    )


def _session(
    oracle_results: tuple[OracleResult, ...],
    *,
    verdict: TrialVerdict,
    scenario: EvaluationScenario = SCENARIO_CONTRACT,
    evidence: TrialEvidence | None = None,
) -> EvaluationSessionResult:
    bound_evidence = evidence if evidence is not None else _evidence(scenario)
    trial = EvaluatedTrial(
        evidence=bound_evidence,
        oracle_results=oracle_results,
        verdict=verdict,
    )
    return EvaluationSessionResult(
        subject_identity=SUBJECT,
        scenario_identity=scenario.identity,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((verdict,), k=1),
    )


def _report(
    session: EvaluationSessionResult,
    *,
    scenario: EvaluationScenario = SCENARIO_CONTRACT,
) -> AssuranceReport:
    return AssuranceReport.from_session(
        session,
        scenario=scenario,
        release_policy=_policy(),
    )


def _valid_pass_report() -> AssuranceReport:
    evidence = _evidence()
    return _report(
        _session(
            grade_deterministic_evidence(SCENARIO_CONTRACT, evidence),
            verdict=TrialVerdict.PASS,
            evidence=evidence,
        )
    )


def test_from_session_rejects_resolved_trial_without_policy_oracle() -> None:
    session = _session(
        (OracleResult(name="outcome", verdict=TrialVerdict.PASS),),
        verdict=TrialVerdict.PASS,
    )

    with pytest.raises(ValueError, match="missing core oracle results: policy"):
        _report(session)


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
        _report(session)


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
    request = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.TOOL_REQUEST,
        source="adapter:test",
        payload={"tool": "forbidden-tool", "call_id": "call-1", "arguments": "{}"},
    )
    evidence = _evidence(events=(request,))
    results = grade_deterministic_evidence(SCENARIO_CONTRACT, evidence)

    assert results[0].verdict is TrialVerdict.FAIL
    report = _report(
        _session(
            results,
            verdict=TrialVerdict.FAIL,
            evidence=evidence,
        )
    )

    assert report.critical_violations == 1
    assert report.gate.decision is GateDecision.REJECT


def test_valid_outcome_failure_remains_noncritical() -> None:
    scenario = EvaluationScenario(
        scenario_id="assurance.core-oracles.outcome-failure",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Exercise non-critical deterministic outcome failure.",
        required_outcomes={"ok": True},
    )
    evidence = _evidence(scenario, final_state={"ok": False})
    results = grade_deterministic_evidence(scenario, evidence)

    assert results[1].verdict is TrialVerdict.FAIL
    report = _report(
        _session(
            results,
            verdict=TrialVerdict.FAIL,
            scenario=scenario,
            evidence=evidence,
        ),
        scenario=scenario,
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


def test_from_session_rejects_unconfigured_custom_deterministic_oracle() -> None:
    session = _session(
        (
            OracleResult(name="policy", verdict=TrialVerdict.PASS),
            OracleResult(name="outcome", verdict=TrialVerdict.PASS),
            OracleResult(name="custom-deterministic", verdict=TrialVerdict.PASS),
        ),
        verdict=TrialVerdict.PASS,
    )

    with pytest.raises(
        ValueError,
        match="deterministic oracle results do not match scenario/evidence grading",
    ):
        _report(session)


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
        _report(session)
