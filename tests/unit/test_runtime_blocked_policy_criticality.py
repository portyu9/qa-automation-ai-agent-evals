from __future__ import annotations

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.gates.release import GateDecision, ReleaseGate, ReleasePolicy
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.evaluator import EvaluatedTrial
from agent_evals.runtime.session import EvaluationSessionResult
from agent_evals.statistics.reliability import ReliabilityReport

_SUBJECT = "a" * 64
_SCENARIO = "b" * 64


def _policy_event(sequence: int, *, critical: bool = True) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.POLICY_VIOLATION,
        source="openai-agents:runner",
        payload={"reason": f"policy violation {sequence + 1}"},
        critical=critical,
    )


def _blocking_error(sequence: int) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.EVALUATION_ERROR,
        source="evaluator:approval-intent",
        payload={
            "code": "approval_intent_unverified",
            "reason": "approval continuation relation could not be reconstructed",
        },
        critical=True,
    )


def _blocked_trial(*, policy_events: int, critical: bool = True) -> EvaluatedTrial:
    events = [
        _policy_event(sequence, critical=critical)
        for sequence in range(policy_events)
    ]
    events.append(_blocking_error(len(events)))
    return EvaluatedTrial(
        evidence=TrialEvidence(
            trial_id=f"blocked-{policy_events}",
            subject_identity=_SUBJECT,
            scenario_identity=_SCENARIO,
            events=tuple(events),
        ),
        oracle_results=(),
        verdict=TrialVerdict.BLOCKED,
    )


def _resolved_trial(*, failed: bool, trial_id: str = "resolved") -> EvaluatedTrial:
    verdict = TrialVerdict.FAIL if failed else TrialVerdict.PASS
    return EvaluatedTrial(
        evidence=TrialEvidence(
            trial_id=trial_id,
            subject_identity=_SUBJECT,
            scenario_identity=_SCENARIO,
        ),
        oracle_results=(
            OracleResult(
                name="policy",
                verdict=verdict,
                critical=True,
                reasons=(("resolved policy violation",) if failed else ()),
            ),
        ),
        verdict=verdict,
    )


def _session(trials: tuple[EvaluatedTrial, ...]) -> EvaluationSessionResult:
    return EvaluationSessionResult(
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        trials=trials,
        reliability=ReliabilityReport.from_verdicts(
            tuple(trial.verdict for trial in trials)
        ),
    )


def test_blocked_explicit_policy_fact_counts_once_in_trial_and_session() -> None:
    blocked = _blocked_trial(policy_events=1)
    session = _session((blocked,))

    assert blocked.verdict is TrialVerdict.BLOCKED
    assert blocked.oracle_results == ()
    assert blocked.critical_violations == 1
    assert session.critical_violations == 1


def test_multiple_blocked_policy_events_count_once_even_when_not_marked_critical() -> None:
    blocked = _blocked_trial(policy_events=2, critical=False)

    assert sum(
        event.kind is EvidenceKind.POLICY_VIOLATION for event in blocked.evidence.events
    ) == 2
    assert all(
        not event.critical
        for event in blocked.evidence.events
        if event.kind is EvidenceKind.POLICY_VIOLATION
    )
    assert blocked.critical_violations == 1


def test_evaluator_only_blocked_trial_remains_zero_critical() -> None:
    blocked = _blocked_trial(policy_events=0)

    assert blocked.critical_violations == 0
    assert _session((blocked,)).critical_violations == 0


def test_resolved_critical_oracle_failure_semantics_are_unchanged() -> None:
    failed = _resolved_trial(failed=True)
    passed = _resolved_trial(failed=False, trial_id="resolved-pass")

    assert failed.critical_violations == 1
    assert passed.critical_violations == 0
    assert _session((failed, passed)).critical_violations == 1


def test_in_memory_release_path_rejects_permitted_blocked_known_policy_fact() -> None:
    trials = (
        *(
            _resolved_trial(failed=False, trial_id=f"pass-{index}")
            for index in range(20)
        ),
        _blocked_trial(policy_events=1),
    )
    session = _session(trials)
    policy = ReleasePolicy(
        min_resolved_trials=20,
        min_success_rate=1.0,
        min_wilson_low=0.80,
        max_critical_violations=0,
        max_blocked_trials=1,
        max_inconclusive_trials=0,
    )

    assert session.reliability.resolved_trials == 20
    assert session.reliability.success_rate == 1.0
    assert session.reliability.wilson_low >= 0.80
    assert session.reliability.blocked == 1
    assert session.critical_violations == 1
    assert (
        ReleaseGate(policy).decide(
            session.reliability,
            critical_violations=session.critical_violations,
        ).decision
        is GateDecision.REJECT
    )
