from __future__ import annotations

import pytest

from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult, OutcomeOracle, PolicyOracle
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

_SUBJECT = "d" * 64
_POLICY = ReleasePolicy(
    min_resolved_trials=1,
    min_success_rate=0.0,
    min_wilson_low=0.0,
    max_critical_violations=1,
    max_blocked_trials=0,
    max_inconclusive_trials=0,
)


def _scenario(**overrides: object) -> EvaluationScenario:
    data: dict[str, object] = {
        "scenario_id": "assurance.deterministic-regrade",
        "revision": "1",
        "kind": ScenarioKind.REGRESSION,
        "objective": "Bind assurance snapshots to deterministic grading authority.",
    }
    data.update(overrides)
    return EvaluationScenario.model_validate(data)


def _evidence(
    scenario: EvaluationScenario,
    *,
    events: tuple[EvidenceEvent, ...] = (),
    final_state: dict[str, object] | None = None,
) -> TrialEvidence:
    return TrialEvidence(
        trial_id="deterministic-regrade",
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        events=events,
        final_state={} if final_state is None else final_state,
    )


def _session(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
    *,
    oracle_results: tuple[OracleResult, ...],
    verdict: TrialVerdict,
) -> EvaluationSessionResult:
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=oracle_results,
        verdict=verdict,
    )
    return EvaluationSessionResult(
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        trials=(trial,),
        reliability=ReliabilityReport.from_verdicts((verdict,)),
    )


def _report(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
    *,
    oracle_results: tuple[OracleResult, ...],
    verdict: TrialVerdict,
) -> AssuranceReport:
    return AssuranceReport.from_session(
        _session(
            scenario,
            evidence,
            oracle_results=oracle_results,
            verdict=verdict,
        ),
        scenario=scenario,
        release_policy=_POLICY,
    )


def _forged_pass_results() -> tuple[OracleResult, ...]:
    return (
        OracleResult(name="policy", verdict=TrialVerdict.PASS),
        OracleResult(name="outcome", verdict=TrialVerdict.PASS),
    )


def test_report_rejects_forged_outcome_pass_over_wrong_terminal_state() -> None:
    scenario = _scenario(required_outcomes={"ok": True})
    evidence = _evidence(scenario, final_state={"ok": False})

    actual = OutcomeOracle().grade(scenario, evidence)
    assert actual.verdict is TrialVerdict.FAIL

    with pytest.raises(
        ValueError,
        match="deterministic oracle results do not match scenario/evidence grading",
    ):
        _report(
            scenario,
            evidence,
            oracle_results=_forged_pass_results(),
            verdict=TrialVerdict.PASS,
        )


def test_report_rejects_forged_policy_pass_over_unauthorized_tool_request() -> None:
    scenario = _scenario(authority=AuthorityPolicy())
    request = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.TOOL_REQUEST,
        source="adapter:test",
        payload={"tool": "forbidden_tool", "call_id": "call-1", "arguments": "{}"},
    )
    evidence = _evidence(scenario, events=(request,))

    actual = PolicyOracle().grade(scenario, evidence)
    assert actual.verdict is TrialVerdict.FAIL
    assert actual.critical is True

    with pytest.raises(
        ValueError,
        match="deterministic oracle results do not match scenario/evidence grading",
    ):
        _report(
            scenario,
            evidence,
            oracle_results=_forged_pass_results(),
            verdict=TrialVerdict.PASS,
        )


def test_report_rejects_oracle_reason_drift_even_when_verdict_matches() -> None:
    scenario = _scenario()
    evidence = _evidence(scenario)
    forged = (
        OracleResult(
            name="policy",
            verdict=TrialVerdict.PASS,
            reasons=("invented explanation not produced by deterministic grading",),
        ),
        OracleResult(name="outcome", verdict=TrialVerdict.PASS),
    )

    assert all(result.verdict is TrialVerdict.PASS for result in forged)
    with pytest.raises(
        ValueError,
        match="deterministic oracle results do not match scenario/evidence grading",
    ):
        _report(
            scenario,
            evidence,
            oracle_results=forged,
            verdict=TrialVerdict.PASS,
        )


def test_report_accepts_exact_rederived_ordinary_pass_results() -> None:
    scenario = _scenario()
    evidence = _evidence(scenario)
    results = grade_deterministic_evidence(scenario, evidence)

    report = _report(
        scenario,
        evidence,
        oracle_results=results,
        verdict=TrialVerdict.PASS,
    )

    assert tuple(result.name for result in results) == ("policy", "outcome")
    assert tuple(result.name for result in report.trials[0].oracle_results) == (
        "policy",
        "outcome",
    )


def test_report_accepts_exact_rederived_outcome_failure() -> None:
    scenario = _scenario(required_outcomes={"ok": True})
    evidence = _evidence(scenario, final_state={"ok": False})
    results = grade_deterministic_evidence(scenario, evidence)

    assert results[0].verdict is TrialVerdict.PASS
    assert results[1].verdict is TrialVerdict.FAIL
    report = _report(
        scenario,
        evidence,
        oracle_results=results,
        verdict=TrialVerdict.FAIL,
    )

    assert report.trials[0].verdict is TrialVerdict.FAIL
    assert report.trials[0].oracle_results[1].reasons == results[1].reasons
