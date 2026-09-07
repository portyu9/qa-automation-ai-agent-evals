from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

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


def _blocked_trial(
    *,
    policy_violation_count: int,
    policy_event_critical: bool = True,
) -> EvaluatedTrial:
    events = [
        EvidenceEvent(
            sequence=index,
            kind=EvidenceKind.POLICY_VIOLATION,
            source="openai-agents:runner",
            payload={
                "reason": "turn budget exceeded" if index == 0 else f"policy violation {index + 1}",
                "max_turns": 2,
            },
            critical=policy_event_critical,
        )
        for index in range(policy_violation_count)
    ]
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
        trial_id=f"blocked-with-{policy_violation_count}-policy-events",
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


def _report_for_blocked(blocked: EvaluatedTrial) -> AssuranceReport:
    trials = (*(_pass_trial(index) for index in range(20)), blocked)
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


def _report(*, include_policy_violation: bool) -> AssuranceReport:
    return _report_for_blocked(
        _blocked_trial(policy_violation_count=int(include_policy_violation))
    )


def test_blocked_explicit_policy_violation_remains_noncompensatory_at_release_gate() -> None:
    report = _report(include_policy_violation=True)

    assert report.schema_version == "agent-evals/assurance-report/v5"
    assert report.trials[-1].verdict is TrialVerdict.BLOCKED
    assert report.reliability.blocked == 1
    assert report.critical_violations == 1
    assert report.gate.decision is GateDecision.REJECT


def test_blocked_policy_snapshot_binds_exact_source_event() -> None:
    blocked = _blocked_trial(policy_violation_count=1)
    source_event = blocked.evidence.events[0]
    report = _report_for_blocked(blocked)

    (snapshot,) = report.trials[-1].blocked_policy_violations
    assert snapshot.sequence == source_event.sequence
    assert snapshot.event_digest == source_event.digest
    assert snapshot.source == source_event.source
    assert snapshot.reason == "turn budget exceeded"


def test_policy_event_critical_flag_does_not_override_policy_oracle_semantics() -> None:
    blocked = _blocked_trial(
        policy_violation_count=1,
        policy_event_critical=False,
    )
    report = _report_for_blocked(blocked)

    assert blocked.evidence.events[0].critical is False
    assert len(report.trials[-1].blocked_policy_violations) == 1
    assert report.critical_violations == 1
    assert report.gate.decision is GateDecision.REJECT


def test_multiple_blocked_policy_events_are_preserved_but_count_as_one_policy_failure() -> None:
    blocked = _blocked_trial(policy_violation_count=2)
    report = _report_for_blocked(blocked)
    snapshots = report.trials[-1].blocked_policy_violations

    assert len(snapshots) == 2
    assert tuple(snapshot.sequence for snapshot in snapshots) == (0, 1)
    assert tuple(snapshot.event_digest for snapshot in snapshots) == tuple(
        event.digest for event in blocked.evidence.events[:2]
    )
    assert report.critical_violations == 1
    assert report.gate.decision is GateDecision.REJECT


def test_evaluator_only_blocked_trial_remains_subject_to_configured_blocked_tolerance() -> None:
    report = _report(include_policy_violation=False)

    assert report.trials[-1].verdict is TrialVerdict.BLOCKED
    assert report.trials[-1].blocked_policy_violations == ()
    assert report.reliability.blocked == 1
    assert report.critical_violations == 0
    assert report.gate.decision is GateDecision.ACCEPT


def test_nonblocked_trial_cannot_smuggle_blocked_policy_authority() -> None:
    report = _report(include_policy_violation=True)
    payload = report.model_dump(mode="json")
    payload["trials"][0]["blocked_policy_violations"] = deepcopy(
        payload["trials"][-1]["blocked_policy_violations"]
    )

    with pytest.raises(
        ValidationError,
        match="non-blocked assurance trial cannot contain blocked policy-violation snapshots",
    ):
        AssuranceReport.model_validate(payload)


def test_blocked_policy_review_material_is_bound_by_report_root() -> None:
    report = _report(include_policy_violation=True)
    payload = report.model_dump(mode="json")
    payload["trials"][-1]["blocked_policy_violations"][0]["reason"] = "forged review reason"

    with pytest.raises(ValidationError, match="report root does not match report content"):
        AssuranceReport.model_validate(payload)
