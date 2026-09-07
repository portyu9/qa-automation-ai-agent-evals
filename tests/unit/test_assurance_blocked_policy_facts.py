from __future__ import annotations

from agent_evals.assurance.report import AssuranceReport
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import GateDecision, ReleasePolicy
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

_SUBJECT = "a" * 64
_SCENARIO = EvaluationScenario(
    scenario_id="assurance.blocked-known-policy-fact",
    revision="1",
    kind=ScenarioKind.REGRESSION,
    objective="Preserve known critical policy facts when a different relation remains blocked.",
    required_outcomes={"status": "ok"},
)
_POLICY = ReleasePolicy(
    min_resolved_trials=20,
    min_success_rate=1.0,
    min_wilson_low=0.80,
    max_critical_violations=0,
    max_blocked_trials=1,
    max_inconclusive_trials=0,
)


def _pass_trial(index: int) -> EvaluatedTrial:
    evidence = TrialEvidence(
        trial_id=f"pass-{index}",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO.identity,
        final_state={"status": "ok"},
    )
    oracle_results = grade_deterministic_evidence(_SCENARIO, evidence)
    assert all(result.verdict is TrialVerdict.PASS for result in oracle_results)
    return EvaluatedTrial(
        evidence=evidence,
        oracle_results=oracle_results,
        verdict=TrialVerdict.PASS,
    )


def _blocked_trial(*, include_policy_violation: bool) -> EvaluatedTrial:
    events: list[EvidenceEvent] = []
    if include_policy_violation:
        events.append(
            EvidenceEvent(
                sequence=len(events),
                kind=EvidenceKind.POLICY_VIOLATION,
                source="openai-agents:runner",
                payload={"reason": "turn budget exceeded", "max_turns": 2},
                critical=True,
            )
        )
    events.append(
        EvidenceEvent(
            sequence=len(events),
            kind=EvidenceKind.EVALUATION_ERROR,
            source="evaluator:approval-intent",
            payload={
                "code": "approval_intent_unverified",
                "reason": "approval continuation relation could not be reconstructed",
            },
            critical=True,
        )
    )
    evidence = TrialEvidence(
        trial_id=("blocked-with-policy" if include_policy_violation else "blocked-evaluator-only"),
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO.identity,
        events=tuple(events),
        final_state={"status": "ok"},
    )
    return EvaluatedTrial(
        evidence=evidence,
        oracle_results=(),
        verdict=TrialVerdict.BLOCKED,
    )


def _report(*, include_policy_violation: bool) -> AssuranceReport:
    trials = (
        *(_pass_trial(index) for index in range(20)),
        _blocked_trial(include_policy_violation=include_policy_violation),
    )
    reliability = ReliabilityReport.from_verdicts(tuple(trial.verdict for trial in trials))
    assert reliability.resolved_trials == 20
    assert reliability.success_rate == 1.0
    assert reliability.wilson_low >= 0.80
    session = EvaluationSessionResult(
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO.identity,
        trials=trials,
        reliability=reliability,
    )
    return AssuranceReport.from_session(
        session,
        scenario=_SCENARIO,
        release_policy=_POLICY,
    )


def test_blocked_explicit_policy_violation_remains_noncompensatory_at_release_gate() -> None:
    report = _report(include_policy_violation=True)

    assert report.trials[-1].verdict is TrialVerdict.BLOCKED
    assert report.reliability.blocked == 1
    assert report.critical_violations == 1
    assert report.gate.decision is GateDecision.REJECT


def test_evaluator_only_blocked_trial_remains_subject_to_configured_blocked_tolerance() -> None:
    report = _report(include_policy_violation=False)

    assert report.trials[-1].verdict is TrialVerdict.BLOCKED
    assert report.reliability.blocked == 1
    assert report.critical_violations == 0
    assert report.gate.decision is GateDecision.ACCEPT
